"""Sidebar navigation styled to match the provided console mockup."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

WORKFLOW_PAGES = [
    ("p01", "Dashboard", "grid"),
    ("p02", "Triage", "clock"),
    ("p03", "Fix Script", "doc"),
    ("p04", "Execute", "play"),
    ("p05", "Results", "list"),
]

RESOURCE_PAGES = [
    ("p06", "Knowledge Base", "book"),
    ("history", "History", "archive"),
]

_SVG = {
    "grid": '<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>',
    "clock": '<circle cx="8" cy="8" r="6"/><path d="M8 5v4l3 1.5" stroke-linecap="round"/>',
    "doc": '<path d="M4 6h8M4 10h5" stroke-linecap="round"/><rect x="2" y="2" width="12" height="12" rx="2"/>',
    "play": '<polygon points="5,3 13,8 5,13"/>',
    "list": '<path d="M3 5h10M3 8h7M3 11h5" stroke-linecap="round"/>',
    "book": '<path d="M2 4h12v10H2zM2 4l6-2 6 2" stroke-linecap="round"/>',
    "archive": '<path d="M8 2v12M4 8l4-4 4 4" stroke-linecap="round"/>',
}


def _icon(name: str) -> str:
    return (
        '<svg class="tt-sidebar-icon" viewBox="0 0 16 16" fill="none" '
        f'stroke="currentColor" stroke-width="1.5">{_SVG.get(name, "")}</svg>'
    )


def _section(label: str) -> None:
    st.markdown(f'<div class="tt-sidebar-section">{label}</div>', unsafe_allow_html=True)


def _item(page_id: str, label: str, icon: str, badge: int = 0) -> None:
    is_active = st.session_state.get("page", "p01") == page_id
    badge_html = f'<span class="tt-sidebar-badge-count">{badge}</span>' if badge else ""
    icon_html  = _icon(icon)
    active_cls = "tt-sidebar-item active" if is_active else "tt-sidebar-item"
    
    # Use a link with a query parameter for navigation
    # This gives us full control over the HTML/CSS
    st.markdown(
        f'<a class="{active_cls}" href="/?page={page_id}" target="_self">'
        f'{icon_html}'
        f'<span>{label}</span>'
        f'{badge_html}'
        '</a>',
        unsafe_allow_html=True
    )

def handle_nav() -> None:
    """Check query params for page navigation."""
    params = st.query_params
    if "page" in params:
        st.session_state.page = params["page"]
        # Clear the param to avoid redirect loops if needed, 
        # but Streamlit usually handles this fine.


def render_sidebar(pending_count: int = 0, api_ok: bool = True) -> None:
    handle_nav()
    with st.sidebar:
        st.markdown(
            '<div class="tt-sidebar-logo">'
            '<div class="tt-sidebar-title">NTIP</div>'
            '<div class="tt-sidebar-sub">AI Powered Test Intelligent Platform</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        _section("Workflow")
        st.markdown('<div class="tt-sidebar-nav">', unsafe_allow_html=True)
        for page_id, label, icon in WORKFLOW_PAGES:
            _item(page_id, label, icon, pending_count if page_id == "p02" else 0)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="tt-sidebar-divider"></div>', unsafe_allow_html=True)

        st.markdown('<div class="tt-sidebar-resources">', unsafe_allow_html=True)
        _section("Resources")
        st.markdown('<div class="tt-sidebar-nav">', unsafe_allow_html=True)
        for page_id, label, icon in RESOURCE_PAGES:
            _item(page_id, label, icon)
        st.markdown("</div></div>", unsafe_allow_html=True)

        st.markdown(
            '<a class="tt-sidebar-clear" href="?clear_session=1" target="_self">'
            '<span>↺</span><span>Clear session</span>'
            '</a>',
            unsafe_allow_html=True,
        )

        dot_colour = "#4CAF50" if api_ok else "#C62828"
        dot_label = "Connected" if api_ok else "Disconnected"
        now = datetime.now().strftime("%d %b, %H:%M")
        st.markdown(
            '<div class="tt-sidebar-status">'
            '<div class="tt-sidebar-status-label">API Status</div>'
            f'<div class="tt-sidebar-status-val"><span class="tt-dot" style="background:{dot_colour}"></span>{dot_label}</div>'
            '<div style="margin-top:6px">'
            '<div class="tt-sidebar-status-label">Run today</div>'
            f'<div class="tt-sidebar-status-val" style="color:rgba(255,255,255,.55)">{pending_count} pending - {now}</div>'
            '</div></div>',
            unsafe_allow_html=True,
        )
