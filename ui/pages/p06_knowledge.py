"""
ui/pages/p06_knowledge.py  —  Knowledge Base page.

Upload / Library / Query tabs.
Knowledge base upload, library, and query page.
"""

import uuid
import streamlit as st
from ui.theme import topbar, section_label, cite_block, tag

ALLOWED = ["pdf", "docx", "txt", "md", "log", "csv", "json"]

FILE_META = {
    "pdf":  ("#A32D2D", "Runbooks / reports"),
    "docx": ("#185FA5", "Word documents"),
    "md":   ("#3B6D11", "Wiki / RCA logs"),
    "txt":  ("#533AB7", "Raw logs"),
    "log":  ("#BA7517", "Device logs"),
    "json": ("#BA7517", "Config dumps"),
    "csv":  ("#5F5E5A", "Issue exports"),
}


def render() -> None:
    topbar("Knowledge Base")

    # Stats bar
    total_chunks = 0
    docs = []
    try:
        from core.kb_store import chunk_count, list_unique_documents
        total_chunks = chunk_count()
        docs = list_unique_documents()
    except Exception:
        pass

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Documents", len(docs))
    col_b.metric("Indexed chunks", f"{total_chunks:,}")
    col_c.metric("Status", "Active ✓" if total_chunks > 0 else "Empty")

    st.markdown('<hr style="margin:10px 0 16px"/>', unsafe_allow_html=True)

    tab_up, tab_lib, tab_query = st.tabs(["📤  Upload", "📂  Library", "💬  Query"])

    # ── UPLOAD ────────────────────────────────────────────────────────────
    with tab_up:
        st.markdown(
            f'<div class="tt-section-label">Supported: '
            + "  ·  ".join(f".{e}" for e in ALLOWED)
            + "</div>",
            unsafe_allow_html=True,
        )
        files = st.file_uploader(
            "Drop files or click to browse",
            type=ALLOWED,
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if files and st.button("📥  Ingest", type="primary"):
            prog = st.progress(0)
            for i, f in enumerate(files):
                prog.progress(i / len(files), text=f"Processing {f.name}…")
                try:
                    from core.kb_ingest import extract_text, chunk_text
                    from core.kb_store import upsert_chunks
                    content = f.read()
                    text = extract_text(content, f.name)
                    doc_id = str(uuid.uuid4())
                    chunks = chunk_text(text, doc_id, f.name)
                    upsert_chunks(chunks)
                    if "kb_docs" not in st.session_state:
                        st.session_state.kb_docs = []
                    st.session_state.kb_docs.append({
                        "doc_id": doc_id, "filename": f.name,
                        "size_kb": round(len(content)/1024, 1), "chunks": len(chunks),
                    })
                    st.success(f"✓ {f.name} — {len(chunks)} chunks")
                except Exception as e:
                    st.error(f"✕ {f.name}: {e}")
            prog.progress(1.0)
            st.rerun()

        # Type reference grid
        st.markdown('<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:12px">', unsafe_allow_html=True)
        for ext, (colour, label) in FILE_META.items():
            st.markdown(
                f'<div style="background:#fff;border:0.5px solid #E0E4EA;border-radius:6px;padding:7px 9px">'
                f'<div style="font-family:monospace;font-size:10px;font-weight:500;color:{colour}">.{ext}</div>'
                f'<div style="font-size:9px;color:#9BA8B3;margin-top:1px">{label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    # ── LIBRARY ───────────────────────────────────────────────────────────
    with tab_lib:
        if not docs:
            st.info("No documents yet. Upload files in the Upload tab.")
        else:
            session_map = {d["doc_id"]: d for d in st.session_state.get("kb_docs", [])}
            for doc in docs:
                ext = doc["source"].rsplit(".", 1)[-1].lower() if "." in doc["source"] else "?"
                colour, _ = FILE_META.get(ext, ("#888", ""))
                meta = session_map.get(doc["doc_id"], {})
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.markdown(
                        f'<div style="background:#fff;border:0.5px solid #E0E4EA;'
                        f'border-radius:6px;padding:8px 10px;margin-bottom:4px">'
                        f'<div style="display:flex;align-items:center;gap:6px">'
                        f'<span style="background:{colour}22;color:{colour};'
                        f'font-size:9px;font-weight:500;font-family:monospace;'
                        f'padding:1px 5px;border-radius:3px">.{ext}</span>'
                        f'<span style="font-size:11px;font-weight:500;color:#1C2B3A">{doc["source"]}</span>'
                        f'</div>'
                        f'<div style="font-size:10px;color:#9BA8B3;font-family:monospace;margin-top:3px">'
                        + (f'{meta.get("chunks","?")} chunks · {meta.get("size_kb","?")}KB · ' if meta else "")
                        + '✓ indexed</div></div>',
                        unsafe_allow_html=True,
                    )
                with col2:
                    if st.button("🗑", key=f"del_{doc['doc_id']}"):
                        try:
                            from core.kb_store import delete_document
                            delete_document(doc["doc_id"])
                            if "kb_docs" in st.session_state:
                                st.session_state.kb_docs = [
                                    d for d in st.session_state.kb_docs
                                    if d["doc_id"] != doc["doc_id"]
                                ]
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

    # ── QUERY ─────────────────────────────────────────────────────────────
    with tab_query:
        if total_chunks == 0:
            st.warning("Knowledge base is empty. Upload documents first.")
            return

        if "kb_chat" not in st.session_state:
            st.session_state.kb_chat = []

        # Starter prompts
        if not st.session_state.kb_chat:
            st.markdown("**Try asking:**")
            starters = [
                "What causes PPPoE PADI frames to be silently dropped?",
                "Show rollback steps for VLAN misconfiguration on NTD",
                "How to diagnose GPON signal loss on ONT?",
                "How was an N2 interface timeout resolved?",
            ]
            cols = st.columns(2)
            for i, s in enumerate(starters):
                if cols[i % 2].button(s, key=f"start_{i}"):
                    st.session_state.kb_chat.append({"role": "user", "content": s})
                    st.rerun()

        # Chat history
        for msg in st.session_state.kb_chat:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("sources"):
                    with st.expander(f"📎 {len(msg['sources'])} sources"):
                        for src in msg["sources"]:
                            st.markdown(
                                cite_block(src["source"], src["relevance_score"], src["text"]),
                                unsafe_allow_html=True,
                            )

        # Input
        question = st.chat_input("Ask anything about your runbooks and incidents…")
        if question:
            st.session_state.kb_chat.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.spinner("Searching knowledge base…"):
                    try:
                        from core.kb_store import search, format_kb_context
                        from core.config import get_config
                        import anthropic
                        cfg = get_config()
                        chunks = search(question, top_k=5)
                        ctx = format_kb_context(chunks)
                        claude_cfg = cfg.get("claude", {})
                        api_key = claude_cfg.get("api_key") or None
                        model = claude_cfg.get("model", "claude-sonnet-4-20250514")
                        client = anthropic.Anthropic(api_key=api_key)
                        system = (
                            "You are an expert NBN (National Broadband Network) network operations "
                            "and troubleshooting assistant with deep knowledge of FTTP, FTTN, HFC, "
                            "Fixed Wireless, PPPoE, IPoE, BNG, and access network infrastructure.\n\n"
                            "Rules:\n"
                            "1. Answer using ONLY the knowledge base context below — do not guess or invent.\n"
                            "2. Cite the source document for every key claim.\n"
                            "3. Use numbered steps for procedures; bullet points for recommendations.\n"
                            "4. Use access-network terminology (NTD not modem, OLT not switch, S-VLAN not outer VLAN).\n"
                            "5. If the answer is not in the knowledge base, say so clearly.\n\n"
                            "KNOWLEDGE BASE:\n" + (ctx or "No relevant documents found.")
                        )
                        history = [
                            {"role": m["role"], "content": m["content"]}
                            for m in st.session_state.kb_chat[-8:]
                            if m["role"] in ("user", "assistant")
                        ]
                        resp = client.messages.create(
                            model=model,
                            max_tokens=1200,
                            system=system,
                            messages=history,
                        )
                        answer = resp.content[0].text
                        st.markdown(answer)
                        if chunks:
                            with st.expander(f"📎 {len(chunks)} sources"):
                                for c in chunks:
                                    st.markdown(
                                        cite_block(c["source"], c["relevance_score"], c["text"]),
                                        unsafe_allow_html=True,
                                    )
                        st.session_state.kb_chat.append({
                            "role": "assistant", "content": answer, "sources": chunks,
                        })
                    except Exception as exc:
                        st.error(f"Query failed: {exc}")
