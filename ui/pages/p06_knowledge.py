"""
ui/pages/p06_knowledge.py — Knowledge Base management page.

Provides three tabs:
  📤 Upload  — ingest PDF, DOCX, TXT, MD, LOG, CSV, JSON into ChromaDB
  📂 Library — view and delete indexed documents
  💬 Query   — direct KB chat with Claude (separate from the triage pipeline)

KB context is also auto-injected into the triage engine system prompt when
relevant documents are found for the failing test.
"""
from __future__ import annotations

import os
import uuid
import streamlit as st

# ── Graceful import guard ─────────────────────────────────────────────────────
# KB features require chromadb + sentence-transformers + optional file parsers.
# Show a friendly install prompt if they are missing rather than crashing.
try:
    from core.kb_ingest import extract_text, chunk_text, SUPPORTED_EXTENSIONS
    from core.kb_store import (
        upsert_chunks, delete_document, search,
        chunk_count, list_unique_documents, format_kb_context,
    )
    _KB_AVAILABLE = True
except ImportError as _kb_err:
    _KB_AVAILABLE = False
    _KB_IMPORT_ERR = str(_kb_err)


def render() -> None:
    # ── Dependency check ──────────────────────────────────────────────────────
    if not _KB_AVAILABLE:
        st.error("Knowledge Base dependencies are not installed.")
        st.code(
            "pip install chromadb==0.5.3 sentence-transformers==3.0.1 "
            "PyMuPDF==1.24.5 python-docx==1.1.2",
            language="bash",
        )
        st.caption(f"Missing: {_KB_IMPORT_ERR}")
        return

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown("## 📚 Knowledge Base")
    st.markdown(
        "Upload runbooks, incident RCAs, and configuration guides. "
        "The triage engine will automatically reference them when diagnosing failures."
    )

    # ── Top-level metrics ─────────────────────────────────────────────────────
    try:
        total_chunks = chunk_count()
        docs         = list_unique_documents()
    except Exception as exc:
        st.warning(f"Could not connect to ChromaDB: {exc}")
        total_chunks = 0
        docs         = []

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Documents",    len(docs))
    col_b.metric("Total Chunks", total_chunks)
    col_c.metric("KB Status",    "Active ✓" if total_chunks > 0 else "Empty")

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_upload, tab_library, tab_query = st.tabs(["📤 Upload", "📂 Library", "💬 Query KB"])

    # ═════════════════════════════════════════════════════════════
    # TAB 1 — UPLOAD
    # ═════════════════════════════════════════════════════════════
    with tab_upload:
        st.markdown("### Upload documents")
        st.caption("Supported: " + " · ".join(f".{e}" for e in sorted(SUPPORTED_EXTENSIONS)))

        uploaded_files = st.file_uploader(
            "Drop files here or click to browse",
            type=list(SUPPORTED_EXTENSIONS),
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        if uploaded_files:
            if st.button("📥 Ingest selected files", type="primary"):
                progress = st.progress(0, text="Starting ingestion…")
                results: list[tuple[str, str, str]] = []

                for i, f in enumerate(uploaded_files):
                    progress.progress(i / len(uploaded_files), text=f"Processing {f.name}…")
                    try:
                        content = f.read()
                        text    = extract_text(content, f.name)
                        if not text.strip():
                            results.append(("⚠️", f.name, "No text extracted — skipped"))
                            continue

                        doc_id = str(uuid.uuid4())
                        chunks = chunk_text(text, doc_id, f.name)
                        upsert_chunks(chunks)

                        if "kb_docs" not in st.session_state:
                            st.session_state.kb_docs = []
                        st.session_state.kb_docs.append({
                            "doc_id":   doc_id,
                            "filename": f.name,
                            "size_kb":  round(len(content) / 1024, 1),
                            "chunks":   len(chunks),
                        })
                        results.append(("✅", f.name, f"{len(chunks)} chunks indexed"))

                    except Exception as exc:
                        results.append(("❌", f.name, str(exc)))

                progress.progress(1.0, text="Done!")
                for icon, name, msg in results:
                    st.markdown(f"{icon} **{name}** — {msg}")
                st.rerun()

        with st.expander("What file types work best?"):
            st.markdown(
                "| Type | Best for |\n|------|----------|\n"
                + "\n".join(f"| `{t}` | {d} |" for t, d in [
                    (".pdf",  "Runbooks, incident reports, SOPs"),
                    (".docx", "Word documents, test procedures"),
                    (".md",   "Wiki pages, RCA logs, Confluence exports"),
                    (".txt",  "Raw device logs, CLI output captures"),
                    (".log",  "Application and system logs"),
                    (".json", "Config dumps, structured test data"),
                    (".csv",  "JIRA / ServiceNow issue exports"),
                ])
            )

    # ═════════════════════════════════════════════════════════════
    # TAB 2 — LIBRARY
    # ═════════════════════════════════════════════════════════════
    with tab_library:
        st.markdown("### Indexed documents")

        docs_live = list_unique_documents()
        if not docs_live:
            st.info("No documents indexed yet. Upload files in the Upload tab.")
        else:
            session_docs = {d["doc_id"]: d for d in st.session_state.get("kb_docs", [])}

            for doc in docs_live:
                meta = session_docs.get(doc["doc_id"], {})
                with st.container():
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        ext = doc["source"].rsplit(".", 1)[-1].upper() if "." in doc["source"] else "?"
                        st.markdown(f"**`{ext}`** {doc['source']}")
                        details = []
                        if meta.get("chunks"):
                            details.append(f"{meta['chunks']} chunks")
                        if meta.get("size_kb"):
                            details.append(f"{meta['size_kb']} KB")
                        details.append("✓ indexed")
                        st.caption(" · ".join(details))
                    with col2:
                        if st.button("🗑", key=f"del_{doc['doc_id']}", help="Remove from KB"):
                            n = delete_document(doc["doc_id"])
                            if "kb_docs" in st.session_state:
                                st.session_state.kb_docs = [
                                    d for d in st.session_state.kb_docs
                                    if d["doc_id"] != doc["doc_id"]
                                ]
                            st.success(f"Removed {n} chunks.")
                            st.rerun()
                    st.divider()

    # ═════════════════════════════════════════════════════════════
    # TAB 3 — DIRECT KB QUERY
    # ═════════════════════════════════════════════════════════════
    with tab_query:
        st.markdown("### Ask the knowledge base")
        st.caption(
            "Queries the KB directly with Claude — separate from the triage pipeline. "
            "Useful for looking up specific runbook steps or past incident resolutions."
        )

        if chunk_count() == 0:
            st.warning("Knowledge base is empty. Upload documents first.")
            return

        if "kb_chat" not in st.session_state:
            st.session_state.kb_chat = []

        # Starter prompts (shown only when chat is empty)
        if not st.session_state.kb_chat:
            st.markdown("**Try asking:**")
            starters = [
                "What causes PPPoE session failures on FTTP?",
                "Show me the rollback steps for VLAN reconfiguration",
                "What are the OLT VLAN mismatch troubleshooting steps?",
                "How was the NBN DHCP lease failure resolved?",
            ]
            starter_cols = st.columns(2)
            for i, s in enumerate(starters):
                if starter_cols[i % 2].button(s, key=f"starter_{i}"):
                    st.session_state.kb_chat.append({"role": "user", "content": s})
                    st.rerun()

        # Render conversation history
        for msg in st.session_state.kb_chat:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("sources"):
                    with st.expander(f"📎 {len(msg['sources'])} sources referenced"):
                        for src in msg["sources"]:
                            st.markdown(
                                f"**{src['source']}** · chunk #{src['chunk_idx']} "
                                f"· relevance {src['relevance_score']:.0%}"
                            )
                            st.code(
                                src["text"][:300] + ("…" if len(src["text"]) > 300 else "")
                            )

        # Free-text input
        question = st.chat_input("Ask anything about your runbooks and incidents…")
        if question:
            st.session_state.kb_chat.append({"role": "user", "content": question})

            with st.chat_message("user"):
                st.markdown(question)

            with st.chat_message("assistant"):
                with st.spinner("Searching knowledge base…"):
                    chunks  = search(question, top_k=5)
                    context = format_kb_context(chunks)

                import anthropic

                model  = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
                client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env

                system = f"""You are an expert Network Operations & Troubleshooting Assistant \
for NBN (National Broadband Network) infrastructure, 5G Core, O-RAN, and Kubernetes CNFs.

You have access to a curated knowledge base of runbooks, incident RCAs, and configuration guides.

Rules:
1. Answer using ONLY the knowledge base context below — do not guess or invent.
2. Cite the source document for every key claim.
3. Use numbered steps for procedures; bullet points for recommendations.
4. If the answer is not in the knowledge base, say so clearly.

KNOWLEDGE BASE CONTEXT:
{context if context else "No relevant documents found."}"""

                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.kb_chat[-8:]
                    if m["role"] in ("user", "assistant")
                ]

                response = client.messages.create(
                    model      = model,
                    max_tokens = 1200,
                    system     = system,
                    messages   = history,
                )
                answer = response.content[0].text

            st.markdown(answer)
            if chunks:
                with st.expander(f"📎 {len(chunks)} sources referenced"):
                    for src in chunks:
                        st.markdown(
                            f"**{src['source']}** · chunk #{src['chunk_idx']} "
                            f"· relevance {src['relevance_score']:.0%}"
                        )
                        st.code(
                            src["text"][:300] + ("…" if len(src["text"]) > 300 else "")
                        )

            st.session_state.kb_chat.append({
                "role":    "assistant",
                "content": answer,
                "sources": chunks,
            })
