"""
core/remediation.py  — Step 3: COMPLETE
-----------------------------------------
Calls Claude to generate an ordered, idempotent fix script from a TriageResult.

Each FixStep includes:
  - command        CLI command to execute on the target device
  - pre_check      Command that must succeed (exit 0) before this step runs
  - post_check     Command that must succeed (exit 0) after this step completes
  - expected_output Substring that must appear in command output
  - rollback_command Inverse command to undo this step if a later step fails

The script is returned as FixScript with all steps in PENDING status.
Execution lives in executor.py — nothing runs here.
"""
from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET

import anthropic

from .logger import audit
from .models import ExecutionMode, FixScript, FixStep, StepStatus, TestRun, TriageResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS    = int(os.getenv("REMEDIATION_MAX_TOKENS", "4096"))
PROMPT_VERSION = "v1.0"
MAX_RETRIES   = 3
BACKOFF_BASE  = 2


# ── Public entry point ────────────────────────────────────────────────────────

def generate_fix_script(run: TestRun, triage: TriageResult) -> FixScript:
    """
    Generate a FixScript from the TriageResult.
    Returns a FixScript with all steps in PENDING status — not yet executed.

    Raises:
        anthropic.APIError  on unrecoverable API failure after retries
        ValueError          if Claude's response cannot be parsed
    """
    client = anthropic.Anthropic()
    system = _system_prompt(run)
    prompt = _build_remediation_prompt(run, triage)

    logger.info("Remediation call → Claude %s  run=%s", DEFAULT_MODEL, run.run_id)

    response: anthropic.types.Message | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model      = DEFAULT_MODEL,
                max_tokens = MAX_TOKENS,
                system     = system,
                messages   = [{"role": "user", "content": prompt}],
            )
            break
        except (anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            if attempt == MAX_RETRIES:
                raise
            wait = BACKOFF_BASE ** attempt
            logger.warning("Claude %s (attempt %d/%d) — retrying in %ds",
                           type(exc).__name__, attempt, MAX_RETRIES, wait)
            time.sleep(wait)

    assert response is not None

    audit("remediation_call", {
        "run_id":         run.run_id,
        "model":          DEFAULT_MODEL,
        "prompt_version": PROMPT_VERSION,
        "input_tokens":   response.usage.input_tokens,
        "output_tokens":  response.usage.output_tokens,
    })

    script = _parse_fix_script(run, response)
    logger.info("Fix script generated: '%s'  steps=%d  run=%s",
                script.title, len(script.steps), run.run_id)
    return script


# ── System prompt ─────────────────────────────────────────────────────────────

def _system_prompt(run: TestRun) -> str:
    tech  = run.dut.access_technology
    vendor = run.dut.vendor
    model  = run.dut.model
    fw     = run.dut.firmware

    return f"""You are a senior NBN field engineer specialised in remediating faults on NBN access equipment.

TARGET DEVICE: {vendor} {model}  Firmware: {fw}  Technology: {tech}

YOUR TASK: Generate a safe, minimal, ordered fix script to resolve the confirmed root cause.

OUTPUT CONTRACT — CRITICAL:
Return ONLY a single <fix_script> XML block. No preamble, no explanation outside the block.
Use this exact schema:

<fix_script>
  <title>Brief descriptive title for this fix (e.g. "Correct wan0 VLAN mismatch on NF18ACV")</title>

  <pre_checks>
    <check>Command to verify device is reachable and state is as expected before starting</check>
    <!-- Add more pre-checks as needed -->
  </pre_checks>

  <steps>
    <step number="1">
      <description>What this step does in plain English</description>
      <command>Exact CLI command to run on the device</command>
      <pre_check>Command to verify precondition for THIS step (optional — omit tag if not needed)</pre_check>
      <expected_output>Substring that must appear in the command output to consider step passed</expected_output>
      <post_check>Command to verify this step's change took effect</post_check>
      <rollback>Exact command to undo this step if a later step fails</rollback>
    </step>
    <!-- Add more steps as needed — maximum 10 -->
  </steps>

  <post_checks>
    <check>Command to verify the service is now working end-to-end</check>
    <!-- Add more post-checks as needed -->
  </post_checks>
</fix_script>

RULES:
1. IDEMPOTENT — every step must be safe to re-run. Check current state before changing.
2. MINIMAL — fix only what the root cause analysis identified. Do not make speculative changes.
3. ORDERED — steps must be in the correct dependency order (read → verify → change → verify).
4. ROLLBACK — every step that changes state MUST have a rollback command.
5. SPECIFIC — use exact config field names and values from the triage. No placeholders.
6. NBN-CORRECT — use vendor CLI syntax for {vendor} {model} firmware {fw}.
7. SAFE-FIRST — read/show commands before write/set commands. Never change what you haven't read.
8. ONE ISSUE — scope is strictly the confirmed root cause. Do not fix unrelated issues.

COMMAND STYLE for {vendor} {model}:
- Read config: show interface wan0 config
- Set VLAN:    set interface wan0 vlan-id <value>
- Commit:      commit
- Verify:      show interface wan0 status
- PPPoE:       show pppoe status
- Rollback:    set interface wan0 vlan-id <previous-value> ; commit"""


# ── User prompt ───────────────────────────────────────────────────────────────

def _build_remediation_prompt(run: TestRun, triage: TriageResult) -> str:
    """Build the user prompt from triage findings and DUT context."""
    lines: list[str] = []

    # ── Confirmed root cause ──────────────────────────────────────────────────
    lines += [
        "## CONFIRMED ROOT CAUSE",
        "",
        f"Summary   : {triage.root_cause_summary}",
        "",
        "Detail:",
        triage.root_cause_detail,
        "",
        f"Severity  : {triage.severity.value}",
        f"Confidence: {triage.confidence:.0%}",
        "",
    ]

    # ── Recommendations from triage ───────────────────────────────────────────
    if triage.recommendations:
        lines += ["## RECOMMENDED ACTIONS (from triage)", ""]
        for rec in triage.recommendations:
            lines.append(f"  {rec.priority}. {rec.action}")
            lines.append(f"     Rationale: {rec.rationale}")
            if rec.estimated_effort:
                lines.append(f"     Effort: {rec.estimated_effort}")
            lines.append("")

    # ── Device context ────────────────────────────────────────────────────────
    dut = run.dut
    lines += [
        "## TARGET DEVICE",
        "",
        f"Vendor     : {dut.vendor}",
        f"Model      : {dut.model}",
        f"Firmware   : {dut.firmware}",
        f"Device ID  : {dut.device_id}",
        f"Access Tech: {dut.access_technology}",
    ]
    if dut.management_ip:
        lines.append(f"Mgmt IP    : {dut.management_ip}")
    lines.append("")

    # ── Config snapshot (exact values to fix) ────────────────────────────────
    config = run.extra_context.get("config_snapshot")
    if config:
        import json
        lines += [
            "## CURRENT CONFIGURATION (at time of failure)",
            "(These are the values you are fixing — do not invent values)",
            "",
            json.dumps(config, indent=2),
            "",
        ]

    # ── Test parameters (expected correct values) ─────────────────────────────
    params = run.extra_context.get("test_parameters")
    if params:
        import json
        lines += [
            "## EXPECTED CORRECT VALUES (from test specification)",
            "",
            json.dumps(params, indent=2),
            "",
        ]

    # ── Topology for context ──────────────────────────────────────────────────
    if run.topology_summary:
        lines += ["## TOPOLOGY", "", run.topology_summary, ""]

    # ── Request ───────────────────────────────────────────────────────────────
    lines += [
        "---",
        "Generate a fix script that resolves ONLY the confirmed root cause above.",
        "Use the exact config values shown — do not invent or approximate values.",
        "Return your response in the <fix_script> XML schema specified in your instructions.",
    ]

    return "\n".join(lines)


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_fix_script(run: TestRun, response: anthropic.types.Message) -> FixScript:
    """
    Extract <fix_script> XML from Claude's response and map to FixScript.

    Strategy:
      1. Concatenate all text blocks
      2. Regex-extract <fix_script>…</fix_script>
      3. Parse with ElementTree
      4. Map to FixScript + FixStep Pydantic models
    """
    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    match = re.search(r"<fix_script>.*?</fix_script>", raw_text, re.DOTALL)
    if not match:
        logger.error("No <fix_script> block in response:\n%s", raw_text[:500])
        raise ValueError(
            "Claude response did not contain a <fix_script> XML block. "
            f"Raw response (first 400 chars): {raw_text[:400]}"
        )

    xml_block = match.group(0)

    try:
        root = ET.fromstring(xml_block)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed <fix_script> XML: {exc}\nXML: {xml_block[:400]}") from exc

    # Title
    title_el = root.find("title")
    title = title_el.text.strip() if title_el is not None and title_el.text else f"Fix for {run.run_id}"

    # Global pre-checks
    pre_checks: list[str] = [
        c.text.strip()
        for c in root.findall("pre_checks/check")
        if c.text
    ]

    # Global post-checks
    post_checks: list[str] = [
        c.text.strip()
        for c in root.findall("post_checks/check")
        if c.text
    ]

    # Steps
    steps: list[FixStep] = []
    for step_el in root.findall("steps/step"):
        try:
            num = int(step_el.get("number", "0"))
        except ValueError:
            num = len(steps) + 1

        steps.append(FixStep(
            step_number      = num,
            description      = _el_text(step_el, "description", "(no description)"),
            command          = _el_text(step_el, "command", "echo no-command"),
            pre_check        = _el_text(step_el, "pre_check"),
            expected_output  = _el_text(step_el, "expected_output"),
            post_check       = _el_text(step_el, "post_check"),
            rollback_command = _el_text(step_el, "rollback"),
            status           = StepStatus.PENDING,
        ))

    if not steps:
        raise ValueError("<fix_script> contains no <step> elements — unusable script")

    steps.sort(key=lambda s: s.step_number)

    return FixScript(
        run_id         = run.run_id,
        title          = title,
        pre_checks     = pre_checks,
        steps          = steps,
        post_checks    = post_checks,
        execution_mode = ExecutionMode.SIMULATED,
    )


def _el_text(parent: ET.Element, tag: str, fallback: str | None = None) -> str | None:
    """Return stripped text of a child element, or fallback if missing/empty."""
    el = parent.find(tag)
    if el is None or not el.text:
        return fallback
    return el.text.strip()
