"""
services/chat_service.py
-------------------------
Mid-triage conversational chat service.

Responsibility:
  - Build a context-rich system prompt from the live TestRun, TriageResult,
    FixScript, and accumulated exec_log (list[dict] from StepResult.to_dict())
  - Manage per-run ChatSession state (history, token hygiene)
  - Stream Claude responses token-by-token via the Anthropic API
  - Expose quick-action chips mapped to pre-written prompts

The service is intentionally stateless across calls — all session state
is passed in and returned, so Streamlit can hold it in st.session_state
without any server-side storage.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Generator
from datetime import datetime, timezone
from textwrap import dedent

import anthropic

from core.models import (
    ChatMessage,
    ChatRole,
    ChatSession,
    FixScript,
    TestRun,
    TriageResult,
)

logger = logging.getLogger(__name__)

MODEL       = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS  = int(os.getenv("CHAT_MAX_TOKENS", "1024"))
TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.3"))
# Keep last N user+assistant turns to stay within context limits
MAX_HISTORY = int(os.getenv("CHAT_MAX_HISTORY", "20"))


# ---------------------------------------------------------------------------
# Quick-action chips
# ---------------------------------------------------------------------------

QUICK_ACTIONS: list[tuple[str, str]] = [
    ("Why did this fail?",   "The most recent step failed. Explain in plain English why it failed and whether it blocks the next step."),
    ("Safe to proceed?",     "Given everything you can see in this run so far, is it safe to continue to the next step? Be direct."),
    ("Alternatives?",        "Are there alternative approaches to fix this issue that carry less risk than the current fix script?"),
    ("Explain this error",   "Explain the error output from the most recently failed step in plain English for a non-expert."),
    ("Rollback steps",       "List the exact rollback steps I should follow if the next fix command makes things worse."),
    ("Impact on customers?", "Based on the steps run so far, what is the customer-visible impact right now and will the fix cause any additional interruption?"),
]


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _format_exec_step(entry: dict) -> str:
    status = entry.get("status", "pending").upper()
    lines  = [f"  Step {entry.get('step_number', '?')}: [{status}] {entry.get('description', '')}"]
    if entry.get("command"):
        lines.append(f"    Command : {entry['command']}")
    if entry.get("stdout"):
        lines.append(f"    Output  : {entry['stdout'][:300]}")
    if entry.get("stderr"):
        lines.append(f"    Error   : {entry['stderr'][:300]}")
    return "\n".join(lines)


def _format_fix_script(script: FixScript) -> str:
    cmds = "\n".join(
        f"  {s.step_number}. {s.command}  # {s.description}" for s in script.steps
    )
    rollbacks = "\n".join(
        f"  {s.step_number}. {s.rollback_command}"
        for s in script.steps if s.rollback_command
    )
    pre  = "\n".join(f"  - {c}" for c in script.pre_checks)  or "  none"
    post = "\n".join(f"  - {c}" for c in script.post_checks) or "  none"
    return dedent(f"""\
        Commands:
        {cmds}
        Pre-checks:
        {pre}
        Post-checks:
        {post}
        Rollback:
        {rollbacks or '  none specified'}
    """)


def build_system_prompt(
    run:      TestRun,
    triage:   TriageResult | None,
    script:   FixScript | None,
    exec_log: list[dict],
) -> str:
    """
    Construct the full system prompt injected at the start of every chat
    request. Rebuilt fresh on each call so Claude always has the latest
    step outputs even as execution progresses.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    device_block = dedent(f"""\
        Vendor     : {run.dut.vendor}
        Model      : {run.dut.model}
        Firmware   : {run.dut.firmware}
        Serial     : {run.dut.device_id}
        Technology : {run.dut.access_technology}
        Site       : {run.dut.location or 'unknown'}
    """)

    triage_block = "Not yet available."
    if triage:
        triage_block = dedent(f"""\
            Root cause : {triage.root_cause_summary}
            Detail     : {triage.root_cause_detail}
            Severity   : {triage.severity.value.upper()}
            Confidence : {triage.confidence * 100:.0f}%
        """)

    fix_block = "Not yet generated."
    if script:
        fix_block = _format_fix_script(script)

    steps_block = "No steps executed yet."
    if exec_log:
        steps_block = "\n".join(_format_exec_step(e) for e in exec_log)

    last_failed_note = ""
    failed = [e for e in exec_log if e.get("status") == "failed"]
    if failed:
        last = failed[-1]
        last_failed_note = (
            f"\nNOTE: Step {last.get('step_number')} "
            f"('{last.get('description', '')}') FAILED. "
            f"Error: {last.get('stderr') or last.get('stdout', '')}"
        )

    return dedent(f"""\
        You are an expert  network engineer assistant embedded inside a
        live triage session. The operator can ask you questions at any time
        during the diagnostic and fix execution.

        Your job:
        - Answer questions about what is happening in this specific run
        - Explain step failures in plain English (assume a mid-level NOC operator)
        - Give clear, direct risk assessments — never vague
        - Suggest alternatives only when explicitly asked
        - Never invent step outputs — reference only what appears below
        - Keep answers short (3–5 sentences max) unless detail is explicitly requested

        ── RUN CONTEXT (as of {now}) ────────────────────────────────────────
        Run ID      : {run.run_id}
        Test Case   : {run.test_case_name}
        Verdict     : {run.verdict.value}
        Started     : {run.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")}

        DEVICE:
        {device_block}
        TRIAGE RESULT:
        {triage_block}
        FIX SCRIPT:
        {fix_block}
        EXECUTED STEPS:
        {steps_block}{last_failed_note}
        ─────────────────────────────────────────────────────────────────────
    """)


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def get_or_create_session(
    sessions: dict[str, ChatSession],
    run_id:   str,
) -> ChatSession:
    """Return existing session or create a fresh one with a welcome message."""
    if run_id not in sessions:
        session = ChatSession(run_id=run_id)
        session.add(
            ChatRole.ASSISTANT,
            "Run context loaded. I can see all steps and their outputs. "
            "Ask me anything about what's happening.",
        )
        sessions[run_id] = session
    return sessions[run_id]


