"""
ui/components/severity_banner.py — Feature #15
Displays a coloured banner at the top of every page based on triage severity.
"""
import streamlit as st

_BANNER_CSS = {
    "CRITICAL": ("background:#C0392B;color:#fff;", "🚨 CRITICAL"),
    "HIGH":     ("background:#E67E22;color:#fff;", "⚠️  HIGH"),
    "MEDIUM":   ("background:#2980B9;color:#fff;", "ℹ️  MEDIUM"),
    "LOW":      ("background:#27AE60;color:#fff;", "✅ LOW"),
}

def render_banner() -> None:
    triage = st.session_state.get("triage_result")
    if not triage:
        return
    sev = triage.severity.value if hasattr(triage, "severity") else str(triage.get("severity",""))
    style, label = _BANNER_CSS.get(sev, ("background:#6B7885;color:#fff;", f"ℹ️  {sev}"))
    st.markdown(
        f'<div style="{style}padding:0.6rem 1.2rem;border-radius:6px;'
        f'margin-bottom:1rem;font-weight:600;">{label} — {triage.root_cause_summary if hasattr(triage,"root_cause_summary") else ""}</div>',
        unsafe_allow_html=True,
    )
