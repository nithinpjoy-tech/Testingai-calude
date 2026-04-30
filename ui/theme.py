"""Shared Streamlit theme helpers for the test triage console."""

from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

NAVY = "#0F2744"
ORANGE = "#E8612C"
BG = "#F5F7FA"
BORDER = "#E0E4EA"

THEME_CSS = f"""
<style>
* {{ box-sizing: border-box; }}
html, body, .stApp {{
  font-family: "Inter", "Segoe UI", Arial, sans-serif !important;
  font-size: 13px !important;
  color: #1C2B3A !important;
}}
.stApp {{ background: {BG} !important; }}
.block-container {{ padding: 0 20px 20px !important; max-width: 100% !important; }}
div[data-testid="stVerticalBlock"] {{ gap: 0.75rem; }}
#MainMenu, footer, header {{ visibility: hidden; }}
.stDeployButton {{ display: none !important; }}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"],
div[data-testid="stSidebarNav"] {{
  display: none !important;
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
}}

section[data-testid="stSidebar"] {{
  background: {NAVY} !important;
  border-right: 0.5px solid rgba(255,255,255,0.08) !important;
  width: 240px !important;
  min-width: 240px !important;
  max-width: 240px !important;
  display: block !important;
  visibility: visible !important;
  transform: translateX(0) !important;
  left: 0 !important;
  opacity: 1 !important;
}}
section[data-testid="stSidebar"] > div {{
  width: 240px !important;
  padding: 0 !important;
  position: relative !important;
  min-height: 100vh !important;
}}
button[title="Close sidebar"],
button[title="Open sidebar"],
button[aria-label="Close sidebar"],
button[aria-label="Open sidebar"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"] {{
  display: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
}}
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {{
  gap: 0 !important;
  min-height: 100vh !important;
  padding-bottom: 150px !important;
}}
section[data-testid="stSidebar"] * {{ color: #ECF0F1 !important; }}
section[data-testid="stSidebar"] .stButton {{
  margin: 0 !important;
  padding: 0 !important;
}}
section[data-testid="stSidebar"] .stButton > button {{
  background: transparent !important;
  border: 0.5px solid transparent !important;
  border-radius: 8px !important;
  color: rgba(255,255,255,.72) !important;
  width: 100% !important;
  min-height: 42px !important;
  height: auto !important;
  padding: 8px 12px 8px 42px !important;
  margin: 0 0 4px 0 !important;
  font-size: 13px !important;
  font-weight: 400 !important;
  text-align: left !important;
  display: flex !important;
  align-items: center !important;
  gap: 0 !important;
  transition: all .2s !important;
  line-height: 1.4 !important;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
  background: rgba(255,255,255,.08) !important;
  color: #fff !important;
  border-color: transparent !important;
}}
section[data-testid="stSidebar"] .stButton > button div[data-testid="stMarkdownContainer"] p {{
  text-align: left !important;
}}
section[data-testid="stSidebar"] .stButton > button:focus:not(:focus-visible) {{
  box-shadow: none !important;
  outline: none !important;
}}

.tt-sidebar-logo {{ padding: 0 14px 22px; border-bottom: 0.5px solid rgba(255,255,255,0.1); margin-top: -16px; }}
.tt-sidebar-badge {{ background: {ORANGE}; color: #fff; font-size: 9px; font-weight: 500; letter-spacing: .06em; padding: 3px 7px; border-radius: 4px; display: inline-block; margin-bottom: 6px; font-family: monospace; }}
.tt-sidebar-title {{ color: {ORANGE} !important; font-size: 24px; font-weight: 800; line-height: 1.05; letter-spacing: 0; }}
.tt-sidebar-sub {{ color: rgba(255,255,255,.72) !important; font-size: 10px; margin-top: 7px; line-height: 1.35; max-width: 160px; white-space: normal; }}
.tt-sidebar-section {{ display:block; padding: 20px 10px 12px; margin: 0; color: rgba(255,255,255,.42) !important; font-size: 9px; font-weight: 700; letter-spacing:.08em; text-transform:uppercase; font-family:monospace; line-height: 1; }}
.tt-sidebar-nav {{ padding: 0 10px 16px; }}
.tt-sidebar-item {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: all .2s;
  color: rgba(255,255,255,.72) !important;
  font-size: 13px;
  text-decoration: none !important;
  position: relative;
  min-height: 42px;
  border: 0.5px solid transparent;
}}
.tt-sidebar-item:hover {{
  background: rgba(255,255,255,.08);
  color: #fff !important;
}}
.tt-sidebar-item.active {{
  background: {ORANGE} !important;
  color: #fff !important;
  border-color: {ORANGE} !important;
  font-weight: 600;
}}
.tt-sidebar-icon {{
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  opacity: .6;
}}
.tt-sidebar-item.active .tt-sidebar-icon {{
  opacity: 1;
  color: #fff !important;
}}
.tt-sidebar-badge-count {{
  margin-left: auto;
  background: rgba(255,255,255,.15);
  color: #fff;
  font-size: 9px;
  font-family: monospace;
  padding: 2px 6px;
  border-radius: 4px;
}}
.tt-sidebar-item.active .tt-sidebar-badge-count {{
  background: rgba(255,255,255,.25);
}}
.tt-sidebar-item.active::before {{
  content: "";
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  background: #fff;
  border-radius: 0 4px 4px 0;
}}
.tt-sidebar-divider {{ border-top: 0.5px solid rgba(255,255,255,.1); margin: 10px 10px 0; }}
.tt-sidebar-resources {{ position: fixed !important; left: 20px; bottom: 142px; width: 160px; background: {NAVY}; z-index: 9; }}
.tt-sidebar-resources .tt-sidebar-section {{ padding-top: 12px; }}
.tt-sidebar-resources .tt-sidebar-nav {{ padding-bottom: 8px; }}
.tt-sidebar-clear {{
  position: fixed !important;
  left: 24px;
  bottom: 114px;
  width: 156px;
  height: 28px;
  display: flex !important;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  color: rgba(255,255,255,.74) !important;
  background: rgba(255,255,255,.06);
  border: 0.5px solid rgba(255,255,255,.10);
  font-size: 11px;
  font-weight: 600;
  text-decoration: none !important;
  z-index: 11;
}}
.tt-sidebar-clear:hover {{
  color: #fff !important;
  background: rgba(232,97,44,.22);
  border-color: rgba(232,97,44,.55);
}}
.tt-sidebar-status {{
  position: fixed !important;
  left: 24px;
  bottom: 20px;
  width: 192px;
  padding: 12px 0 0;
  margin: 0;
  border-top: 0.5px solid rgba(255,255,255,.1);
  background: {NAVY};
  z-index: 10;
}}
.tt-sidebar-status-label {{ font-size: 9px; color: rgba(255,255,255,.42) !important; text-transform: uppercase; letter-spacing: .06em; font-family: monospace; line-height: 1.2; }}
.tt-sidebar-status-val {{ font-size: 11px; color: rgba(255,255,255,.78) !important; margin-top: 5px; display: flex; align-items: center; gap: 5px; line-height: 1.25; }}
.tt-dot {{ width: 6px; height: 6px; border-radius: 50%; background: #4CAF50; flex-shrink: 0; display: inline-block; }}

.tt-topbar {{
  background: #fff;
  border-bottom: 0.5px solid {BORDER};
  height: 48px;
  padding: 0 20px;
  margin: 0 -20px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.tt-breadcrumb {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: #9BA8B3; }}
.tt-breadcrumb b {{ color: #1C2B3A; font-weight: 500; }}
.tt-topbar-actions {{ display: flex; align-items: center; gap: 8px; }}
.tt-topbar-pill {{ background: #F5F7FA; border: 0.5px solid {BORDER}; border-radius: 20px; padding: 4px 10px; font-size: 11px; color: #6B7885; display: flex; align-items: center; gap: 5px; font-family: monospace; white-space: nowrap; }}
.tt-btn-orange {{ background: {ORANGE}; border: none; border-radius: 6px; padding: 6px 14px; font-size: 11px; font-weight: 500; color: #fff; display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }}
.tt-btn-orange:hover {{ color: #fff !important; filter: brightness(.96); text-decoration: none !important; }}

.tt-flow-label {{ font-size: 11px; color: #9BA8B3; margin-bottom: 2px; font-family: monospace; }}
.tt-stepper {{ display: flex; align-items: center; gap: 0; margin: 8px 0 20px; }}
.tt-step {{ display: flex; flex-direction: column; align-items: center; flex: 1; }}
.tt-step-circle {{ width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 500; border: 0.5px solid {BORDER}; margin-bottom: 4px; font-family: monospace; }}
.tt-step.done .tt-step-circle {{ background: {ORANGE}; border-color: {ORANGE}; color: #fff; }}
.tt-step.active .tt-step-circle {{ background: {NAVY}; border-color: {NAVY}; color: #fff; }}
.tt-step.pending .tt-step-circle {{ background: #F5F7FA; color: #9BA8B3; }}
.tt-step-label {{ font-size: 9px; color: #9BA8B3; text-align: center; font-family: monospace; white-space: nowrap; }}
.tt-step-line {{ flex: 1; height: 1px; background: {BORDER}; margin-top: -18px; }}
.tt-step-line.done {{ background: {ORANGE}; }}

.tt-kpi-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }}
.tt-kpi {{ background: #fff; border: 0.5px solid {BORDER}; border-radius: 8px; padding: 12px 14px; position: relative; overflow: hidden; }}
.tt-kpi-label {{ font-size: 10px; color: #9BA8B3; text-transform: uppercase; letter-spacing: .06em; font-family: monospace; margin-bottom: 4px; }}
.tt-kpi-value {{ font-size: 22px; font-weight: 500; color: #1C2B3A; line-height: 1; }}
.tt-kpi-delta {{ font-size: 10px; margin-top: 4px; font-family: monospace; }}
.tt-kpi-delta.up {{ color: #2E7D32; }}
.tt-kpi-delta.down {{ color: #C62828; }}
.tt-kpi-delta.neutral {{ color: #9BA8B3; }}
.tt-kpi-bar {{ position: absolute; bottom: 0; left: 0; right: 0; height: 3px; border-radius: 0 0 8px 8px; }}

.tt-card {{ background: #fff; border: 0.5px solid {BORDER}; border-radius: 8px; overflow: hidden; margin-bottom: 12px; }}
.tt-card-head {{ padding: 12px 14px; border-bottom: 0.5px solid {BORDER}; display: flex; align-items: center; justify-content: space-between; }}
.tt-card-title {{ font-size: 12px; font-weight: 500; color: #1C2B3A; }}
.tt-card-body {{ padding: 12px 14px; }}
.tt-tag {{ font-size: 9px; font-family: monospace; font-weight: 500; padding: 2px 7px; border-radius: 3px; display: inline-block; }}
.tt-tag-blue {{ background: #E3F2FD; color: #0D47A1; }}
.tt-tag-green {{ background: #E8F5E9; color: #1B5E20; }}
.tt-tag-purple {{ background: #F3E5F5; color: #6A1B9A; }}
.tt-tag-orange {{ background: #FFF3E0; color: #E65100; }}
.tt-tag-gray {{ background: #F5F7FA; color: #6B7885; border: 0.5px solid #D8DDE4; }}

.tt-sev {{ font-size: 9px; font-weight: 500; padding: 2px 6px; border-radius: 3px; white-space: nowrap; font-family: monospace; display: inline-block; }}
.tt-sev-crit {{ background: #FFEBEE; color: #B71C1C; }}
.tt-sev-high {{ background: #FFF3E0; color: #E65100; }}
.tt-sev-med {{ background: #E3F2FD; color: #0D47A1; }}
.tt-sev-low {{ background: #E8F5E9; color: #1B5E20; }}
.tt-sev-info {{ background: #F3E5F5; color: #6A1B9A; }}

.tt-run-row {{ display: flex; align-items: center; gap: 8px; padding: 7px 0; border-bottom: 0.5px solid {BORDER}; font-size: 11px; }}
.tt-run-row:last-child {{ border-bottom: none; }}
.tt-run-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
.tt-run-dot.pass {{ background: #4CAF50; }}
.tt-run-dot.fail {{ background: #C62828; }}
.tt-run-dot.pending {{ background: #FF9800; }}
.tt-run-name {{ flex: 1; font-weight: 500; color: #1C2B3A; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.tt-run-meta {{ color: #9BA8B3; font-family: monospace; font-size: 10px; }}

.tt-code {{ background: #F8F9FA; border-radius: 0 0 8px 8px; padding: 10px 14px; font-family: monospace; font-size: 10px; line-height: 1.8; overflow-x: auto; color: #4A5568; }}
.tt-code .k {{ color: #9C27B0; }}
.tt-code .s {{ color: #1565C0; }}
.tt-code .n {{ color: #E65100; }}
.tt-code .e {{ color: #C62828; }}
.tt-diagnosis-root {{ background: #FFEBEE; border-left: 3px solid #C62828; padding: 8px 10px; border-radius: 0 4px 4px 0; font-size: 11px; line-height: 1.6; color: #4A1515; }}
.tt-diagnosis-fix {{ font-size: 11px; line-height: 1.7; color: #3D4A56; }}
.tt-step-num {{ display: inline-flex; width: 16px; height: 16px; border-radius: 50%; background: {ORANGE}; color: #fff; align-items: center; justify-content: center; font-size: 9px; font-weight: 500; font-family: monospace; flex-shrink: 0; }}
.tt-bar-track {{ height: 5px; background: #F5F7FA; border-radius: 3px; overflow: hidden; }}
.tt-bar-fill {{ height: 100%; border-radius: 3px; }}
.tt-conf {{ height: 4px; background: #F0F2F5; border-radius: 2px; margin-top: 6px; overflow: hidden; }}
.tt-conf-fill {{ height: 100%; border-radius: 2px; }}
.tt-cite {{ padding: 8px 14px; border-bottom: 0.5px solid {BORDER}; font-size: 10px; line-height: 1.5; color: #6B7885; }}
.tt-cite:last-child {{ border-bottom: 0; }}
.tt-cite-label {{ color: #6A1B9A; font-weight: 500; font-family: monospace; margin-bottom: 2px; display: block; }}
.tt-exec-row {{ display: flex; align-items: flex-start; gap: 10px; padding: 8px 14px; border-bottom: 0.5px solid {BORDER}; font-size: 11px; }}
.tt-exec-row:last-child {{ border-bottom: none; }}
.tt-exec-status {{ width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 9px; flex-shrink: 0; margin-top: 1px; }}
.tt-exec-status.pass {{ background: #E8F5E9; color: #2E7D32; }}
.tt-exec-status.fail {{ background: #FFEBEE; color: #C62828; }}
.tt-exec-status.running {{ background: #FFF3E0; color: #E65100; }}
.tt-exec-status.pending {{ background: #F5F7FA; color: #9BA8B3; }}
.tt-section-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: #9BA8B3; font-family: monospace; margin-bottom: 6px; }}
.tt-approval-banner {{ background: #FFF8E1; border: 0.5px solid #FFD54F; border-radius: 8px; padding: 10px 14px; font-size: 11px; color: #5D4037; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }}
.stButton button[kind="primary"] {{ background: {ORANGE} !important; border-color: {ORANGE} !important; color: #fff !important; }}
@media (max-width: 900px) {{
  .tt-kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
  .tt-step-label {{ white-space: normal; }}
}}
</style>
"""


