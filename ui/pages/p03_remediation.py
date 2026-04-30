"""
p03_remediation.py — Fix script generation, approval gate, step-by-step execution.
Features: #8 script view, #9 approval gate, #10 step executor, #11 rollback indicator,
          #12 mid-triage Claude chat panel (right column).
"""
from __future__ import annotations
import time
from datetime import datetime, timezone

import streamlit as st

from core.remediation import generate_fix_script
from core.executor import execute, reset_simulated_ntd, StepResult
from core.models import ExecutionMode, StepStatus
from core.reporter import build_report, save, to_run_record
import db.store as store


_STATUS_STYLE = {
    "pending": ("⚪", "#6B7885", "#F8F9FA"),
    "running": ("🔄", "#E67E22", "#FEF9E7"),
    "passed":  ("✅", "#1E8449", "#EAFAF1"),
    "failed":  ("❌", "#C0392B", "#FDEDEC"),
    "skipped": ("⏭",  "#6B7885", "#F8F9FA"),
}


def render() -> None:
    run    = st.session_state.get("current_run")
    triage = st.session_state.get("triage_result")

    if not triage:
        st.warning("⬅️  Run triage analysis first.")
        if st.button("Go to Triage"):
            st.session_state.active_page = "triage"
            st.rerun()
        return

    # Two-column layout: execution steps on the left, Claude chat on the right
    left_col, right_col = st.columns([3, 2], gap="large")

    with left_col:
        _render_main(run, triage)

    with right_col:
        st.markdown("### Ask Claude")
        from ui.components.chat_sidebar import render_chat_panel
        render_chat_panel()


# ---------------------------------------------------------------------------
# Main remediation content (left column)
# ---------------------------------------------------------------------------

