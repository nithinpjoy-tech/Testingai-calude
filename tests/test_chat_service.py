"""
tests/test_chat_service.py
--------------------------
Unit tests for the chat service. All Anthropic API calls are mocked —
no API key required, no credit spent.

Run with:
    pytest tests/test_chat_service.py -v
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.models import (
    ChatRole,
    ChatSession,
    DeviceUnderTest,
    FixScript,
    FixStep,
    Recommendation,
    Severity,
    StepStatus,
    TestMetric,
    TestRun,
    TriageResult,
    Verdict,
)
from services import chat_service
from services.chat_service import (
    MAX_HISTORY,
    build_system_prompt,
    get_or_create_session,
    stream_response,
    trim_history,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_run() -> TestRun:
    return TestRun(
        run_id="test-run-001",
        test_case_id="TC-001",
        test_case_name="PPPoE Session Test",
        timestamp=datetime(2026, 4, 30, 10, 0, 0),
        verdict=Verdict.FAIL,
        dut=DeviceUnderTest(
            device_id="NC001",
            vendor="NetComm",
            model="NF18ACV",
            firmware="3.7.2-r4",
            access_technology="FTTP",
        ),
    )


@pytest.fixture
def full_run() -> TestRun:
    return TestRun(
        run_id="test-run-002",
        test_case_id="TC-002",
        test_case_name="PPPoE VLAN Mismatch",
        timestamp=datetime(2026, 4, 30, 10, 0, 0),
        verdict=Verdict.FAIL,
        dut=DeviceUnderTest(
            device_id="NC2041-DEMO",
            vendor="NetComm",
            model="NF18ACV",
            firmware="3.7.2-r4",
            access_technology="FTTP",
            location="NSW-SYD-0042",
        ),
    )


@pytest.fixture
def sample_triage(full_run) -> TriageResult:
    return TriageResult(
        run_id=full_run.run_id,
        severity=Severity.HIGH,
        root_cause_summary="VLAN mismatch on wan0",
        root_cause_detail="NTD configured VLAN 10, OLT expects VLAN 2.",
        confidence=0.91,
        recommendations=[
            Recommendation(priority=1, action="Set VLAN to 2", rationale="OLT service profile mismatch"),
        ],
        claude_model="claude-sonnet-4-20250514",
    )


@pytest.fixture
def sample_script(full_run) -> FixScript:
    return FixScript(
        run_id=full_run.run_id,
        title="Fix VLAN mismatch on wan0",
        pre_checks=["show interface wan0 config"],
        steps=[
            FixStep(
                step_number=1,
                description="Correct VLAN tag",
                command="set interface wan0 vlan-id 2 ; commit",
                expected_output="vlan-id=2",
                rollback_command="set interface wan0 vlan-id 10 ; commit",
            ),
        ],
        post_checks=["show pppoe status"],
    )


@pytest.fixture
def sample_exec_log() -> list[dict]:
    return [
        {
            "step_number": 1,
            "description": "Check current VLAN config",
            "command": "show interface wan0 config",
            "status": "passed",
            "stdout": "wan0: vlan-id 10, encap dot1q",
            "stderr": "",
            "exit_code": 0,
            "pre_check_output": "",
            "post_check_output": "",
            "executed_at": "2026-04-30T10:00:05",
        },
        {
            "step_number": 2,
            "description": "OLT reachability",
            "command": "ping 10.0.0.1",
            "status": "failed",
            "stdout": "",
            "stderr": "PING 10.0.0.1: 100% packet loss",
            "exit_code": 1,
            "pre_check_output": "",
            "post_check_output": "",
            "executed_at": "2026-04-30T10:00:10",
        },
    ]


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_contains_run_id(self, full_run, sample_triage, sample_script, sample_exec_log):
        prompt = build_system_prompt(full_run, sample_triage, sample_script, sample_exec_log)
        assert "test-run-002" in prompt

    def test_contains_root_cause(self, full_run, sample_triage, sample_script, sample_exec_log):
        prompt = build_system_prompt(full_run, sample_triage, sample_script, sample_exec_log)
        assert "VLAN mismatch on wan0" in prompt

    def test_contains_failed_step(self, full_run, sample_triage, sample_script, sample_exec_log):
        prompt = build_system_prompt(full_run, sample_triage, sample_script, sample_exec_log)
        assert "FAILED" in prompt
        assert "OLT reachability" in prompt

    def test_contains_fix_command(self, full_run, sample_triage, sample_script, sample_exec_log):
        prompt = build_system_prompt(full_run, sample_triage, sample_script, sample_exec_log)
        assert "vlan-id 2" in prompt

    def test_no_triage_yet(self, minimal_run):
        prompt = build_system_prompt(minimal_run, None, None, [])
        assert "Not yet available" in prompt
        assert "No steps executed yet" in prompt

    def test_no_script_yet(self, full_run, sample_triage):
        prompt = build_system_prompt(full_run, sample_triage, None, [])
        assert "Not yet generated" in prompt

    def test_device_fields_present(self, full_run, sample_triage, sample_script, sample_exec_log):
        prompt = build_system_prompt(full_run, sample_triage, sample_script, sample_exec_log)
        assert "NF18ACV" in prompt
        assert "3.7.2-r4" in prompt
        assert "NC2041-DEMO" in prompt

    def test_step_output_truncated(self, full_run, sample_triage, sample_script):
        long_log = [{
            "step_number": 1,
            "description": "Check VLAN",
            "command": "show interface wan0",
            "status": "passed",
            "stdout": "UNIQUE_MARKER_" + "x" * 1000,
            "stderr": "",
            "exit_code": 0,
            "pre_check_output": "",
            "post_check_output": "",
            "executed_at": "2026-04-30T10:00:00",
        }]
        prompt = build_system_prompt(full_run, sample_triage, sample_script, long_log)
        marker = "UNIQUE_MARKER_"
        idx = prompt.index(marker) + len(marker)
        # The x-run after the marker should not exceed 300 chars
        x_run = len(prompt[idx:].split()[0])
        assert x_run <= 300, f"Output not truncated: got {x_run} x chars"

    def test_last_failed_note_present(self, full_run, sample_triage, sample_script, sample_exec_log):
        prompt = build_system_prompt(full_run, sample_triage, sample_script, sample_exec_log)
        assert "NOTE:" in prompt
        assert "packet loss" in prompt


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class TestSessionManagement:
    def test_creates_new_session_with_welcome(self, full_run):
        sessions: dict = {}
        session = get_or_create_session(sessions, full_run.run_id)
        assert len(session.messages) == 1
        assert session.messages[0].role == ChatRole.ASSISTANT
        assert "context loaded" in session.messages[0].content.lower()

    def test_returns_existing_session(self, full_run):
        sessions: dict = {}
        s1 = get_or_create_session(sessions, full_run.run_id)
        s2 = get_or_create_session(sessions, full_run.run_id)
        assert s1 is s2

    def test_trim_history_keeps_first_message(self):
        session = ChatSession(run_id="trim-test")
        session.add(ChatRole.ASSISTANT, "Welcome")
        for i in range(MAX_HISTORY + 5):
            session.add(ChatRole.USER, f"Q{i}")
            session.add(ChatRole.ASSISTANT, f"A{i}")

        trim_history(session)
        assert session.messages[0].content == "Welcome"
        assert len(session.messages) <= MAX_HISTORY

    def test_to_api_messages_excludes_system(self):
        session = ChatSession(run_id="api-test")
        session.add(ChatRole.SYSTEM, "system instruction")
        session.add(ChatRole.USER, "hello")
        session.add(ChatRole.ASSISTANT, "hi")

        api_msgs = session.to_api_messages()
        roles = [m["role"] for m in api_msgs]
        assert "system" not in roles
        assert "user" in roles
        assert "assistant" in roles


# ---------------------------------------------------------------------------
# stream_response (mocked API)
# ---------------------------------------------------------------------------

class TestStreamResponse:
    def _make_mock_stream(self, chunks: list[str]):
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.text_stream = iter(chunks)
        return mock_stream

    def test_yields_chunks(self, full_run, sample_triage, sample_script, sample_exec_log):
        sessions: dict = {}
        session = get_or_create_session(sessions, full_run.run_id)
        mock_stream = self._make_mock_stream(["Hello", " world"])

        with patch("services.chat_service.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream
            mock_cls.return_value = mock_client

            chunks = list(stream_response(
                full_run, sample_triage, sample_script, sample_exec_log,
                session, "What happened?",
            ))

        assert chunks == ["Hello", " world"]

    def test_persists_full_reply(self, full_run, sample_triage, sample_script, sample_exec_log):
        sessions: dict = {}
        session = get_or_create_session(sessions, full_run.run_id)
        mock_stream = self._make_mock_stream(["Step", " failed", " because"])

        with patch("services.chat_service.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream
            mock_cls.return_value = mock_client

            list(stream_response(
                full_run, sample_triage, sample_script, sample_exec_log,
                session, "Why?",
            ))

        last = session.messages[-1]
        assert last.role == ChatRole.ASSISTANT
        assert last.content == "Step failed because"

    def test_records_user_message(self, full_run, sample_triage, sample_script, sample_exec_log):
        sessions: dict = {}
        session = get_or_create_session(sessions, full_run.run_id)
        mock_stream = self._make_mock_stream(["ok"])

        with patch("services.chat_service.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream
            mock_cls.return_value = mock_client

            list(stream_response(
                full_run, sample_triage, sample_script, sample_exec_log,
                session, "Is it safe?",
            ))

        user_msgs = [m for m in session.messages if m.role == ChatRole.USER]
        assert any("Is it safe?" in m.content for m in user_msgs)

    def test_no_triage_or_script_still_works(self, minimal_run):
        sessions: dict = {}
        session = get_or_create_session(sessions, minimal_run.run_id)
        mock_stream = self._make_mock_stream(["ok"])

        with patch("services.chat_service.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream
            mock_cls.return_value = mock_client

            chunks = list(stream_response(
                minimal_run, None, None, [], session, "Hello?",
            ))

        assert chunks == ["ok"]

    def test_api_error_yields_error_string(self, full_run, sample_triage, sample_script, sample_exec_log):
        sessions: dict = {}
        session = get_or_create_session(sessions, full_run.run_id)

        with patch("services.chat_service.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.side_effect = chat_service.anthropic.APIError(
                message="rate limited", request=MagicMock(), body={}
            )
            mock_cls.return_value = mock_client

            chunks = list(stream_response(
                full_run, sample_triage, sample_script, sample_exec_log,
                session, "Hello?",
            ))

        assert any("[API error" in c for c in chunks)
