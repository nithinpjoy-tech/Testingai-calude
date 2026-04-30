"""
ui/pages/p02_triage.py  —  Triage page.

Fixed:
  - "Load sample file" buttons restored (JSON / XML / LOG)
  - "Run AI Triage" is a large prominent CTA, labelled with the loaded filename
  - File-uploader state is persisted in session_state so sidebar navigation works
  - Navigation never locks — file content stored in session immediately on load
"""

import tempfile
import html as htmllib
from pathlib import Path

import streamlit as st
from ui.theme import stepper, topbar, sev_badge, cite_block

WORKFLOW_STEPS = ["Ingest", "Triage", "Fix Script", "Approve", "Execute", "Report"]
ALLOWED_TYPES  = ["json", "xml", "log", "txt", "csv"]

SAMPLES = {
    "📄 JSON sample": ("samples/pppoe_vlan_mismatch.json", "json"),
    "🗂 XML sample":  ("samples/pppoe_vlan_mismatch.xml",  "xml"),
    "📋 LOG sample":  ("samples/pppoe_vlan_mismatch.log",  "log"),
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _syntax_highlight(text: str, fmt: str) -> str:
    """Minimal syntax colouring for JSON/XML inside a tt-code block."""
    import re
    safe = htmllib.escape(text[:4000])
    if fmt == "json":
        safe = re.sub(r'"([^"]+)"(?=\s*:)', r'<span class="k">"\1"</span>', safe)
        safe = re.sub(r':\s*"([^"]*)"',     r': <span class="s">"\1"</span>', safe)
        safe = re.sub(r':\s*(\d+\.?\d*)',   r': <span class="n">\1</span>', safe)
        safe = re.sub(r'(CRITICAL|ERROR|FAIL)', r'<span class="e">\1</span>', safe)
    elif fmt in ("xml",):
        safe = re.sub(r'(&lt;/?[\w:]+)', r'<span class="k">\1</span>', safe)
    return f'<div class="tt-code">{safe}</div>'


def _ingest_file(content: bytes, filename: str) -> None:
    """Parse content bytes into TestRun and store in session_state."""
    from core.ingestor import ingest
    suffix = Path(filename).suffix or ".json"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    run = ingest(tmp_path)
    run.raw_input_path = filename
    st.session_state.current_run         = run
    st.session_state.raw_input_text      = content.decode("utf-8", errors="replace")
    st.session_state.raw_input_format    = run.raw_input_format
    st.session_state.triage_result       = None
    st.session_state.fix_script          = None
    st.session_state.exec_results        = []
    st.session_state._loaded_filename    = filename   # track what's loaded


# ── Upload / sample section ────────────────────────────────────────────────────

def _upload_section() -> None:
    st.markdown(
        '<div class="tt-card">'
        '<div class="tt-card-head">'
        '<span class="tt-card-title">Upload test result</span>'
        '<span class="tt-tag tt-tag-gray">JSON · XML · LOG · TXT · CSV</span>'
        '</div>'
        '<div class="tt-card-body">',
        unsafe_allow_html=True,
    )

    uploaded = st.file_uploader(
        "Drop file or click to browse",
        type=ALLOWED_TYPES,
        label_visibility="collapsed",
        key="triage_file_uploader",
    )

    if uploaded:
        # Only re-ingest when the filename changes (avoids loop on rerun)
        if st.session_state.get("_loaded_filename") != uploaded.name:
            try:
                _ingest_file(uploaded.read(), uploaded.name)
                st.success(f"✓ Loaded: **{uploaded.name}**")
            except Exception as exc:
                st.error(f"Could not parse file: {exc}")

    # ── Sample file loader ────────────────────────────────────────────────
    st.markdown(
        '<div style="margin-top:8px;font-size:11px;color:#9BA8B3;font-weight:500">'
        'OR LOAD A SAMPLE</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(len(SAMPLES))
    for col, (label, (path, fmt)) in zip(cols, SAMPLES.items()):
        with col:
            if st.button(label, key=f"sample_{fmt}", use_container_width=True):
                try:
                    file_path = Path(path)
                    if not file_path.exists():
                        # Try relative to project root
                        file_path = Path(__file__).parent.parent.parent / path
                    content = file_path.read_bytes()
                    _ingest_file(content, file_path.name)
                    st.success(f"✓ Loaded sample: **{file_path.name}**")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not load sample: {exc}")

    st.markdown("</div></div>", unsafe_allow_html=True)


# ── Run triage CTA ─────────────────────────────────────────────────────────────

def _run_triage_cta(run, result) -> None:
    """Prominent triage run button — shows the loaded filename as context."""
    filename = getattr(run, "raw_input_path", "") or getattr(run, "test_case_name", "loaded file")
    label    = (f"▶  Run AI Triage on  ‘{filename}’" if not result
              else f"↺  Re-run AI Triage on  ‘{filename}’")

    st.markdown(
        f'<div style="background:#E8F0FE;border:1.5px solid #185FA5;border-radius:8px;'
        f'padding:10px 14px;display:flex;align-items:center;gap:10px;margin:10px 0">'
        f'<span style="font-size:11px;color:#185FA5;font-weight:500">'
        f'File loaded — click button to analyse with AI</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    col_btn, col_hint = st.columns([2, 3])
    with col_btn:
        clicked = st.button(
            label,
            type="primary",
            key="run_triage_main",
            use_container_width=True,
        )
    with col_hint:
        st.caption("Sends the test result to Claude for root cause analysis.")

    if clicked:
        with st.spinner("AI engine analysing failure…"):
            try:
                from core.triage_engine import analyse
                triage_result = analyse(run)
                run.severity = triage_result.severity
                st.session_state.current_run   = run
                st.session_state.triage_result = triage_result
                st.session_state.fix_script    = None
                st.session_state.exec_results  = []
                # Auto-save to history so Dashboard and History page reflect this run
                try:
                    from db.store import init_db, upsert_run
                    from core.reporter import build_report, to_run_record
                    init_db()
                    report = build_report(run, triage_result)
                    upsert_run(to_run_record(report), report.model_dump_json())
                except Exception:
                    pass
                st.rerun()
            except Exception as exc:
                st.error(f"Triage failed: {exc}")


# ── Run summary card ───────────────────────────────────────────────────────────

def _run_summary_card(run) -> None:
    name       = getattr(run, "test_case_name", "—") or "—"
    test_id    = getattr(run, "test_case_id", "") or ""
    verdict    = getattr(getattr(run, "verdict", ""), "value", str(getattr(run, "verdict", "")))
    technology = getattr(getattr(run, "dut", None), "access_technology", "") or ""
    timestamp  = getattr(run, "timestamp", "")
    ts_str     = timestamp.strftime("%Y-%m-%d %H:%M UTC") if hasattr(timestamp, "strftime") else str(timestamp)[:16]

    vrd_colour = "#C0392B" if verdict == "FAIL" else "#1E8449"
    vrd_bg     = "#FADBD8" if verdict == "FAIL" else "#D5F5E3"
    meta       = " · ".join(filter(None, [test_id, technology, ts_str]))

    st.markdown(
        f'<div class="tt-card" style="border-left:4px solid {vrd_colour};margin-bottom:10px">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
        f'<div>'
        f'<div style="font-size:1.05rem;font-weight:700;color:#1A3557">{htmllib.escape(name)}</div>'
        f'<div style="font-size:0.82rem;color:#6B7885;margin-top:3px">{htmllib.escape(meta)}</div>'
        f'</div>'
        f'<span style="background:{vrd_bg};color:{vrd_colour};font-size:0.88rem;font-weight:700;'
        f'padding:4px 14px;border-radius:12px;letter-spacing:0.5px;white-space:nowrap">'
        f'{htmllib.escape(verdict)}</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


# ── Structured data sections ───────────────────────────────────────────────────

def _dut_section(run) -> None:
    dut = getattr(run, "dut", None)
    with st.expander("🖥  Device Under Test", expanded=True):
        if not dut:
            st.info("No device data available.")
            return
        vendor     = getattr(dut, "vendor", "—") or "—"
        model      = getattr(dut, "model", "—") or "—"
        firmware   = getattr(dut, "firmware", "—") or "—"
        device_id  = getattr(dut, "device_id", "—") or "—"
        technology = getattr(dut, "access_technology", "—") or "—"
        mgmt_ip    = getattr(dut, "management_ip", None)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Vendor:** {vendor}")
            st.markdown(f"**Model:** {model}")
            st.markdown(f"**Firmware:** {firmware}")
        with col2:
            st.markdown(f"**Device ID:** `{device_id}`")
            st.markdown(f"**Technology:** {technology}")
            if mgmt_ip:
                st.markdown(f"**Mgmt IP:** `{mgmt_ip}`")


def _metrics_section(run) -> None:
    metrics = getattr(run, "metrics", []) or []
    with st.expander("📊  Test Metrics", expanded=True):
        if not metrics:
            st.info("No metric data in this test run.")
            return
        rows = []
        for m in metrics:
            verdict_val = getattr(getattr(m, "verdict", ""), "value", str(getattr(m, "verdict", "—")))
            rows.append({
                "Metric":   getattr(m, "name", "—"),
                "Expected": str(getattr(m, "expected", "—")),
                "Measured": str(getattr(m, "measured", "—")),
                "Verdict":  verdict_val,
                "Unit":     getattr(m, "unit", "") or "—",
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)


def _error_logs_section(run) -> None:
    error_logs = getattr(run, "error_logs", []) or []
    with st.expander("📋  Error Logs", expanded=False):
        if not error_logs:
            st.info("No error logs in this test run.")
            return
        for log in error_logs:
            st.markdown(
                f'<div style="font-family:monospace;font-size:10px;color:#C62828;'
                f'background:#FFEBEE;border-radius:4px;padding:4px 8px;margin-bottom:4px">'
                f'{htmllib.escape(str(log))}</div>',
                unsafe_allow_html=True,
            )


def _config_snapshot_section(run) -> None:
    extra = getattr(run, "extra_context", {}) or {}
    snapshot = extra.get("config_snapshot") if isinstance(extra, dict) else None
    with st.expander("⚙️  Config Snapshot", expanded=True):
        if snapshot:
            st.json(snapshot)
        else:
            st.info("No config snapshot available.")


# ── KB context panel ───────────────────────────────────────────────────────────

def _kb_context_panel(run) -> None:
    chunks = []
    try:
        from core.kb_store import search, chunk_count
        if chunk_count() == 0:
            return
        query  = " ".join([getattr(run, "test_case_name", ""), *getattr(run, "error_logs", [])[:3]])
        chunks = search(query.strip(), top_k=3)
    except Exception:
        return

    if not chunks:
        return

    st.markdown(
        f'<div class="tt-card">'
        f'<div class="tt-card-head">'
        f'<span class="tt-card-title">KB context injected</span>'
        f'<span class="tt-tag tt-tag-purple">{len(chunks)} chunks — auto</span>'
        f'</div><div class="tt-card-body" style="padding:0">',
        unsafe_allow_html=True,
    )
    for c in chunks:
        st.markdown(cite_block(c["source"], c["relevance_score"], c["text"]), unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)


# ── Diagnosis card ─────────────────────────────────────────────────────────────

def _diagnosis_card(result) -> None:
    root_cause = getattr(result, "root_cause_summary", getattr(result, "root_cause", "—"))
    confidence = getattr(result, "confidence", 0.0)
    recs       = getattr(result, "recommendations", [])
    recs_text  = [f"{rec.action} — {rec.rationale}" for rec in recs]
    conf_pct   = int(confidence * 100)
    conf_colour = "#2E7D32" if conf_pct >= 70 else ("#E65100" if conf_pct >= 40 else "#C62828")

    steps_html = "".join(
        f'<div style="display:flex;align-items:flex-start;gap:6px;margin-bottom:5px">'
        f'<span class="tt-step-num">{i+1}</span>'
        f'<span class="tt-diagnosis-fix">{r}</span></div>'
        for i, r in enumerate(recs_text)
    ) or '<span style="color:#9BA8B3;font-size:11px">No steps generated</span>'

    st.markdown(
        f'<div class="tt-card">'
        f'<div class="tt-card-head">'
        f'<span class="tt-card-title">AI diagnosis</span>'
        f'<div style="display:flex;align-items:center;gap:8px">'
        f'<span class="tt-tag tt-tag-green">Confidence {conf_pct}%</span>'
        f'</div></div>'
        f'<div class="tt-card-body">'
        f'<div class="tt-conf"><div class="tt-conf-fill" '
        f'style="width:{conf_pct}%;background:{conf_colour}"></div></div>'
        f'<div style="height:10px"></div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">'
        f'<div>'
        f'<div class="tt-section-label">Root cause</div>'
        f'<div class="tt-diagnosis-root">{root_cause}</div>'
        f'</div>'
        f'<div>'
        f'<div class="tt-section-label">Recommended steps</div>'
        f'{steps_html}'
        f'</div>'
        f'</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def render() -> None:
    run    = st.session_state.get("current_run")
    result = st.session_state.get("triage_result")
    sev    = getattr(run, "severity", "") if run else ""

    topbar("Triage", sev_badge(sev) if sev else "")
    stepper(WORKFLOW_STEPS, 1 if run else 0)

    # ── Upload + sample loader ─────────────────────────────────────────────
    _upload_section()

    # Refresh after upload section (uploader may have updated session_state)
    run    = st.session_state.get("current_run")
    result = st.session_state.get("triage_result")

    if not run:
        st.markdown(
            '<div style="text-align:center;padding:40px 0;color:#9BA8B3;font-size:12px">'
            'Upload a test result file above, or click a sample button to begin'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Run summary card (test name + PASS/FAIL verdict) ─────────────────
    _run_summary_card(run)

    # ── Run triage CTA (visible once file is loaded) ───────────────────────
    _run_triage_cta(run, result)

    # ── Structured data sections + KB context panel ───────────────────────
    _dut_section(run)
    _metrics_section(run)
    _error_logs_section(run)
    _config_snapshot_section(run)
    _kb_context_panel(run)

    st.divider()

    # ── Diagnosis result ───────────────────────────────────────────────────
    if result:
        _diagnosis_card(result)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("Generate fix script →", type="primary", key="goto_fix_script"):
            st.session_state.page = "p03"
            st.rerun()
