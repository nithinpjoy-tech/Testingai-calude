"""
tests/test_notifications.py — webhook notification tests.
All HTTP calls are mocked — no real webhooks fired.
"""
from __future__ import annotations
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import httpx

from core.models import (
    DeviceUnderTest, Recommendation, RunReport, Severity,
    TestRun, TriageResult, Verdict,
)
from notifications.webhook import notify, _send_slack, _send_teams


@pytest.fixture
def sample_report() -> RunReport:
    run = TestRun(
        run_id="run-notif-001", test_case_id="TC001",
        test_case_name="PPPoE test", timestamp=datetime(2026,4,28),
        verdict=Verdict.FAIL,
        dut=DeviceUnderTest(device_id="d1", vendor="NetComm",
                            model="NF18ACV", firmware="3.7.2", access_technology="FTTP"),
    )
    triage = TriageResult(
        run_id="run-notif-001", severity=Severity.CRITICAL,
        root_cause_summary="VLAN mismatch", root_cause_detail="Detail.",
        confidence=0.97,
        recommendations=[Recommendation(priority=1, action="Fix VLAN",
                                        rationale="Aligns VLAN", estimated_effort="2 min")],
        claude_model="claude-sonnet-4-20250514",
    )
    from core.reporter import build_report
    return build_report(run, triage)


def test_notify_no_urls_returns_empty(sample_report, monkeypatch):
    monkeypatch.setattr("notifications.webhook.SLACK_WEBHOOK_URL", "")
    monkeypatch.setattr("notifications.webhook.TEAMS_WEBHOOK_URL", "")
    sent = notify(sample_report)
    assert sent == []


@patch("notifications.webhook.httpx.post")
def test_notify_slack_called(mock_post, sample_report, monkeypatch):
    monkeypatch.setattr("notifications.webhook.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    monkeypatch.setattr("notifications.webhook.TEAMS_WEBHOOK_URL", "")
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
    sent = notify(sample_report)
    assert "slack" in sent
    mock_post.assert_called_once()
    payload = mock_post.call_args[1]["json"]
    assert "attachments" in payload


@patch("notifications.webhook.httpx.post")
def test_notify_teams_called(mock_post, sample_report, monkeypatch):
    monkeypatch.setattr("notifications.webhook.SLACK_WEBHOOK_URL", "")
    monkeypatch.setattr("notifications.webhook.TEAMS_WEBHOOK_URL", "https://outlook.office.com/test")
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
    sent = notify(sample_report)
    assert "teams" in sent
    payload = mock_post.call_args[1]["json"]
    assert "attachments" in payload
    card = payload["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"


@patch("notifications.webhook.httpx.post")
def test_notify_both_channels(mock_post, sample_report, monkeypatch):
    monkeypatch.setattr("notifications.webhook.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    monkeypatch.setattr("notifications.webhook.TEAMS_WEBHOOK_URL", "https://outlook.office.com/test")
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
    sent = notify(sample_report)
    assert "slack" in sent
    assert "teams" in sent
    assert mock_post.call_count == 2


@patch("notifications.webhook.httpx.post")
def test_notify_slack_error_does_not_crash(mock_post, sample_report, monkeypatch):
    """Notification failure must never crash the pipeline."""
    monkeypatch.setattr("notifications.webhook.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    monkeypatch.setattr("notifications.webhook.TEAMS_WEBHOOK_URL", "")
    mock_post.side_effect = httpx.ConnectError("connection refused")
    sent = notify(sample_report)   # must not raise
    assert "slack" not in sent


@patch("notifications.webhook.httpx.post")
def test_slack_payload_contains_severity(mock_post, sample_report, monkeypatch):
    monkeypatch.setattr("notifications.webhook.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_post.return_value = MagicMock(raise_for_status=lambda: None)
    _send_slack(sample_report)
    payload_str = str(mock_post.call_args)
    assert "CRITICAL" in payload_str


@patch("notifications.webhook.httpx.post")
def test_teams_payload_contains_facts(mock_post, sample_report, monkeypatch):
    monkeypatch.setattr("notifications.webhook.TEAMS_WEBHOOK_URL", "https://outlook.office.com/test")
    mock_post.return_value = MagicMock(raise_for_status=lambda: None)
    _send_teams(sample_report)
    payload = mock_post.call_args[1]["json"]
    body = payload["attachments"][0]["content"]["body"]
    fact_sets = [b for b in body if b.get("type") == "FactSet"]
    assert len(fact_sets) > 0
