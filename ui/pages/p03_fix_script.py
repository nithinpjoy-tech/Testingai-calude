"""
ui/pages/p03_fix_script.py  —  Fix Script page.

Shows the AI-generated fix script, allows operator edit before approval.
Removed: "Claude" → AI, token cost, simulated-mode.
"""

from datetime import datetime, timezone

import streamlit as st
from ui.theme import stepper, topbar, sev_badge, section_label

WORKFLOW_STEPS = ["Ingest", "Triage", "Fix Script", "Approve", "Execute", "Report"]


def _script_viewer(script) -> None:
    steps = getattr(script, "steps", [])
    st.markdown(
        f'<div class="tt-card">'
        f'<div class="tt-card-head">'
        f'<span class="tt-card-title">Generated fix script</span>'
        f'<span class="tt-tag tt-tag-blue">{len(steps)} steps</span>'
        f'</div><div class="tt-card-body" style="padding:0">',
        unsafe_allow_html=True,
    )
    for i, step in enumerate(steps):
        cmd = getattr(step, "command", "")
        desc = getattr(step, "description", "")
        pre = getattr(step, "pre_check", "")
        rb = getattr(step, "rollback_command", "")
        st.markdown(
            f'<div class="tt-exec-row">'
            f'<div class="tt-exec-status pending">{i+1:02d}</div>'
            f'<div style="flex:1">'
            f'<div style="font-weight:500;font-size:11px;color:#1C2B3A">{desc}</div>'
            f'<div style="font-family:monospace;font-size:10px;color:#185FA5;'
            f'background:#EEF4FB;padding:3px 6px;border-radius:3px;margin-top:4px'
            f';display:inline-block">{cmd}</div>'
            + (f'<div style="font-size:10px;color:#9BA8B3;margin-top:3px">↩ Rollback: {rb}</div>' if rb else "")
            + f'</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div></div>", unsafe_allow_html=True)


def _approval_gate() -> bool:
    script = st.session_state.get("fix_script")
    if not script:
        return False
    already = getattr(script, "approved_by", None)
    if already:
        st.success(f"Approved by: {already}")
        return True

    st.markdown(
        '<div class="tt-approval-banner">'
        '<span style="font-size:14px">⚠</span>'
        '<span>Review the fix script above before approving. '
        'No commands will execute without sign-off.</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        operator = st.text_input("Your name", placeholder="Enter name to approve")
    with col2:
        st.caption("Uses script execution mode")
    with col3:
        st.markdown("<br/>", unsafe_allow_html=True)
        if st.button("✓ Approve & continue", type="primary"):
            if operator.strip():
                script.approved_by = operator.strip()
                script.approved_at = datetime.now(timezone.utc)
                st.session_state.fix_script = script
                st.session_state.page = "p04"
                st.rerun()
            else:
                st.warning("Enter your name to approve")
    return False


def render() -> None:
    run = st.session_state.get("current_run")
    triage = st.session_state.get("triage_result")
    script = st.session_state.get("fix_script")

    sev = getattr(run, "severity", "") if run else ""
    topbar("Fix Script", sev_badge(sev) if sev else "")
    stepper(WORKFLOW_STEPS, 2)

    if not triage:
        st.warning("Complete triage first.")
        if st.button("← Go to Triage"):
            st.session_state.page = "p02"
            st.rerun()
        return

    col_btn, _ = st.columns([1, 3])
    with col_btn:
        if st.button("Generate fix script" if not script else "Re-generate", type="primary"):
            with st.spinner("AI engine generating fix script…"):
                try:
                    from core.remediation import generate_fix_script
                    script = generate_fix_script(run, triage)
                    st.session_state.fix_script = script
                    st.session_state.exec_results = []
                except Exception as exc:
                    st.error(f"Generation failed: {exc}")
                    return

    if script:
        _script_viewer(script)
        st.divider()
        _approval_gate()
