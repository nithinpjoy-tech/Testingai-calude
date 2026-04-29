"""
p04_comparison.py — Diff two runs side-by-side. Feature #16.
"""
from __future__ import annotations
import json

import streamlit as st

import db.store as store
from core.models import Severity, Verdict


def render() -> None:
    st.markdown("## ⚖️ Compare Runs")
    st.markdown(
        "<p style='color:#6B7885;'>Select two run IDs to diff metrics, "
        "severity, root cause, and recommendations side by side.</p>",
        unsafe_allow_html=True,
    )

    store.init_db()
    history = store.list_runs(limit=50)

    if len(history) < 2:
        st.info("Need at least 2 completed runs to compare. Run a triage first.")
        return

    # Build option list: "ID — test case name (verdict)"
    options = {
        f"{r.id[:8]}… · {r.test_case[:35]} ({r.verdict.value})": r.id
        for r in history
    }
    labels = list(options.keys())

    col1, col2 = st.columns(2)
    sel_a = col1.selectbox("Run A", labels, index=0, key="cmp_a")
    sel_b = col2.selectbox("Run B", labels, index=min(1, len(labels) - 1), key="cmp_b")

    if options[sel_a] == options[sel_b]:
        st.warning("Select two different runs to compare.")
        return

    if not st.button("⚖️ Compare", type="primary"):
        return

    id_a, id_b = options[sel_a], options[sel_b]
    json_a = store.get_report_json(id_a)
    json_b = store.get_report_json(id_b)

    if not json_a or not json_b:
        st.error("Full report data not available for one or both runs. "
                 "Re-run triage and save the report first.")
        return

    rep_a = json.loads(json_a)
    rep_b = json.loads(json_b)

    st.markdown("---")
    _render_comparison(rep_a, rep_b)


def _render_comparison(a: dict, b: dict) -> None:
    ca, cb = st.columns(2)

    # ── Header ────────────────────────────────────────────────────────────────
    _col_header(ca, a)
    _col_header(cb, b)

    st.markdown("---")

    # ── Severity ──────────────────────────────────────────────────────────────
    st.markdown("#### Severity & Confidence")
    c1, c2 = st.columns(2)
    _sev_card(c1, a.get("triage", {}))
    _sev_card(c2, b.get("triage", {}))

    st.markdown("---")

    # ── Root cause ────────────────────────────────────────────────────────────
    st.markdown("#### Root Cause")
    c1, c2 = st.columns(2)
    ta, tb = a.get("triage", {}), b.get("triage", {})
    c1.markdown(f"**{ta.get('root_cause_summary','—')}**")
    c1.markdown(f"<div style='font-size:0.82rem;color:#555;'>{ta.get('root_cause_detail','')[:300]}…</div>",
                unsafe_allow_html=True)
    c2.markdown(f"**{tb.get('root_cause_summary','—')}**")
    c2.markdown(f"<div style='font-size:0.82rem;color:#555;'>{tb.get('root_cause_detail','')[:300]}…</div>",
                unsafe_allow_html=True)

    st.markdown("---")

    # ── Metrics diff ──────────────────────────────────────────────────────────
    st.markdown("#### Metrics Comparison")
    metrics_a = {m["name"]: m for m in a.get("test_run", {}).get("metrics", [])}
    metrics_b = {m["name"]: m for m in b.get("test_run", {}).get("metrics", [])}
    all_names = sorted(set(metrics_a) | set(metrics_b))

    if all_names:
        rows = ""
        for name in all_names:
            ma = metrics_a.get(name, {})
            mb = metrics_b.get(name, {})
            _va = f"{ma.get('measured','—')} ({ma.get('verdict','—')})" if ma else "—"
            _vb = f"{mb.get('measured','—')} ({mb.get('verdict','—')})" if mb else "—"
            changed = ma.get("measured") != mb.get("measured") and ma and mb
            bg = "#FEF9E7" if changed else "transparent"
            rows += (
                f"<tr style='background:{bg};'>"
                f"<td style='padding:6px 8px;font-size:0.83rem;font-weight:500;'>{name}</td>"
                f"<td style='padding:6px 8px;font-size:0.83rem;'>{_va}</td>"
                f"<td style='padding:6px 8px;font-size:0.83rem;'>{_vb}</td>"
                f"</tr>"
            )
        st.markdown(f"""
        <table style='width:100%;border-collapse:collapse;border:1px solid #DDE1E7;border-radius:8px;'>
          <thead><tr style='background:#F4F6F9;'>
            <th style='padding:8px;text-align:left;font-size:0.78rem;color:#6B7885;'>METRIC</th>
            <th style='padding:8px;text-align:left;font-size:0.78rem;color:#6B7885;'>RUN A</th>
            <th style='padding:8px;text-align:left;font-size:0.78rem;color:#6B7885;'>RUN B</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>""", unsafe_allow_html=True)


def _col_header(col, rep: dict) -> None:
    tr = rep.get("test_run", {})
    vrd = tr.get("verdict", "—")
    badge_cls = "badge-fail" if vrd == "FAIL" else "badge-pass"
    col.markdown(f"""
    <div class='tt-card'>
      <div style='font-weight:700;font-size:0.9rem;color:#1A3557;'>{tr.get("test_case_name","—")}</div>
      <div style='font-size:0.78rem;color:#6B7885;margin:3px 0;'>{tr.get("test_case_id","—")}</div>
      <span class='badge {badge_cls}'>{vrd}</span>
    </div>""", unsafe_allow_html=True)


def _sev_card(col, triage: dict) -> None:
    sev = triage.get("severity", "—")
    conf = triage.get("confidence", 0)
    colours = {"CRITICAL":"#C0392B","HIGH":"#E67E22","MEDIUM":"#2471A3","LOW":"#1E8449"}
    c = colours.get(sev, "#6B7885")
    col.markdown(f"""
    <div class='tt-card' style='border-left:4px solid {c};'>
      <div style='font-size:1.1rem;font-weight:700;color:{c};'>{sev}</div>
      <div style='font-size:0.85rem;color:#555;'>Confidence: {conf:.0%}</div>
    </div>""", unsafe_allow_html=True)
