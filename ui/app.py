"""
ui/app.py  —  Test Triage Console  —  Streamlit entry point.

Run:
    streamlit run ui/app.py

Professional Streamlit redesign for the test triage workflow.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st

# ── Page config — MUST be first Streamlit call ────────────────────────────────
st.set_page_config(
    page_title="Test Triage Console",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from ui.theme import inject_theme
from ui.components.sidebar import render_sidebar

# ── Inject design system ───────────────────────────────────────────────────────
inject_theme()

# ── Session state defaults ─────────────────────────────────────────────────────
_DEFAULTS = {
    "page":             "p01",
    "current_run":      None,
    "triage_result":    None,
    "fix_script":       None,
    "exec_results":     [],
    "raw_input_text":   "",
    "raw_input_format": "json",
    "_loaded_filename": None,   # tracks which file is loaded in triage uploader
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

def _query_flag(name: str) -> bool:
    value = st.query_params.get(name)
    return value == "1" or value == ["1"]


if _query_flag("clear_session"):
    try:
        from db.store import clear_run_history
        clear_run_history()
    except Exception:
        pass

    for key in (
        "current_run",
        "triage_result",
        "fix_script",
        "exec_results",
        "raw_input_text",
        "raw_input_format",
    ):
        st.session_state.pop(key, None)

    st.session_state.page = "p01"
    st.query_params.clear()
    st.rerun()

if _query_flag("new_triage"):
    for key in (
        "current_run",
        "triage_result",
        "fix_script",
        "exec_results",
        "raw_input_text",
        "raw_input_format",
    ):
        st.session_state.pop(key, None)
    st.session_state.page = "p02"
    st.query_params.clear()
    st.rerun()

# ── Sidebar ────────────────────────────────────────────────────────────────────
# Count pending runs that need approval
pending = 0
try:
    from db.store import count_pending
    pending = count_pending()
except Exception:
    pass

api_ok = True
try:
    from core.config import get_config
    cfg = get_config()
    api_ok = bool(cfg.get("claude", {}).get("api_key"))
except Exception:
    api_ok = False

render_sidebar(pending_count=pending, api_ok=api_ok)

# ── Page router ────────────────────────────────────────────────────────────────
import importlib, sys as _sys

def _load(module_name: str):
    """Force fresh load from disk on every run — avoids Streamlit hot-reload misses."""
    _sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)

page = st.session_state.get("page", "p01")

if page == "p01":
    _p = _load("ui.pages.p01_dashboard")
    _p.render()
elif page == "p02":
    _p = _load("ui.pages.p02_triage")
    _p.render()
elif page == "p03":
    _p = _load("ui.pages.p03_fix_script")
    _p.render()
elif page == "p04":
    _p = _load("ui.pages.p04_execute")
    _p.render()
elif page == "p05":
    _p = _load("ui.pages.p05_results")
    _p.render()
elif page == "p06":
    _p = _load("ui.pages.p06_knowledge")
    _p.render()
elif page == "p08":
    _p = _load("ui.pages.p08_run_detail")
    _p.render()
elif page == "history":
    _p = _load("ui.pages.p07_history")
    _p.render()
else:
    st.error(f"Unknown page: {page}")