def inject_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def _value(value: object) -> str:
    return getattr(value, "value", str(value or ""))


def sev_badge(severity: object) -> str:
    s = _value(severity).upper()
    if "CRIT" in s:
        return '<span class="tt-sev tt-sev-crit">CRIT</span>'
    if "HIGH" in s:
        return '<span class="tt-sev tt-sev-high">HIGH</span>'
    if "MED" in s:
        return '<span class="tt-sev tt-sev-med">MED</span>'
    if "LOW" in s:
        return '<span class="tt-sev tt-sev-low">LOW</span>'
    return f'<span class="tt-sev tt-sev-info">{html.escape(s or "?")}</span>'


def tag(text: str, colour: str = "gray") -> str:
    return f'<span class="tt-tag tt-tag-{colour}">{html.escape(text)}</span>'


def section_label(text: str) -> None:
    st.markdown(f'<div class="tt-section-label">{html.escape(text)}</div>', unsafe_allow_html=True)


def card_head(title: str, badge_html: str = "") -> None:
    st.markdown(
        f'<div class="tt-card-head"><span class="tt-card-title">{html.escape(title)}</span>{badge_html}</div>',
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, delta: str, delta_dir: str, bar_colour: str) -> str:
    return (
        '<div class="tt-kpi">'
        f'<div class="tt-kpi-label">{html.escape(label)}</div>'
        f'<div class="tt-kpi-value">{html.escape(value)}</div>'
        f'<div class="tt-kpi-delta {html.escape(delta_dir)}">{html.escape(delta)}</div>'
        f'<div class="tt-kpi-bar" style="background:{bar_colour}"></div>'
        '</div>'
    )


