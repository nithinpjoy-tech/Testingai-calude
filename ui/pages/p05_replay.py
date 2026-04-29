"""
p05_replay.py — Step-through replay of a past run. Feature #20.
Loads a saved RunReport from DB and replays each executor step with timing.
"""
from __future__ import annotations
import json
import time

import streamlit as st

import db.store as store


def render() -> None:
    st.markdown("## ▶️ Replay Mode")
    st.markdown(
        "<p style='color:#6B7885;'>Step through a past run for training or demo purposes. "
        "All steps are replayed from the saved execution log — no commands are re-executed.</p>",
        unsafe_allow_html=True,
    )

    store.init_db()
    history = store.list_runs(limit=50)
    executed = [r for r in history if r.status.value in ("executed", "reported")]

    if not executed:
        st.info("No completed runs with execution logs found. "
                "Run a full triage → remediation → execute cycle first.")
        return

    options = {
        f"{r.id[:8]}… · {r.test_case[:40]} ({r.verdict.value})": r.id
        for r in executed
    }
    labels = list(options.keys())

    selected = st.selectbox("Select a run to replay", labels)
    speed    = st.slider("Replay speed", 0.3, 3.0, 1.0, 0.1,
                         help="Seconds between steps")

    if not st.button("▶ Start Replay", type="primary"):
        return

    run_id  = options[selected]
    raw     = store.get_report_json(run_id)
    if not raw:
        st.error("Report data not found for this run.")
        return

    report = json.loads(raw)
    _replay(report, speed)


def _replay(report: dict, speed: float) -> None:
    tr     = report.get("test_run", {})
    triage = report.get("triage", {})
    exec_r = report.get("execution")

    # ── Summary ───────────────────────────────────────────────────────────────
    st.markdown("---")
    sev = triage.get("severity", "—")
    colours = {"CRITICAL":"#C0392B","HIGH":"#E67E22","MEDIUM":"#2471A3","LOW":"#1E8449"}
    col = colours.get(sev, "#6B7885")

    st.markdown(f"""
    <div class='tt-card tt-card-accent'>
      <b>{tr.get("test_case_name","—")}</b>
      &nbsp;·&nbsp; {tr.get("test_case_id","—")}
      <span style='float:right;color:{col};font-weight:700;'>{sev}</span>
    </div>""", unsafe_allow_html=True)

    st.markdown(f"**Root cause:** {triage.get('root_cause_summary','—')}")
    st.markdown("---")

    # ── Step replay ───────────────────────────────────────────────────────────
    if not exec_r or not exec_r.get("steps"):
        st.info("No execution steps recorded in this report.")
        return

    steps = exec_r["steps"]
    st.markdown(f"### Replaying {len(steps)} steps")
    progress = st.progress(0)
    total = len(steps)

    _STATUS_ICON = {
        "passed": "✅", "failed": "❌",
        "running": "🔄", "pending": "⚪", "skipped": "⏭",
    }

    for i, step in enumerate(steps, 1):
        status  = step.get("status", "pending")
        icon    = _STATUS_ICON.get(status, "⚪")
        bg      = "#EAFAF1" if status=="passed" else "#FDEDEC" if status=="failed" else "#FFF"
        border  = "#1E8449" if status=="passed" else "#C0392B" if status=="failed" else "#DDE1E7"

        with st.expander(
            f"{icon} Step {step.get('step_number', i)}: {step.get('description','—')}",
            expanded=True,
        ):
            st.code(step.get("command", ""), language="bash")
            out = step.get("actual_output") or step.get("stdout", "")
            if out:
                st.code(out, language="text")

        progress.progress(int(i / total * 100))
        time.sleep(speed)

    # Final verdict
    all_passed = all(s.get("status") == "passed" for s in steps)
    if all_passed:
        st.success("✅ Replay complete — all steps passed.")
    else:
        st.error("❌ Replay complete — one or more steps failed.")
