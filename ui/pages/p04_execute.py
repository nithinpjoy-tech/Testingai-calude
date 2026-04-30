"""
ui/pages/p04_execute.py  —  Execute page.

Live step-by-step execution view.
Removed: "simulated mode" label, token cost, "Claude" references.
"""

import streamlit as st
from ui.theme import stepper, topbar, sev_badge

WORKFLOW_STEPS = ["Ingest", "Triage", "Fix Script", "Approve", "Execute", "Report"]

STATUS_HTML = {
    "pass":    '<div class="tt-exec-status pass">✓</div>',
    "fail":    '<div class="tt-exec-status fail">✕</div>',
    "running": '<div class="tt-exec-status running">⟳</div>',
    "pending": '<div class="tt-exec-status pending">○</div>',
}


def _exec_row(idx: int, step, result=None) -> str:
    cmd  = getattr(step, "command", "")
    desc = getattr(step, "description", "")
    status = "pending"
    output = ""
    if result:
        result_status = getattr(result, "status", "")
        status_value = getattr(result_status, "value", str(result_status))
        status = "pass" if status_value == "passed" else "fail"
        output = getattr(result, "stdout", "") or ""

    out_html = (
        f'<div class="tt-code" style="border-radius:4px;margin-top:4px;padding:4px 8px">'
        f'{output[:300]}</div>'
    ) if output else ""

    return (
        f'<div class="tt-exec-row">'
        f'{STATUS_HTML[status]}'
        f'<div style="flex:1">'
        f'<div style="font-size:11px;font-weight:500;color:#1C2B3A">{desc}</div>'
        f'<div style="font-family:monospace;font-size:10px;color:#185FA5;'
        f'background:#EEF4FB;padding:2px 6px;border-radius:3px;'
        f'display:inline-block;margin-top:3px">{cmd}</div>'
        f'{out_html}'
        f'</div></div>'
    )


def render() -> None:
    run    = st.session_state.get("current_run")
    script = st.session_state.get("fix_script")
    results= st.session_state.get("exec_results", [])

    sev = getattr(run, "severity", "") if run else ""
    topbar("Execute", sev_badge(sev) if sev else "")
    stepper(WORKFLOW_STEPS, 4)

    if not script or not getattr(script, "approved_by", None):
        st.warning("Fix script must be approved before execution.")
        if st.button("← Back to Fix Script"):
            st.session_state.page = "p03"
            st.rerun()
        return

    steps = getattr(script, "steps", [])

    # ── Script overview ────────────────────────────────────────────────────
    mode = getattr(getattr(script, "execution_mode", None), "value", "simulated")
    st.markdown(
        f'<div class="tt-card">'
        f'<div class="tt-card-head">'
        f'<span class="tt-card-title">Execution plan</span>'
        f'<div style="display:flex;gap:6px">'
        f'<span class="tt-tag tt-tag-blue">{len(steps)} steps</span>'
        f'<span class="tt-tag tt-tag-green">{mode.title()}</span>'
        f'</div></div>'
        f'<div class="tt-card-body" style="padding:0">'
        + "".join(_exec_row(i, s, results[i] if i < len(results) else None)
                  for i, s in enumerate(steps))
        + "</div></div>",
        unsafe_allow_html=True,
    )

    # ── Execute button ─────────────────────────────────────────────────────
    if len(results) < len(steps):
        if st.button("▶  Run fix script", type="primary"):
            progress = st.progress(0)
            result_list = []
            try:
                from core.executor import execute, reset_simulated_ntd
                from core.models import StepStatus
                reset_simulated_ntd()
                for i, step_result in enumerate(execute(script)):
                    result_list.append(step_result)
                    st.session_state.exec_results = list(result_list)
                    progress.progress((i + 1) / len(steps))
                    if step_result.status == StepStatus.FAILED:
                        st.error(f"Step {i+1} failed — halted.")
                        break
                st.rerun()
            except Exception as exc:
                st.error(f"Execution error: {exc}")
    else:
        passed = sum(
            1 for r in results
            if getattr(getattr(r, "status", ""), "value", str(getattr(r, "status", ""))) == "passed"
        )
        if passed == len(steps):
            st.success(f"All {len(steps)} steps passed.")
            if st.button("View report →", type="primary"):
                st.session_state.page = "p05"
                st.rerun()
        else:
            st.error(f"{len(steps)-passed} step(s) failed.")
