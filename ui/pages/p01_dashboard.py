"""
ui/pages/p01_dashboard.py  —  Dashboard page.

Displays: workflow stepper, KPI cards, recent runs, failure categories, KB summary.

Redesigned dashboard for workflow status, KPIs, recent runs, and KB summary.
"""

import html as _html

import streamlit as st
from ui.theme import (
    inject_theme, stepper, topbar, sev_badge, kpi_card,
    section_label, tag,
)

WORKFLOW_STEPS = ["Ingest", "Triage", "Fix Script", "Approve", "Execute", "Report"]


def _kpi_row(stats: dict) -> None:
    html = '<div class="tt-kpi-row" style="grid-template-columns:repeat(3,1fr)">'
    html += kpi_card("Runs today",       str(stats.get("runs_today", 0)),
                     f"+{stats.get('runs_delta', 0)} vs yesterday", "up", "#E8612C")
    html += kpi_card("Auto-resolved",    str(stats.get("resolved", 0)),
                     f"{stats.get('resolve_rate', 0):.0f}% rate", "up", "#2E7D32")
    html += kpi_card("Pending approval", str(stats.get("pending", 0)),
                     "Needs action" if stats.get("pending", 0) else "All clear",
                     "down" if stats.get("pending", 0) else "up", "#E65100")
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _load_run_detail(run_id: str) -> None:
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
    st.session_state.detail_back_page = "p01"
    st.session_state.page = "p08"
    st.rerun()


def _recent_runs(runs: list) -> None:
    st.markdown('<div class="tt-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="tt-card-head">'
        '<span class="tt-card-title">Recent triage runs</span>'
        f'<span class="tt-tag tt-tag-blue">{len(runs)} today</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="tt-card-body" style="padding:0 14px">', unsafe_allow_html=True)

    if not runs:
        st.markdown(
            '<div style="padding:20px 0;text-align:center;font-size:12px;'
            'color:#9BA8B3">No runs yet — upload a test result to begin</div>',
            unsafe_allow_html=True,
        )
    else:
        for run in runs[:6]:
            run_id = run.get("run_id", "")
            dot_cls = "pass" if run.get("status") == "resolved" else (
                "fail" if run.get("status") == "failed" else "pending"
            )
            row = st.columns([0.04, 1, 0.38, 0.2, 0.18])
            with row[0]:
                st.markdown(
                    f'<div style="padding-top:9px">'
                    f'<span class="tt-run-dot {dot_cls}"></span></div>',
                    unsafe_allow_html=True,
                )
            with row[1]:
                st.markdown(
                    f'<div style="padding:6px 0;font-size:11px;font-weight:500;'
                    f'color:#1C2B3A;white-space:nowrap;overflow:hidden;'
                    f'text-overflow:ellipsis" title="{_html.escape(run.get("name",""))}">'
                    f'{_html.escape(run.get("name","—"))}</div>',
                    unsafe_allow_html=True,
                )
            with row[2]:
                st.markdown(
                    f'<div style="padding:4px 0">{sev_badge(run.get("severity",""))}</div>',
                    unsafe_allow_html=True,
                )
            with row[3]:
                st.markdown(
                    f'<div style="padding:6px 0;font-size:10px;font-family:monospace;'
                    f'color:#9BA8B3">{run.get("time","")}</div>',
                    unsafe_allow_html=True,
                )
            with row[4]:
                if run_id and st.button("View", key=f"dash_run_{run_id}", use_container_width=True):
                    _load_run_detail(run_id)

    st.markdown("</div></div>", unsafe_allow_html=True)


def _failure_chart(categories: list) -> None:
    """Pure-CSS horizontal bar chart — no Plotly dependency."""
    colours = ["#E8612C", "#0F2744", "#185FA5", "#2E7D32", "#9BA8B3"]
    st.markdown('<div class="tt-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="tt-card-head">'
        '<span class="tt-card-title">Top failure categories</span>'
        '<span class="tt-tag tt-tag-purple">30 days</span>'
        '</div>'
        '<div class="tt-card-body">',
        unsafe_allow_html=True,
    )

    html_parts = []
    for i, cat in enumerate(categories[:5]):
        colour = colours[i % len(colours)]
        pct = cat.get("pct", 0)
        html_parts.append(
            f'<div style="margin-bottom:10px">'
            f'<div style="display:flex;justify-content:space-between;'
            f'font-size:10px;margin-bottom:3px">'
            f'<span style="color:#3D4A56">{cat["label"]}</span>'
            f'<span style="font-family:monospace;color:#9BA8B3">{pct}%</span></div>'
            f'<div class="tt-bar-track">'
            f'<div class="tt-bar-fill" style="width:{pct}%;background:{colour}"></div>'
            f'</div></div>'
        )
    st.markdown("".join(html_parts) + "</div></div>", unsafe_allow_html=True)


