"""ui/components/sidebar.py — Navigation + session info."""
import streamlit as st
from core.models import Verdict

PAGES = [
    ("dashboard",      "📊", "Dashboard"),
    ("triage",         "🧠", "Triage"),
    ("remediation",    "🔧", "Remediation"),
    ("comparison",     "⚖️", "Compare Runs"),
    ("replay",         "▶️", "Replay"),
    ("knowledge_base", "📚", "Knowledge Base"),
]

def render_sidebar() -> None:
    with st.sidebar:
        # Logo / title block (styled as logo via CSS in app.py)
        if st.button("NTIP", key="nav_logo_btn", type="tertiary", use_container_width=True):
            st.session_state.active_page = "dashboard"
            st.rerun()

        st.markdown("---")

        for key, icon, label in PAGES:
            active = st.session_state.get("active_page") == key
            # Indicate readiness with subtle dot
            dot = _readiness_dot(key)
            btn_label = f"{icon}  {label} {dot}"
            if st.button(btn_label, key=f"nav_{key}", use_container_width=True):
                st.session_state.active_page = key
                st.rerun()

        st.markdown("---")

        # Current run info
        run = st.session_state.get("current_run")
        if run:
            v = run.verdict.value
            colour = "#C0392B" if v == "FAIL" else "#27AE60"
            st.markdown(f"""
            <div style="font-size:0.78rem;opacity:0.85;">
              <b>Active Run</b><br>
              <span style="font-size:0.72rem;">{run.test_case_id}</span><br>
              <span style="color:{colour};font-weight:700;">{v}</span>
              &nbsp;·&nbsp;{run.dut.access_technology}
            </div>""", unsafe_allow_html=True)
            if st.button("✕  Clear session", key="clear_session", use_container_width=True):
                for k in ["current_run","triage_result","fix_script","exec_log","exec_done","approved"]:
                    st.session_state[k] = [] if k == "exec_log" else None if k != "approved" else False
                    if k == "exec_done": st.session_state[k] = False
                st.rerun()

        st.markdown("""
        <div style="position: fixed; bottom: 15px; left: 20px; font-size: 0.75rem; color: rgba(255, 255, 255, 0.4); z-index: 999999;">
            v0.1.0-milestone1 • Claude Sonnet 4
        </div>
        """, unsafe_allow_html=True)


def _readiness_dot(page_key: str) -> str:
    """Tiny indicator showing whether the page has data ready."""
    run    = st.session_state.get("current_run")
    triage = st.session_state.get("triage_result")
    script = st.session_state.get("fix_script")
    done   = st.session_state.get("exec_done")

    ready = {
        "dashboard":      True,
        "triage":         run is not None,
        "remediation":    triage is not None,
        "comparison":     True,
        "replay":         True,
        "knowledge_base": True,
    }
    return "🟢" if ready.get(page_key) else "⚪"