def stepper(steps: list[str], current: int) -> None:
    parts = ['<div class="tt-flow-label">Workflow progress</div><div class="tt-stepper">']
    for i, name in enumerate(steps):
        cls = "done" if i < current else "active" if i == current else "pending"
        parts.append(
            f'<div class="tt-step {cls}">'
            f'<div class="tt-step-circle">{i + 1:02d}</div>'
            f'<div class="tt-step-label">{html.escape(name)}</div>'
            '</div>'
        )
        if i < len(steps) - 1:
            line_cls = "done" if i < current else ""
            parts.append(f'<div class="tt-step-line {line_cls}"></div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def topbar(page_name: str, extra_html: str = "", context: str = "Overview") -> None:
    now = datetime.now().strftime("%a %d %b, %H:%M")
    primary_html = (
        '<a class="tt-btn-orange" href="/?new_triage=1" target="_self">New triage</a>'
        if page_name != "Triage"
        else ""
    )
    mode_pill = (
        '<div class="tt-topbar-pill"><span class="tt-dot"></span>Connected</div>'
        if page_name == "Dashboard"
        else ""
    )
    st.markdown(
        '<div class="tt-topbar">'
        f'<div class="tt-breadcrumb"><b>{html.escape(page_name)}</b><span style="opacity:.4">/</span>{html.escape(context)}</div>'
        '<div class="tt-topbar-actions">'
        f'{extra_html}{mode_pill}<div class="tt-topbar-pill">{html.escape(now)}</div>'
        f'{primary_html}'
        '</div></div>',
        unsafe_allow_html=True,
    )


def cite_block(source: str, relevance: float, snippet: str) -> str:
    pct = int(relevance * 100)
    safe_source = html.escape(str(source))
    safe_snippet = html.escape(str(snippet)[:240])
    ellipsis = "..." if len(str(snippet)) > 240 else ""
    return (
        '<div class="tt-cite">'
        f'<span class="tt-cite-label">{safe_source} - {pct}% match</span>'
        f'{safe_snippet}{ellipsis}'
        '</div>'
    )
