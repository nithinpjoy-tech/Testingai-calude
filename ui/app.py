"""
ui/app.py — Streamlit entry point (Step 5: COMPLETE)
Handles: page config, theme, session state init, sidebar, severity banner, routing.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import config
import streamlit as st

st.set_page_config(
    page_title="NBN Test Triage Tool",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Professional theme injection ──────────────────────────────────────────────
st.markdown("""<style>
/* Colour tokens */
:root {
  --c-primary:#1A3557; --c-accent:#E8612C;
  --c-bg:#F4F6F9;      --c-surface:#FFFFFF;
  --c-border:#DDE1E7;  --c-text:#1C2B3A;
  --c-muted:#6B7885;
  --c-crit:#C0392B;    --c-high:#E67E22;
  --c-med:#2471A3;     --c-low:#1E8449;
  --c-pass:#D5F5E3;    --c-fail:#FADBD8;
}

/* App background */
.stApp { background: var(--c-bg) !important; }

/* Sidebar */
section[data-testid="stSidebar"] {
  background: var(--c-primary) !important;
}
section[data-testid="stSidebar"] * { color: #ECF0F1 !important; }
section[data-testid="stSidebar"] .stButton button {
  background: transparent !important;
  border: 1px solid rgba(255,255,255,0.2) !important;
  color: #ECF0F1 !important;
  text-align: left !important;
  margin-bottom: 4px !important;
}
section[data-testid="stSidebar"] .stButton button:hover {
  background: rgba(255,255,255,0.12) !important;
  border-color: var(--c-accent) !important;
}
section[data-testid="stSidebar"] .stButton[data-active="true"] button {
  background: var(--c-accent) !important;
  border-color: var(--c-accent) !important;
}

/* Logo Button styling (First button in sidebar) */
section[data-testid="stSidebar"] div.stButton:first-of-type button {
    background: transparent !important;
    border: none !important;
    padding: 0.5rem 0 1rem 0 !important;
    text-align: left !important;
    display: block !important;
    width: 100% !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] div.stButton:first-of-type button:hover {
    background: transparent !important;
    border: none !important;
}
section[data-testid="stSidebar"] div.stButton:first-of-type button p {
    font-size: 1.8rem;
    font-weight: 900;
    letter-spacing: -1px;
    background: linear-gradient(90deg, #FFFFFF, #E8612C);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0;
}
section[data-testid="stSidebar"] div.stButton:first-of-type button::after {
    content: "AI powered Network test intelligence platform.";
    display: block;
    font-size: 0.75rem;
    opacity: 0.8;
    margin-top: 4px;
    line-height: 1.3;
    font-weight: 500;
    color: #FFFFFF;
    -webkit-text-fill-color: initial;
    text-transform: none;
    text-align: left;
}

/* Cards */
.tt-card {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 10px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1rem;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.tt-card-accent { border-left: 4px solid var(--c-accent); }

/* Metric-style KPI cards */
.kpi-card {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 10px;
  padding: 1rem 1.25rem;
  text-align: center;
}
.kpi-value { font-size: 2rem; font-weight: 700; color: var(--c-primary); }
.kpi-label { font-size: 0.85rem; color: var(--c-muted); margin-top: 2px; }

/* Badges */
.badge {
  display: inline-block;
  padding: 3px 12px;
  border-radius: 12px;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.badge-pass    { background:#D5F5E3; color:#1E8449; }
.badge-fail    { background:#FADBD8; color:#922B21; }
.badge-crit    { background:#FADBD8; color:#922B21; }
.badge-high    { background:#FDEBD0; color:#784212; }
.badge-med     { background:#D6EAF8; color:#1A5276; }
.badge-low     { background:#D5F5E3; color:#1E8449; }
.badge-pending { background:#EBF5FB; color:#5D6D7E; }

/* Step rows */
.step-row {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 8px;
  padding: 0.9rem 1.2rem;
  margin-bottom: 0.6rem;
}
.step-running { border-left: 4px solid var(--c-accent); }
.step-passed  { border-left: 4px solid var(--c-low); }
.step-failed  { border-left: 4px solid var(--c-crit); }

/* Code blocks */
.stCode { font-size: 0.82rem !important; }

/* Divider spacing */
hr { margin: 1.2rem 0 !important; }

/* Hide streamlit branding */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }

/* Hide default pages navigation since we use a custom one */
[data-testid="stSidebarNav"] { display: none !important; }
</style>""", unsafe_allow_html=True)

# ── Session state defaults ────────────────────────────────────────────────────
_DEFAULTS = {
    "current_run":    None,   # TestRun
    "triage_result":  None,   # TriageResult
    "fix_script":     None,   # FixScript
    "exec_log":       [],     # list[StepResult.to_dict()]
    "exec_done":      False,
    "approved":       False,
    "active_page":    "dashboard",
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar + severity banner ─────────────────────────────────────────────────
from ui.components.sidebar import render_sidebar
from ui.components.severity_banner import render_banner
render_sidebar()
render_banner()

# ── Page routing ──────────────────────────────────────────────────────────────
import importlib
_PAGES = {
    "dashboard":   "ui.pages.p01_dashboard",
    "triage":      "ui.pages.p02_triage",
    "remediation": "ui.pages.p03_remediation",
    "comparison":  "ui.pages.p04_comparison",
    "replay":      "ui.pages.p05_replay",
}
mod = importlib.import_module(_PAGES.get(st.session_state.active_page, "ui.pages.p01_dashboard"))
mod.render()
