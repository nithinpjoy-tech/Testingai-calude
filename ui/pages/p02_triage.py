"""
p02_triage.py — Triage page: test run summary, Claude analysis, root cause + recommendations.
Features: #4 severity, #5 root cause, #6 recommendations, #7 token usage.
"""
from __future__ import annotations
import json

import streamlit as st

from core.triage_engine import analyse
from core.models import Severity, Verdict
import db.store as store
from core.reporter import to_run_record
from db.store import upsert_run


# Severity display config
_SEV = {
    "CRITICAL": ("#C0392B", "#FADBD8", "🚨"),
    "HIGH":     ("#E67E22", "#FDEBD0", "⚠️"),
    "MEDIUM":   ("#2471A3", "#D6EAF8", "ℹ️"),
    "LOW":      ("#1E8449", "#D5F5E3", "✅"),
}


def render() -> None:
    run = st.session_state.get("current_run")
    if not run:
        st.warning("⬅️  Upload a test result file from the Dashboard first.")
        if st.button("Go to Dashboard"):
            st.session_state.active_page = "dashboard"
            st.rerun()
        return

    st.markdown("## 🧠 Triage Analysis")

    # ── Test run summary card ─────────────────────────────────────────────────
    vrd     = run.verdict.value
    vrd_col = "#C0392B" if vrd == "FAIL" else "#1E8449"
    st.markdown(f"""
    <div class='tt-card tt-card-accent'>
      <div style='display:flex;justify-content:space-between;align-items:flex-start;'>
        <div>
          <div style='font-size:1.05rem;font-weight:700;color:#1A3557;'>
            {run.test_case_name}
          </div>
          <div style='font-size:0.82rem;color:#6B7885;margin-top:3px;'>
            {run.test_case_id} &nbsp;·&nbsp; {run.dut.access_technology}
            &nbsp;·&nbsp; {run.timestamp.strftime('%Y-%m-%d %H:%M UTC')}
          </div>
        </div>
        <span class='badge badge-{"fail" if vrd=="FAIL" else "pass"}'
              style='font-size:0.9rem;padding:5px 14px;'>{vrd}</span>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── DUT + metrics ─────────────────────────────────────────────────────────
    with st.expander("📋 Device Under Test", expanded=False):
        c1, c2 = st.columns(2)
        c1.markdown(f"**Vendor:** {run.dut.vendor}")
        c1.markdown(f"**Model:** {run.dut.model}")
        c1.markdown(f"**Firmware:** {run.dut.firmware}")
        c2.markdown(f"**Device ID:** {run.dut.device_id}")
        c2.markdown(f"**Technology:** {run.dut.access_technology}")
        if run.dut.management_ip:
            c2.markdown(f"**Mgmt IP:** {run.dut.management_ip}")
        if run.topology_summary:
            st.markdown(f"**Topology:** `{run.topology_summary}`")

    with st.expander("📊 Test Metrics", expanded=False):
        if run.metrics:
            for m in run.metrics:
                icon  = "✅" if m.verdict == Verdict.PASS else "❌"
                tol   = f" ±{m.tolerance}" if m.tolerance else ""
                unit  = m.unit or ""
                st.markdown(
                    f"{icon} **{m.name}** — "
                    f"expected `{m.expected}{unit}`{tol} · "
                    f"measured `{m.measured}{unit}`"
                )
        else:
            st.info("No metric data in this test run.")

    with st.expander("📜 Error Logs", expanded=False):
        if run.error_logs:
            st.code("\n".join(run.error_logs), language="text")
        else:
            st.info("No log events captured.")

    if run.extra_context.get("config_snapshot"):
        with st.expander("⚙️ Config Snapshot", expanded=False):
            st.json(run.extra_context["config_snapshot"])

    st.markdown("---")

    # ── Triage action ─────────────────────────────────────────────────────────
    triage = st.session_state.get("triage_result")

    if not triage:
        st.markdown("### Run Claude Analysis")
        col_btn, col_info = st.columns([1, 3])
        if col_btn.button("🧠 Analyse with Claude", type="primary", use_container_width=True):
            with st.spinner("Sending to Claude — analysing failure context..."):
                try:
                    result = analyse(run)
                    st.session_state.triage_result = result
                    # Persist to DB
                    store.init_db()
                    from core.reporter import build_report
                    report = build_report(run, result)
                    rec = to_run_record(report)
                    upsert_run(rec)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Triage failed: {exc}")
        col_info.info(
            "Analyse the test failure, identify the root cause, "
            "and provide ranked recommendations."
        )
        return

    # ── Results ───────────────────────────────────────────────────────────────
    sev = triage.severity.value
    colour, bg, icon = _SEV.get(sev, ("#6B7885", "#F8F9FA", "ℹ️"))

    # Severity + confidence banner
    st.markdown(f"""
    <div style='background:{bg};border:1px solid {colour};border-radius:8px;
      padding:1rem 1.5rem;margin-bottom:1rem;'>
      <div style='display:flex;justify-content:space-between;align-items:center;'>
        <div style='font-size:1.1rem;font-weight:700;color:{colour};'>
          {icon}&nbsp; {sev} SEVERITY
        </div>
        <div style='font-size:0.88rem;color:#444;'>
          Confidence: <b style='color:{colour};'>{triage.confidence:.0%}</b>
          &nbsp;·&nbsp; Model: {triage.claude_model}
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    # Root cause
    st.markdown("### 🎯 Root Cause")
    st.markdown(f"""
    <div class='tt-card' style='border-left:4px solid {colour};'>
      <div style='font-size:1rem;font-weight:600;color:#1A3557;margin-bottom:0.5rem;'>
        {triage.root_cause_summary}
      </div>
      <div style='font-size:0.88rem;color:#333;line-height:1.6;white-space:pre-wrap;'>
        {triage.root_cause_detail}
      </div>
    </div>""", unsafe_allow_html=True)

    # Recommendations
    st.markdown("### 📋 Recommendations")
    for rec in triage.recommendations:
        effort_html = (
            f"<span style='float:right;font-size:0.75rem;color:#6B7885;'>"
            f"⏱ {rec.estimated_effort}</span>"
            if rec.estimated_effort else ""
        )
        st.markdown(f"""
        <div class='tt-card' style='margin-bottom:0.5rem;'>
          {effort_html}
          <div style='font-size:0.82rem;color:{colour};font-weight:700;margin-bottom:4px;'>
            PRIORITY {rec.priority}
          </div>
          <div style='font-weight:600;color:#1A3557;margin-bottom:4px;'>{rec.action}</div>
          <div style='font-size:0.85rem;color:#555;'>{rec.rationale}</div>
        </div>""", unsafe_allow_html=True)

    # Token usage
    with st.expander("🔢 Token usage"):
        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("Input tokens",  f"{triage.prompt_tokens:,}")
        tc2.metric("Output tokens", f"{triage.completion_tokens:,}")
        tc3.metric("Total tokens",  f"{triage.prompt_tokens + triage.completion_tokens:,}")

    st.markdown("---")

    # Navigate to remediation
    col1, col2 = st.columns([1, 3])
    if col1.button("🔧 Generate Fix Script →", type="primary", use_container_width=True):
        st.session_state.active_page = "remediation"
        st.rerun()
    if col2.button("🔄 Re-run analysis", use_container_width=True):
        st.session_state.triage_result = None
        st.rerun()