def trim_history(session: ChatSession) -> None:
    """
    Keep the conversation history within MAX_HISTORY turns to avoid
    ballooning context. Always preserves the opening assistant message.
    """
    non_system = [m for m in session.messages if m.role != ChatRole.SYSTEM]
    if len(non_system) > MAX_HISTORY:
        first  = non_system[0]
        recent = non_system[-(MAX_HISTORY - 1):]
        session.messages = [first] + recent


# ---------------------------------------------------------------------------
# Streaming response
# ---------------------------------------------------------------------------

def stream_response(
    run:        TestRun,
    triage:     TriageResult | None,
    script:     FixScript | None,
    exec_log:   list[dict],
    session:    ChatSession,
    user_input: str,
) -> Generator[str, None, None]:
    """
    Add the user message to the session, stream Claude's response
    token-by-token, then persist the full assistant reply.

    Usage (Streamlit):
        with st.chat_message("assistant"):
            st.write_stream(
                chat_service.stream_response(run, triage, script, exec_log, session, prompt)
            )

    Yields:
        str — each text chunk as it arrives from the API
    """
    session.add(ChatRole.USER, user_input)
    trim_history(session)

    # System prompt rebuilt fresh so it reflects the latest step outputs
    system_prompt = build_system_prompt(run, triage, script, exec_log)
    api_messages  = session.to_api_messages()

    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env

    logger.info(
        "chat_service.stream_response run_id=%s turns=%d",
        run.run_id,
        len(api_messages),
    )

    full_reply = ""
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=system_prompt,
            messages=api_messages,
        ) as stream:
            for chunk in stream.text_stream:
                full_reply += chunk
                yield chunk

    except anthropic.APIError as exc:
        error_msg = f"[API error: {exc}]"
        yield error_msg
        full_reply = error_msg
        logger.error("chat_service stream error: %s", exc)

    session.add(ChatRole.ASSISTANT, full_reply)
