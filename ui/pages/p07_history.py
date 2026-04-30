"""
ui/pages/p07_history.py  —  Run history page.
Run history page.
"""

import json

import streamlit as st
from ui.theme import topbar, sev_badge


def _load_report_into_session(run_id: str) -> None:
    from core.models import RunReport
    from db.store import get_report_json

    raw = get_report_json(run_id)
    if not raw:
        st.error("Full report data is not available for this run.")
        return

    report = RunReport.model_validate_json(raw)
    st.session_state.current_run = report.test_run
    st.session_state.triage_result = report.triage
    st.session_state.fix_script = report.fix_script
    st.session_state.exec_results = list(report.execution.steps) if report.execution else []
    st.session_state.detail_back_page = "history"
    st.session_state.page = "p08"
    st.rerun()


def _report_metric_map(report: dict) -> dict:
    return {
        metric.get("name", ""): metric
        for metric in report.get("test_run", {}).get("metrics", [])
        if metric.get("name")
    }


def _render_comparison(report_a: dict, report_b: dict) -> None:
    triage_a = report_a.get("triage", {})
    triage_b = report_b.get("triage", {})
    test_a = report_a.get("test_run", {})
    test_b = report_b.get("test_run", {})

    st.divider()
    st.markdown('<div class="tt-section-label">Comparison result</div>', unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Run A**")
        st.write(test_a.get("test_case_name", "—"))
        st.write(f"Severity: {triage_a.get('severity', '—')}")
        st.write(f"Confidence: {float(triage_a.get('confidence', 0)):.0%}")
        st.write(triage_a.get("root_cause_summary", "—"))
    with col_b:
        st.markdown("**Run B**")
        st.write(test_b.get("test_case_name", "—"))
        st.write(f"Severity: {triage_b.get('severity', '—')}")
        st.write(f"Confidence: {float(triage_b.get('confidence', 0)):.0%}")
        st.write(triage_b.get("root_cause_summary", "—"))

    metrics_a = _report_metric_map(report_a)
    metrics_b = _report_metric_map(report_b)
    names = sorted(set(metrics_a) | set(metrics_b))
    if not names:
        return

    rows = []
    for name in names:
        a_val = metrics_a.get(name, {}).get("measured", "—")
        b_val = metrics_b.get(name, {}).get("measured", "—")
        rows.append({
            "Metric": name,
            "Run A": a_val,
            "Run B": b_val,
            "Changed": "Yes" if a_val != b_val else "No",
        })
    st.dataframe(rows, hide_index=True, use_container_width=True)


def render() -> None:
    topbar("History")

    runs = []
    try:
        from db.store import list_runs
        runs = list_runs(limit=50)
    except Exception:
        pass

    # ── Filters ────────────────────────────────────────────────────────────
    col_search, col_sev, col_outcome = st.columns([3, 1, 1])
    with col_search:
        q = st.text_input("Search by test name or device", placeholder="Filter…", label_visibility="collapsed")
    with col_sev:
        sev_filter = st.selectbox("Severity", ["All", "CRITICAL", "HIGH", "MEDIUM", "LOW"], label_visibility="collapsed")
    with col_outcome:
        out_filter = st.selectbox("Outcome", ["All", "RESOLVED", "PARTIAL", "FAILED"], label_visibility="collapsed")

    # Apply filters
    if q:
        runs = [r for r in runs if q.lower() in str(r).lower()]
    if sev_filter != "All":
        runs = [
            r for r in runs
            if getattr(getattr(r, "severity", ""), "value", str(getattr(r, "severity", ""))).upper() == sev_filter
        ]
    if out_filter != "All":
        status_filter = {
            "RESOLVED": {"EXECUTED", "REPORTED"},
            "PARTIAL": {"APPROVED", "SCRIPTED"},
            "FAILED": {"INGESTED", "TRIAGED"},
        }.get(out_filter, {out_filter})
        runs = [
            r for r in runs
            if getattr(getattr(r, "status", ""), "value", str(getattr(r, "status", ""))).upper() in status_filter
        ]

    st.markdown(
        f'<div style="font-size:10px;color:#9BA8B3;font-family:monospace;'
        f'margin-bottom:10px">{len(runs)} records</div>',
        unsafe_allow_html=True,
    )

    if not runs:
        st.info("No run history found.")
        return

    # ── Table ──────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="tt-card"><div class="tt-card-body" style="padding:0">',
        unsafe_allow_html=True,
    )

    # Header
    st.markdown(
        '<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr 100px;'
        'gap:8px;padding:8px 14px;border-bottom:0.5px solid #E0E4EA;'
        'font-size:10px;font-weight:500;color:#9BA8B3;font-family:monospace;'
        'text-transform:uppercase;letter-spacing:.05em">'
        '<span>Test / Device</span><span>Severity</span>'
        '<span>Outcome</span><span>Date</span><span></span>'
        '</div>',
        unsafe_allow_html=True,
    )

    for run in runs:
        name     = getattr(run, "test_name", "—")
        device   = getattr(run, "source_file", "") or ""
        sev      = getattr(getattr(run, "severity", ""), "value", str(getattr(run, "severity", "")))
        outcome  = getattr(run, "outcome", "—")
        dt       = getattr(run, "created_at", "")
        run_id   = getattr(run, "id", "")
        name = getattr(run, "test_case", name)
        status_value = getattr(getattr(run, "status", ""), "value", str(getattr(run, "status", ""))).upper()
        outcome = (
            "RESOLVED" if status_value in {"EXECUTED", "REPORTED"}
            else "PARTIAL" if status_value in {"APPROVED", "SCRIPTED"}
            else "FAILED"
        )

        outcome_colour = {
            "RESOLVED": "#2E7D32", "PARTIAL": "#E65100", "FAILED": "#C62828",
        }.get(outcome.upper(), "#9BA8B3")

        row_cols = st.columns([2, 1, 1, 1, 0.7])
        with row_cols[0]:
            st.markdown(
                f'<div style="padding:6px 0"><div style="font-weight:500;color:#1C2B3A;'
                f'font-size:11px">{name}</div>'
                f'<div style="font-size:10px;color:#9BA8B3;font-family:monospace">{device}</div></div>',
                unsafe_allow_html=True,
            )
        with row_cols[1]:
            st.markdown(sev_badge(sev), unsafe_allow_html=True)
        with row_cols[2]:
            st.markdown(
                f'<span style="color:{outcome_colour};font-size:11px;font-weight:500">{outcome}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[3]:
            st.markdown(
                f'<span style="color:#9BA8B3;font-family:monospace;font-size:10px">{str(dt)[:10]}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[4]:
            if st.button("View", key=f"view_{run_id}", use_container_width=True):
                _load_report_into_session(run_id)

    st.markdown("</div></div>", unsafe_allow_html=True)

    # ── Compare button ─────────────────────────────────────────────────────
    st.divider()
    st.markdown(
        '<div class="tt-section-label">Compare two runs side by side</div>',
        unsafe_allow_html=True,
    )
    run_ids = [str(getattr(r, "id", "")) for r in runs]
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        id_a = st.selectbox("Run A", run_ids, label_visibility="collapsed")
    with col2:
        id_b = st.selectbox("Run B", run_ids, index=min(1, len(run_ids)-1), label_visibility="collapsed")
    with col3:
        if st.button("Compare", type="primary"):
            if id_a == id_b:
                st.warning("Select two different runs to compare.")
                return
            try:
                from db.store import get_report_json
                raw_a = get_report_json(id_a)
                raw_b = get_report_json(id_b)
                if not raw_a or not raw_b:
                    st.error("Full report data is not available for one or both selected runs.")
                    return
                _render_comparison(json.loads(raw_a), json.loads(raw_b))
            except Exception as exc:
                st.error(f"Comparison failed: {exc}")