def _kb_summary(doc_count: int, chunk_count: int, doc_types: list) -> None:
    type_tags = "".join(
        f'<div style="background:#F5F7FA;border:0.5px solid #E0E4EA;border-radius:6px;'
        f'padding:8px 10px">'
        f'<div style="font-size:10px;font-weight:500;font-family:monospace;'
        f'color:{d["color"]};margin-bottom:2px">{d["ext"]}</div>'
        f'<div style="font-size:12px;font-weight:500">{d["count"]} files</div>'
        f'<div style="font-size:10px;color:#9BA8B3">{d["label"]}</div>'
        f'</div>'
        for d in doc_types
    )
    st.markdown(
        f'<div class="tt-card">'
        f'<div class="tt-card-head">'
        f'<span class="tt-card-title">Knowledge base</span>'
        f'<span class="tt-tag tt-tag-green">{doc_count} docs · {chunk_count:,} chunks</span>'
        f'</div>'
        f'<div class="tt-card-body">'
        f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">'
        f'{type_tags}'
        f'<div style="background:#E8F5E9;border:0.5px solid #C8E6C9;border-radius:6px;'
        f'padding:8px 10px">'
        f'<div style="font-size:10px;font-weight:500;color:#1B5E20;margin-bottom:2px">Auto-enriched</div>'
        f'<div style="font-size:12px;font-weight:500;color:#1B5E20">Active</div>'
        f'<div style="font-size:10px;color:#2E7D32">Injected in triage</div>'
        f'</div>'
        f'</div></div></div>',
        unsafe_allow_html=True,
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def render() -> None:
    topbar("Dashboard")

    # Determine current pipeline step from session state
    current_step = 0
    if st.session_state.get("current_run"):
        current_step = 1
    if st.session_state.get("triage_result"):
        current_step = 2
    if st.session_state.get("fix_script"):
        current_step = 3

    stepper(WORKFLOW_STEPS, current_step)

    # ── Load stats ─────────────────────────────────────────────────────────
    stats = {"runs_today": 0, "runs_delta": 0, "resolved": 0, "resolve_rate": 0,
             "pending": 0, "runs_week": 0, "avg_daily": 0}
    runs = []
    categories = []
    doc_count, chunk_count = 0, 0
    doc_types = [
        {"ext": ".pdf",  "count": 0, "label": "Runbooks",  "color": "#A32D2D"},
        {"ext": ".docx", "count": 0, "label": "SOPs",      "color": "#185FA5"},
        {"ext": ".md",   "count": 0, "label": "RCA logs",  "color": "#3B6D11"},
    ]

    try:
        from db.store import get_dashboard_stats, get_recent_runs, get_failure_categories
        stats = get_dashboard_stats()
        runs = get_recent_runs(limit=6)
        categories = get_failure_categories(days=30)
    except Exception:
        pass

    try:
        from core.kb_store import chunk_count as kbc, list_unique_documents
        chunk_count = kbc()
        doc_count = len(list_unique_documents())
    except Exception:
        pass

    # ── KPI row ────────────────────────────────────────────────────────────
    _kpi_row(stats)

    # ── Two-column layout ──────────────────────────────────────────────────
    col_left, col_right = st.columns([1.4, 1])
    with col_left:
        _recent_runs(runs)
    with col_right:
        if not categories:
            categories = [
                {"label": "VLAN mismatch",    "pct": 38},
                {"label": "Auth failure",     "pct": 24},
                {"label": "DHCP drift",       "pct": 18},
                {"label": "Interface timeout","pct": 12},
                {"label": "Other",            "pct": 8},
            ]
        _failure_chart(categories)

    # ── KB summary ─────────────────────────────────────────────────────────
    _kb_summary(doc_count, chunk_count, doc_types)

    # ── Quick-start CTA (shown only when no runs yet) ──────────────────────
    if not runs:
        st.markdown(
            '<div style="background:#fff;border:0.5px solid #E0E4EA;border-radius:8px;'
            'padding:20px;text-align:center;margin-top:8px">'
            '<div style="font-size:13px;font-weight:500;margin-bottom:6px">'
            'Start your first triage</div>'
            '<div style="font-size:12px;color:#9BA8B3;margin-bottom:12px">'
            'Upload a test result file (JSON, XML, or log) to begin</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button("Go to Triage →", type="primary"):
            st.session_state.page = "p02"
            st.rerun()
