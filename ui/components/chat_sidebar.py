"""
ui/components/chat_sidebar.py
------------------------------
Mid-triage conversational chat panel for the remediation page.

Drop into any page that has a live triage session in st.session_state:

    from ui.components.chat_sidebar import render_chat_panel

    with right_col:
        render_chat_panel()

The component reads context directly from st.session_state:
    current_run     — TestRun
    triage_result   — TriageResult | None
    fix_script      — FixScript | None
    exec_log        — list[dict] from StepResult.to_dict()

Session state it manages under its own keys:
    chat_sessions   — dict[run_id, ChatSession]
    chat_input_key  — int  (forces chat_input widget reset after each send)
"""
from __future__ import annotations

import streamlit as st

from core.models import ChatRole
from services import chat_service
from services.chat_service import QUICK_ACTIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_state() -> None:
    if "chat_sessions" not in st.session_state:
        st.session_state["chat_sessions"] = {}
    if "chat_input_key" not in st.session_state:
        st.session_state["chat_input_key"] = 0


def _role_label(role: ChatRole) -> str:
    return "assistant" if role == ChatRole.ASSISTANT else "user"


def _handle_send(user_input: str) -> None:
    """
    Write the user bubble immediately, then stream the assistant reply.
    Renders inside whatever Streamlit container is currently active.
    """
    run      = st.session_state.get("current_run")
    triage   = st.session_state.get("triage_result")
    script   = st.session_state.get("fix_script")
    exec_log = st.session_state.get("exec_log") or []

    sessions = st.session_state["chat_sessions"]
    session  = chat_service.get_or_create_session(sessions, run.run_id)

    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        st.write_stream(
            chat_service.stream_response(run, triage, script, exec_log, session, user_input)
        )

    # Force the chat_input widget to reset on next render
    st.session_state["chat_input_key"] += 1


# ---------------------------------------------------------------------------
# Public render function
# ---------------------------------------------------------------------------

def render_chat_panel() -> None:
    """
    Render the mid-triage chat panel. Reads run context from st.session_state.
    Intended to be placed inside a column on the remediation page.

    Shows a 'not yet available' placeholder when triage hasn't run yet.
    """
    _init_state()

    run    = st.session_state.get("current_run")
    triage = st.session_state.get("triage_result")

    if not run or not triage:
        st.info(
            "Chat will be available once triage analysis is complete.",
            icon="💬",
        )
        return

    sessions = st.session_state["chat_sessions"]
    session  = chat_service.get_or_create_session(sessions, run.run_id)
    exec_log = st.session_state.get("exec_log") or []

    # ── Failure alert ─────────────────────────────────────────────────────────
    failed = [e for e in exec_log if e.get("status") == "failed"]
    if failed:
        last = failed[-1]
        st.warning(
            f"Step {last.get('step_number')} failed — ask Claude what happened.",
            icon="⚠️",
        )

    # ── Conversation history (scrollable box) ─────────────────────────────────
    steps_done = len([e for e in exec_log if e.get("status") in ("passed", "failed", "skipped")])
    st.caption(f"{steps_done} step{'s' if steps_done != 1 else ''} executed · context live")

    chat_container = st.container(height=340, border=True)
    with chat_container:
        for msg in session.messages:
            if msg.role == ChatRole.SYSTEM:
                continue
            with st.chat_message(_role_label(msg.role)):
                st.markdown(msg.content)

    # ── Quick-action chips ────────────────────────────────────────────────────
    st.markdown(
        "<p style='font-size:11px;opacity:0.55;margin:8px 0 4px;'>"
        "Quick actions</p>",
        unsafe_allow_html=True,
    )
    chip_cols = st.columns(2)
    for i, (label, prompt) in enumerate(QUICK_ACTIONS):
        with chip_cols[i % 2]:
            if st.button(
                label,
                key=f"chip_{run.run_id}_{i}",
                use_container_width=True,
            ):
                _handle_send(prompt)
                st.rerun()

    st.divider()

    # ── Free-text input ───────────────────────────────────────────────────────
    user_input = st.chat_input(
        placeholder="Ask about this run…",
        key=f"chat_input_{st.session_state['chat_input_key']}",
    )
    if user_input and user_input.strip():
        _handle_send(user_input.strip())
        st.rerun()