def _render_main(run, triage) -> None:
    st.markdown("## 🔧 Remediation")

    # ── Triage summary strip ──────────────────────────────────────────────────
    sev_colours = {
        "CRITICAL": "#C0392B", "HIGH": "#E67E22",
        "MEDIUM":   "#2471A3", "LOW":  "#1E8449",
    }
    sev = triage.severity.value
    col = sev_colours.get(sev, "#6B7885")
    st.markdown(f"""
    <div class='tt-card' style='border-left:4px solid {col};padding:0.8rem 1.2rem;'>
      <span style='color:{col};font-weight:700;'>{sev}</span>
      &nbsp;·&nbsp;
      <span style='font-size:0.9rem;'>{triage.root_cause_summary}</span>
      <span style='float:right;font-size:0.78rem;color:#6B7885;'>
        Confidence: {triage.confidence:.0%}
      </span>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Generate fix script ───────────────────────────────────────────────────
    script = st.session_state.get("fix_script")

    if not script:
        st.markdown("### Step 1 — Generate Fix Script")
        st.info(
            "Claude will generate a safe, idempotent fix script tailored to this device "
            "and firmware. Each step includes pre/post checks and a rollback command."
        )
        col_gen, col_mode = st.columns([1, 2])
        if col_gen.button("📋 Generate Fix Script", type="primary", use_container_width=True):
            with st.spinner("Claude is generating the fix script..."):
                try:
                    reset_simulated_ntd()
                    scr = generate_fix_script(run, triage)
                    st.session_state.fix_script = scr
                    st.session_state.approved   = False
                    st.session_state.exec_log   = []
                    st.session_state.exec_done  = False
                    st.rerun()
                except Exception as exc:
                    st.error(f"Script generation failed: {exc}")
        col_mode.markdown(
            "<div style='padding:0.5rem 0;font-size:0.85rem;color:#6B7885;'>"
            "🛡️ Execution mode: <b>SIMULATED</b> — commands run against a mock NTD."
            "</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Script display ────────────────────────────────────────────────────────
    st.markdown(f"### Step 2 — Review: `{script.title}`")

    # Global pre-checks
    if script.pre_checks:
        with st.expander(f"🔍 Pre-checks ({len(script.pre_checks)})", expanded=False):
            for i, chk in enumerate(script.pre_checks, 1):
                st.markdown(f"`{i}.` `{chk}`")

    # Step cards
    exec_log: list[dict] = st.session_state.get("exec_log", [])
    log_by_step = {r["step_number"]: r for r in exec_log}

    for step in script.steps:
        log = log_by_step.get(step.step_number)
        status_key = log["status"] if log else step.status.value
        icon, text_col, bg_col = _STATUS_STYLE.get(status_key, ("⚪", "#333", "#FFF"))

        with st.expander(
            f"{icon} Step {step.step_number}: {step.description}",
            expanded=(status_key in ("running", "failed")),
        ):
            st.markdown(f"**Command:**")
            st.code(step.command, language="bash")

            cols = st.columns(3)
            if step.pre_check:
                cols[0].markdown(f"**Pre-check:**\n`{step.pre_check}`")
            if step.expected_output:
                cols[1].markdown(f"**Expect in output:**\n`{step.expected_output}`")
            if step.post_check:
                cols[2].markdown(f"**Post-check:**\n`{step.post_check}`")

            if step.rollback_command:
                st.markdown(
                    f"<span style='font-size:0.8rem;color:#6B7885;'>"
                    f"↩ Rollback: <code>{step.rollback_command}</code></span>",
                    unsafe_allow_html=True,
                )

            if log:
                st.markdown("**Output:**")
                st.code(log.get("stdout", ""), language="text")
                if log.get("stderr"):
                    st.error(log["stderr"])
                if log.get("post_check_output"):
                    st.markdown("**Post-check output:**")
                    st.code(log["post_check_output"], language="text")

    # Global post-checks
    if script.post_checks:
        with st.expander(f"✅ Post-checks ({len(script.post_checks)})", expanded=False):
            for i, chk in enumerate(script.post_checks, 1):
                st.markdown(f"`{i}.` `{chk}`")

    st.markdown("---")

    # ── Approval gate ─────────────────────────────────────────────────────────
    approved  = st.session_state.get("approved", False)
    exec_done = st.session_state.get("exec_done", False)

    if exec_done:
        _render_execution_summary(exec_log)
        _render_post_actions(run, triage, script)
        return

    if not approved:
        st.markdown("### Step 3 — Approval Gate")
        st.warning(
            "⚠️ Review all steps carefully before approving. "
            "Once approved, steps will execute in sequence. "
            "Execution halts on first failure."
        )
        operator = st.text_input("Operator name / ID", placeholder="e.g. john.smith")
        col_approve, col_reject, col_regen = st.columns(3)

        if col_approve.button(
            "✅ Approve & Execute", type="primary",
            use_container_width=True,
            disabled=not operator,
        ):
            script.approved_by = operator
            script.approved_at = datetime.now(timezone.utc)
            st.session_state.approved = True
            st.rerun()

        if col_reject.button("❌ Reject Script", use_container_width=True):
            st.session_state.fix_script = None
            st.session_state.approved   = False
            st.rerun()

        if col_regen.button("🔄 Regenerate", use_container_width=True):
            st.session_state.fix_script = None
            st.rerun()

    else:
        # ── Execute steps ─────────────────────────────────────────────────────
        st.markdown("### Step 4 — Execution")
        st.success(f"✅ Approved by: **{script.approved_by}**")

        if not exec_log:
            if st.button("▶ Run Fix Script", type="primary"):
                _run_execution(script)
        else:
            st.info("Execution in progress...")


def _run_execution(script) -> None:
    """Stream execution step by step, updating the UI live."""
    log: list[dict] = []
    progress  = st.progress(0)
    status_box = st.empty()
    total      = len(script.steps)

    reset_simulated_ntd()

    for i, result in enumerate(execute(script), 1):
        log.append(result.to_dict())
        st.session_state.exec_log = log

        pct  = int(i / total * 100)
        progress.progress(pct)
        icon = "✅" if result.status == StepStatus.PASSED else "❌"
        status_box.markdown(
            f"**{icon} Step {result.step.step_number}/{total}:** {result.step.description}"
        )
        time.sleep(0.3)  # let the UI breathe between steps

        if result.status == StepStatus.FAILED:
            st.error(f"Step {result.step.step_number} failed — halting.")
            break

    st.session_state.exec_done = True
    progress.progress(100)
    st.rerun()


def _render_execution_summary(exec_log: list[dict]) -> None:
    passed = sum(1 for r in exec_log if r["status"] == "passed")
    failed = sum(1 for r in exec_log if r["status"] == "failed")
    total  = len(exec_log)

    if failed == 0:
        st.success(f"✅ All {total} steps passed successfully.")
    else:
        st.error(f"❌ {failed} of {total} steps failed ({passed} passed). Execution halted.")

    for r in exec_log:
        icon, col, _ = _STATUS_STYLE.get(r["status"], ("⚪", "#333", "#FFF"))
        with st.expander(f"{icon} Step {r['step_number']}: {r['description']} — {r['status'].upper()}"):
            st.code(r.get("stdout", ""), language="text")
            if r.get("stderr"):
                st.error(r["stderr"])


def _render_post_actions(run, triage, script) -> None:
    st.markdown("---")
    col1, col2, col3 = st.columns(3)

    if col1.button("📄 Save Report", use_container_width=True):
        from core.reporter import build_report, save
        report = build_report(run, triage, script)
        path   = save(report)
        store.init_db()
        store.upsert_run(to_run_record(report), report.model_dump_json())
        st.success(f"Report saved: {path}")

    if col2.button("🔄 New Analysis", use_container_width=True):
        for k in ["fix_script", "exec_log", "exec_done", "approved"]:
            st.session_state[k] = [] if k == "exec_log" else False if k in ("exec_done", "approved") else None
        st.rerun()

    if col3.button("⚖️ Compare Runs →", use_container_width=True):
        st.session_state.active_page = "comparison"
        st.rerun()
