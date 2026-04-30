"""
core/kb_store.py — ChromaDB vector store for the KB.

Uses chromadb's built-in DefaultEmbeddingFunction (all-MiniLM-L6-v2 via ONNX).
No sentence-transformers or PyTorch required.

Two storage modes (auto-detected):
  LOCAL  — chromadb.PersistentClient at data/chroma/ (no Docker, default for dev)
  DOCKER — chromadb.HttpClient when CHROMADB_HOST env var is set

Configure via environment variables:
  CHROMADB_HOST   — if set, uses HttpClient at this host (Docker mode)
  CHROMADB_PORT   — port for HttpClient (default 8000)
  KB_COLLECTION   — collection name (default "_knowledge")
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# Singletons — lazy-loaded on first use
_ef         = None   # chromadb DefaultEmbeddingFunction
_client     = None
_collection = None

COLLECTION_NAME = os.getenv("KB_COLLECTION",    "_knowledge")
CHROMA_HOST     = os.getenv("CHROMADB_HOST",    "")      # empty → PersistentClient
CHROMA_PORT     = int(os.getenv("CHROMADB_PORT", "8000"))

# Suppress ChromaDB telemetry
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("CHROMA_TELEMETRY",     "false")


def _get_ef():
    global _ef
    if _ef is None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        _ef = DefaultEmbeddingFunction()
    return _ef


def _get_collection():
    global _client, _collection
    if _collection is None:
        import chromadb

        if CHROMA_HOST:
            _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
            logger.info("ChromaDB: HTTP mode → %s:%d", CHROMA_HOST, CHROMA_PORT)
        else:
            data_dir = Path(__file__).parent.parent / "data" / "chroma"
            data_dir.mkdir(parents=True, exist_ok=True)
            _client = chromadb.PersistentClient(path=str(data_dir))
            logger.info("ChromaDB: local persistent mode → %s", data_dir)

        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=_get_ef(),
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB: collection '%s' ready", COLLECTION_NAME)
    return _collection


def embed(texts: List[str]) -> List[List[float]]:
    return list(_get_ef()(texts))


def upsert_chunks(chunks: List[dict]) -> None:
    """Embed and store chunks in ChromaDB."""
    if not chunks:
        return
    collection = _get_collection()
    texts = [c["text"] for c in chunks]
    collection.upsert(
        ids       = [c["id"]  for c in chunks],
        documents = texts,
        metadatas = [
            {"doc_id": c["doc_id"], "source": c["source"], "chunk_idx": c["chunk_idx"]}
            for c in chunks
        ],
    )
    logger.info("Upserted %d chunks", len(chunks))


def delete_document(doc_id: str) -> int:
    """Delete all chunks for a document. Returns count deleted."""
    collection = _get_collection()
    results    = collection.get(where={"doc_id": doc_id})
    ids        = results.get("ids", [])
    if ids:
        collection.delete(ids=ids)
    return len(ids)


def search(query: str, top_k: int = 5) -> List[dict]:
    """Semantic search — returns top-k most relevant chunks."""
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return []

    results = collection.query(
        query_texts = [query],
        n_results   = min(top_k, count),
        include     = ["documents", "metadatas", "distances"],
    )

    chunks = []
    for text, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({
            "text":            text,
            "source":          meta.get("source",    "unknown"),
            "chunk_idx":       meta.get("chunk_idx", 0),
            "doc_id":          meta.get("doc_id",    ""),
            "relevance_score": round(1 - dist, 4),
        })
    return chunks


def chunk_count() -> int:
    try:
        return _get_collection().count()
    except Exception:
        return 0


def list_unique_documents() -> List[dict]:
    """Return one {doc_id, source} entry per unique document."""
    try:
        collection = _get_collection()
        results    = collection.get(include=["metadatas"])
        seen: dict[str, dict] = {}
        for meta in results.get("metadatas", []):
            doc_id = meta.get("doc_id", "")
            if doc_id and doc_id not in seen:
                seen[doc_id] = {"doc_id": doc_id, "source": meta.get("source", "?")}
        return list(seen.values())
    except Exception:
        return []


def format_kb_context(chunks: List[dict]) -> str:
    """Format retrieved chunks into a labelled context block for LLM injection."""
    if not chunks:
        return ""
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(
            f"[KB SOURCE {i}: {c['source']} | chunk #{c['chunk_idx']} "
            f"| relevance: {c['relevance_score']:.0%}]\n{c['text']}"
        )
    return "\n\n---\n\n".join(parts)
