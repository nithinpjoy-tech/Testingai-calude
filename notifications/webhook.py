"""
notifications/webhook.py  — Feature #18
----------------------------------------
Stub for Slack and Teams webhook notifications.
Sends severity-aware message when a run completes or fails.

Currently: structured stub (logs payload, does not POST).
Activate: set SLACK_WEBHOOK_URL or TEAMS_WEBHOOK_URL in .env.

TODO (Step 8): implement _send_slack() with httpx
TODO (Step 8): implement _send_teams() with Adaptive Card payload
"""
from __future__ import annotations
import logging
import os

from core.models import RunReport, Severity

logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")

SEVERITY_COLOUR = {
    Severity.CRITICAL: "#C0392B",
    Severity.HIGH:     "#E67E22",
    Severity.MEDIUM:   "#2980B9",
    Severity.LOW:      "#27AE60",
    Severity.INFO:     "#6B7885",
}


def notify(report: RunReport) -> list[str]:
    """Send notification to all configured channels. Returns list of channels notified."""
    sent: list[str] = []
    if SLACK_WEBHOOK_URL:
        _send_slack(report)
        sent.append("slack")
    if TEAMS_WEBHOOK_URL:
        _send_teams(report)
        sent.append("teams")
    if not sent:
        logger.debug("No webhook URLs configured — skipping notification")
    return sent


def _send_slack(report: RunReport) -> None:
    """POST attachment-style message to Slack. TODO (Step 8)."""
    colour = SEVERITY_COLOUR.get(report.triage.severity, "#6B7885")
    payload = {
        "attachments": [{
            "color":  colour,
            "title":  f"[{report.test_run.verdict.value}] {report.test_run.test_case_name}",
            "text":   report.triage.root_cause_summary,
            "fields": [
                {"title": "Severity",    "value": report.triage.severity.value, "short": True},
                {"title": "Confidence",  "value": f"{report.triage.confidence:.0%}", "short": True},
                {"title": "Run ID",      "value": report.run_id, "short": False},
            ],
        }]
    }
    logger.info("[STUB] Slack payload ready for run %s — activate SLACK_WEBHOOK_URL to send", report.run_id)
    # TODO: await httpx.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)


def _send_teams(report: RunReport) -> None:
    """POST Adaptive Card to MS Teams. TODO (Step 8)."""
    logger.info("[STUB] Teams notification for run %s — activate TEAMS_WEBHOOK_URL to send", report.run_id)
    # TODO: build Adaptive Card + httpx.post(TEAMS_WEBHOOK_URL, ...)
