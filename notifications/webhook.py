"""
notifications/webhook.py  — Milestone 3: webhooks activated
-------------------------------------------------------------
Sends severity-aware notifications to Slack and/or MS Teams
when a run completes.

Activation: set SLACK_WEBHOOK_URL or TEAMS_WEBHOOK_URL in .env.
Both channels are independent — one, both, or neither can be active.

Slack:  uses attachment format (compatible with all Slack tiers)
Teams:  uses Adaptive Card via Incoming Webhook connector
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx

from core.models import RunReport, Severity

logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")
NOTIFY_TIMEOUT_S  = 8   # seconds

SEVERITY_COLOUR = {
    Severity.CRITICAL: "#C0392B",
    Severity.HIGH:     "#E67E22",
    Severity.MEDIUM:   "#2980B9",
    Severity.LOW:      "#27AE60",
}

SEVERITY_EMOJI = {
    Severity.CRITICAL: "🚨",
    Severity.HIGH:     "⚠️",
    Severity.MEDIUM:   "ℹ️",
    Severity.LOW:      "✅",
}


def notify(report: RunReport) -> list[str]:
    """
    Send notification to all configured channels.
    Returns list of channel names successfully notified.
    Errors are logged and swallowed — notification failure must never crash the pipeline.
    """
    sent: list[str] = []

    if SLACK_WEBHOOK_URL:
        try:
            _send_slack(report)
            sent.append("slack")
            logger.info("Slack notification sent for run %s", report.run_id)
        except Exception as exc:
            logger.error("Slack notification failed for run %s: %s", report.run_id, exc)

    if TEAMS_WEBHOOK_URL:
        try:
            _send_teams(report)
            sent.append("teams")
            logger.info("Teams notification sent for run %s", report.run_id)
        except Exception as exc:
            logger.error("Teams notification failed for run %s: %s", report.run_id, exc)

    if not sent:
        logger.debug("No webhook URLs configured — skipping notification for run %s", report.run_id)

    return sent


# ── Slack ─────────────────────────────────────────────────────────────────────

def _send_slack(report: RunReport) -> None:
    """POST an attachment-style message to Slack."""
    t      = report.triage
    run    = report.test_run
    colour = SEVERITY_COLOUR.get(t.severity, "#6B7885")
    emoji  = SEVERITY_EMOJI.get(t.severity, "ℹ️")
    ts     = report.generated_at.strftime("%Y-%m-%d %H:%M UTC")

    recs_text = "\n".join(
        f"  {r.priority}. {r.action}" for r in t.recommendations[:3]
    ) or "None"

    payload = {
        "attachments": [{
            "color":    colour,
            "fallback": f"[{t.severity.value}] {run.test_case_name} — {run.verdict.value}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji}Test Triage — {t.severity.value}",
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Test Case*\n{run.test_case_name}"},
                        {"type": "mrkdwn", "text": f"*Verdict*\n{run.verdict.value}"},
                        {"type": "mrkdwn", "text": f"*Device*\n{run.dut.vendor} {run.dut.model}"},
                        {"type": "mrkdwn", "text": f"*Confidence*\n{t.confidence:.0%}"},
                    ]
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Root Cause*\n{t.root_cause_summary}"}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Top Recommendations*\n{recs_text}"}
                },
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn",
                                  "text": f"Run ID: `{report.run_id}` · {ts}"}]
                }
            ],
        }]
    }

    resp = httpx.post(SLACK_WEBHOOK_URL, json=payload, timeout=NOTIFY_TIMEOUT_S)
    resp.raise_for_status()


# ── Microsoft Teams ───────────────────────────────────────────────────────────

def _send_teams(report: RunReport) -> None:
    """POST an Adaptive Card to a Microsoft Teams channel via Incoming Webhook."""
    t      = report.triage
    run    = report.test_run
    colour = SEVERITY_COLOUR.get(t.severity, "#6B7885").lstrip("#")
    emoji  = SEVERITY_EMOJI.get(t.severity, "ℹ️")
    ts     = report.generated_at.strftime("%Y-%m-%d %H:%M UTC")

    facts = [
        {"title": "Test Case",   "value": run.test_case_name},
        {"title": "Verdict",     "value": run.verdict.value},
        {"title": "Severity",    "value": t.severity.value},
        {"title": "Confidence",  "value": f"{t.confidence:.0%}"},
        {"title": "Device",      "value": f"{run.dut.vendor} {run.dut.model} ({run.dut.firmware})"},
        {"title": "Technology",  "value": run.dut.access_technology},
        {"title": "Run ID",      "value": report.run_id},
        {"title": "Timestamp",   "value": ts},
    ]
    if t.recommendations:
        top = t.recommendations[0]
        facts.append({"title": "Top Fix", "value": top.action})

    # Adaptive Card (compatible with Teams Incoming Webhook)
    payload = {
        "type":        "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type":    "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type":   "TextBlock",
                        "size":   "Medium",
                        "weight": "Bolder",
                        "text":   f"{emoji}  Triage Alert — {t.severity.value}",
                        "color":  "Attention" if t.severity.value in ("CRITICAL","HIGH") else "Default",
                    },
                    {
                        "type":  "TextBlock",
                        "text":  t.root_cause_summary,
                        "wrap":  True,
                        "color": "Default",
                    },
                    {"type": "FactSet", "facts": facts},
                ],
            }
        }]
    }

    resp = httpx.post(TEAMS_WEBHOOK_URL, json=payload, timeout=NOTIFY_TIMEOUT_S)
    resp.raise_for_status()
