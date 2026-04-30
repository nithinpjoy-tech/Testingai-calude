"""
ui/pages/p05_results.py  —  Results / Run Report page.
Run report page for execution results, history save, and JSON export.
"""

from datetime import datetime, timezone

import streamlit as st
from ui.theme import stepper, topbar, sev_badge, section_label

WORKFLOW_STEPS = ["Ingest", "Triage", "Fix Script", "Approve", "Execute", "Report"]


def render() -> None:
    run     = st.session_state.get("current_run")
    triage  = st.session_state.get("triage_result")
    script  = st.session_state.get("fix_script")
    results = st.session_state.get("exec_results", [])

    sev = getattr(run, "severity", "") if run else ""
    topbar("Results", sev_badge(sev) if sev else "")
    stepper(WORKFLOW_STEPS, 5)

    if not run or not triage:
        st.info("No completed run in session. Check History for past reports.")
        return
    object.__setattr__(
        triage,
        "root_cause",
        getattr(triage, "root_cause_summary", getattr(triage, "root_cause", "")),
    )

    steps = getattr(script, "steps", []) if script else []
    passed = sum(
        1 for r in results
        if getattr(getattr(r, "status", ""), "value", str(getattr(r, "status", ""))) == "passed"
    )
    total  = len(steps)
    outcome = "RESOLVED" if (total and passed == total) else ("PARTIAL" if passed else "FAILED")
    outcome_colour = {"RESOLVED": "#2E7D32", "PARTIAL": "#E65100", "FAILED": "#C62828"}[outcome]

    # ── Verdict banner ─────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:{outcome_colour}18;border:0.5px solid {outcome_colour}55;'
        f'border-radius:8px;padding:14px 18px;margin-bottom:14px;'
        f'display:flex;align-items:center;gap:12px">'
        f'<div style="font-size:22px;font-weight:500;color:{outcome_colour}">{outcome}</div>'
        f'<div style="font-size:12px;color:#3D4A56">'
        f'{passed}/{total} steps passed · '
        f'{getattr(run, "test_case_name", "")}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown(
            '<div class="tt-card"><div class="tt-card-head">'
            '<span class="tt-card-title">Root cause summary</span></div>'
            '<div class="tt-card-body">'
            f'<p style="font-size:12px;color:#3D4A56;line-height:1.7">'
            f'{getattr(triage, "root_cause", "—")}</p>'
            '</div></div>',
            unsafe_allow_html=True,
        )

    with col_r:
        st.markdown(
            '<div class="tt-card"><div class="tt-card-head">'
            '<span class="tt-card-title">Execution summary</span></div>'
            '<div class="tt-card-body">',
            unsafe_allow_html=True,
        )
        for i, step in enumerate(steps):
            res = results[i] if i < len(results) else None
            status = getattr(getattr(res, "status", ""), "value", str(getattr(res, "status", ""))) if res else ""
            ok = status == "passed" if res else None
            icon = "✓" if ok else ("✕" if ok is False else "○")
            colour = "#2E7D32" if ok else ("#C62828" if ok is False else "#9BA8B3")
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;'
                f'padding:4px 0;font-size:11px">'
                f'<span style="color:{colour};font-weight:500;width:14px">{icon}</span>'
                f'<span style="color:#3D4A56">{getattr(step,"description","")}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        st.markdown("</div></div>", unsafe_allow_html=True)

    # ── Save & export ──────────────────────────────────────────────────────
    st.divider()
    col_save, col_export, _ = st.columns([1, 1, 2])
    with col_save:
        if st.button("Save to history", type="primary"):
            try:
                from core.models import ExecutionResult, StepStatus
                from core.reporter import build_report, save, to_run_record
                from db.store import init_db, upsert_run

                execution_status = StepStatus.PASSED if total and passed == total else StepStatus.FAILED
                execution = ExecutionResult(
                    run_id=run.run_id,
                    fix_script_title=getattr(script, "title", ""),
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    overall_status=execution_status,
                    steps=getattr(script, "steps", []),
                    execution_mode=script.execution_mode,
                    operator=script.approved_by,
                ) if script else None
                report = build_report(run, triage, script, execution)
                save(report)
                init_db()
                upsert_run(to_run_record(report), report.model_dump_json())
                st.success("Saved.")
            except Exception as exc:
                st.error(str(exc))
    with col_export:
        if st.button("Export JSON"):
            try:
                import json
                data = {
                    "test": getattr(run, "test_case_name", ""),
                    "severity": getattr(run, "severity", ""),
                    "outcome": outcome,
                    "root_cause": getattr(triage, "root_cause_summary", ""),
                    "steps_passed": passed,
                    "steps_total": total,
                }
                st.download_button(
                    "⬇ Download",
                    data=json.dumps(data, indent=2),
                    file_name="triage_report.json",
                    mime="application/json",
                )
            except Exception as exc:
                st.error(str(exc))
