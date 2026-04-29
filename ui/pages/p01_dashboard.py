# New dashboard implementation (uploaded from downloads)

from __future__ import annotations
import json
import tempfile
from pathlib import Path

import streamlit as st

import db.store as store
from core.ingestor import ingest
from core.models import RunStatus, Verdict


def render() -> None:
    st.markdown("## 📊 Dashboard")

    # KPI row
    store.init_db()
    history = store.list_runs(limit=200)
    total = len(history)
    fails = sum(1 for r in history if r.verdict == Verdict.FAIL)
    triaged = sum(1 for r in history if r.status != RunStatus.INGESTED)
    pass_rt = f"{((total - fails) / total * 100):.0f}%" if total else "—"

    c1, c2, c3, c4 = st.columns(4)
    _kpi(c1, str(total), "Total Runs")
    _kpi(c2, str(fails), "Failures", colour="#C0392B" if fails else None)
    _kpi(c3, str(triaged), "Triaged")
    _kpi(c4, pass_rt, "Pass Rate", colour="#1E8449" if total else None)

    st.markdown("---")

    # Upload panel
    st.markdown("### Upload Test Result")
    st.markdown(
        "<p style='color:#6B7885;font-size:0.88rem;'>Drop a JSON, XML or LOG file exported from your test harness.</p>",
        unsafe_allow_html=True,
    )

    uploaded = st.file_uploader(
        "Select file", type=["json", "xml", "log", "txt"], label_visibility="collapsed"
    )

    if uploaded:
        col_info, col_btn = st.columns([3, 1])
        col_info.markdown(
            f"<div class='tt-card tt-card-accent'><b>{uploaded.name}</b><br><span style='color:#6B7885;font-size:0.82rem;'>{uploaded.size:,} bytes · {uploaded.type or 'unknown type'}</span></div>",
            unsafe_allow_html=True,
        )
        if col_btn.button("▶ Start Triage", type="primary", use_container_width=True):
            _load_and_navigate(uploaded)

    # Sample shortcuts
    st.markdown("#### Or load a sample")
    s1, s2, s3 = st.columns(3)
    if s1.button("📄 JSON sample", use_container_width=True):
        _load_sample("samples/pppoe_vlan_mismatch.json")
    if s2.button("📄 XML sample", use_container_width=True):
        _load_sample("samples/pppoe_vlan_mismatch.xml")
    if s3.button("📄 LOG sample", use_container_width=True):
        _load_sample("samples/pppoe_vlan_mismatch.log")

    # Run history
    st.markdown("---")
    st.markdown("### Recent Runs")

    if not history:
        st.info("No runs yet — upload a test result file to get started.")
        return

    _render_history_table(history[:20])

# Helpers

def _kpi(col, value: str, label: str, colour: str | None = None) -> None:
    c = colour or "#1A3557"
    col.markdown(
        f"<div class='kpi-card'><div class='kpi-value' style='color:{c}'>{value}</div><div class='kpi-label'>{label}</div></div>",
        unsafe_allow_html=True,
    )

def _load_sample(path: str) -> None:
    try:
        run = ingest(path)
        st.session_state.current_run = run
        st.session_state.triage_result = None
        st.session_state.fix_script = None
        st.session_state.exec_log = []
        st.session_state.exec_done = False
        st.session_state.approved = False
        st.session_state.active_page = "triage"
        st.rerun()
    except Exception as exc:
        st.error(f"Failed to load sample: {exc}")

def _load_and_navigate(uploaded) -> None:
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(uploaded.getvalue())
        tmp_path = tmp.name
    try:
        run = ingest(tmp_path)
        st.session_state.current_run = run
        st.session_state.triage_result = None
        st.session_state.fix_script = None
        st.session_state.exec_log = []
        st.session_state.exec_done = False
        st.session_state.approved = False
        st.session_state.active_page = "triage"
        st.rerun()
    except Exception as exc:
        st.error(f"Ingest failed: {exc}")

def _render_history_table(records) -> None:
    sev_badge = {
        "CRITICAL": "<span class='badge badge-crit'>CRITICAL</span>",
        "HIGH": "<span class='badge badge-high'>HIGH</span>",
        "MEDIUM": "<span class='badge badge-med'>MEDIUM</span>",
        "LOW": "<span class='badge badge-low'>LOW</span>",
    }
    verdict_badge = {
        "FAIL": "<span class='badge badge-fail'>FAIL</span>",
        "PASS": "<span class='badge badge-pass'>PASS</span>",
        "BLOCKED": "<span class='badge badge-high'>BLOCKED</span>",
        "INCONCLUSIVE": "<span class='badge badge-pending'>INCONCLUSIVE</span>",
    }
    rows_html = ""
    for r in records:
        sev_html = sev_badge.get(r.severity.value if r.severity else "", "—")
        vrd_html = verdict_badge.get(r.verdict.value, r.verdict.value)
        root = (r.root_cause or "—")[:70] + ("…" if r.root_cause and len(r.root_cause) > 70 else "")
        ts = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—"
        rows_html += f"""
<tr style='border-bottom:1px solid #EEE;'>
  <td style='padding:8px 6px;font-size:0.78rem;color:#6B7885;'>{ts}</td>
  <td style='padding:8px 6px;font-size:0.82rem;font-weight:500;'>{r.test_case[:40]}</td>
  <td style='padding:8px 6px;'>{vrd_html}</td>
  <td style='padding:8px 6px;'>{sev_html}</td>
  <td style='padding:8px 6px;font-size:0.78rem;color:#444;'>{root}</td>
</tr>"""
    st.markdown(
        f"""
<table style='width:100%;border-collapse:collapse;background:#FFF; border:1px solid #DDE1E7;border-radius:8px;overflow:hidden;'>
  <thead>
    <tr style='background:#F4F6F9;'>
      <th style='padding:10px 6px;text-align:left;font-size:0.78rem;color:#6B7885;'>TIMESTAMP</th>
      <th style='padding:10px 6px;text-align:left;font-size:0.78rem;color:#6B7885;'>TEST CASE</th>
      <th style='padding:10px 6px;text-align:left;font-size:0.78rem;color:#6B7885;'>VERDICT</th>
      <th style='padding:10px 6px;text-align:left;font-size:0.78rem;color:#6B7885;'>SEVERITY</th>
      <th style='padding:10px 6px;text-align:left;font-size:0.78rem;color:#6B7885;'>ROOT CAUSE</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
""",
        unsafe_allow_html=True,
    )
