"""
core/triage_engine.py  — Step 3: COMPLETE
------------------------------------------
Sends structured failure context to Claude and returns a TriageResult.

Design:
  - System prompt encodes Claude's role + exact XML output contract
  - User prompt is assembled deterministically from TestRun fields (no free text)
  - Claude returns a single <triage> XML block — nothing else
  - Parser extracts XML, validates required tags, maps to TriageResult
  - Retry with exponential back-off on rate-limit / overload
  - Every call is written to the audit trail
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import anthropic

from .logger import audit
from .models import Recommendation, Severity, TestRun, TriageResult

# KB context injection — silently disabled if dependencies not installed
try:
    from .kb_store import search as _kb_search, format_kb_context as _kb_format
    _KB_AVAILABLE = True
except Exception:
    _KB_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_MODEL  = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS     = int(os.getenv("TRIAGE_MAX_TOKENS", "4096"))
PROMPT_VERSION = "v1.0"
MAX_RETRIES    = 3
BACKOFF_BASE   = 2  # seconds; wait = BACKOFF_BASE ** attempt


# ── Public entry point ────────────────────────────────────────────────────────

def analyse(run: TestRun) -> TriageResult:
    """
    Send the TestRun context to Claude and return a TriageResult.

    Raises:
        anthropic.APIError  — on unrecoverable API failure after retries
        ValueError          — if Claude's response cannot be parsed
    """
    client = anthropic.Anthropic()                 # reads ANTHROPIC_API_KEY from env
    system = _system_prompt()
    user   = _build_prompt(run)

    # ── KB context injection ──────────────────────────────────────────────────
    if _KB_AVAILABLE:
        try:
            failure_summary = run.extra_context.get("failure_summary", "")
            recent_errors   = " ".join(run.error_logs[:3]) if run.error_logs else ""
            kb_query        = f"{run.test_case_name} {recent_errors} {failure_summary}".strip()
            kb_chunks       = _kb_search(kb_query, top_k=5)
            if kb_chunks:
                system += (
                    "\n\n════════════════════════════════════════════\n"
                    "KNOWLEDGE BASE — RUNBOOKS & PAST INCIDENTS\n"
                    "════════════════════════════════════════════\n"
                    + _kb_format(kb_chunks)
                )
                logger.info("KB: injected %d chunks for run=%s", len(kb_chunks), run.run_id)
        except Exception as _kb_err:
            logger.warning("KB search skipped (non-fatal): %s", _kb_err)

    logger.info("Triage call → Claude %s  run=%s  prompt_v=%s",
                DEFAULT_MODEL, run.run_id, PROMPT_VERSION)

    response: anthropic.types.Message | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model      = DEFAULT_MODEL,
                max_tokens = MAX_TOKENS,
                system     = system,
                messages   = [{"role": "user", "content": user}],
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

    audit("triage_call", {
        "run_id":         run.run_id,
        "model":          DEFAULT_MODEL,
        "prompt_version": PROMPT_VERSION,
        "input_tokens":   response.usage.input_tokens,
        "output_tokens":  response.usage.output_tokens,
    })

    result = _parse_response(run, response)
    logger.info("Triage complete  severity=%s  confidence=%.2f  run=%s",
                result.severity.value, result.confidence, run.run_id)
    return result


# ── System prompt ─────────────────────────────────────────────────────────────

def _system_prompt() -> str:
    return """You are a senior test analyst with deep expertise in:
- FTTP (Fibre to the Premises) with GPON/XGS-PON OLT/ONT technology
- FTTN/FTTB (Fibre to the Node/Building) with VDSL2/G.fast DSLAMs
- HFC (Hybrid Fibre Coaxial) with DOCSIS 3.1 CMTSs
- Fixed Wireless access (4G/5G NR gNB and CPE)
- Satellite (Sky Muster)
- BNG, AAA/RADIUS, PPPoE, IPoE, and DHCP session management
- Wholesale broadband KPIs and SLAs

TASK: You will receive a structured test failure report. Perform root cause analysis and output your findings.

OUTPUT CONTRACT — CRITICAL:
Return ONLY a single <triage> XML block. No preamble, no explanation outside the block.
Use this exact schema:

<triage>
  <severity>CRITICAL|HIGH|MEDIUM|LOW</severity>
  <confidence>0.00 to 1.00</confidence>
  <root_cause>
    <summary>One precise sentence identifying the root cause</summary>
    <detail>
      Full technical explanation. Cite specific log timestamps and counter values.
      Explain the failure chain from trigger to observed symptom.
      Reference config fields by name (e.g. interface_wan0_vlan=10 vs service_vlan=2).
    </detail>
  </root_cause>
  <recommendations>
    <recommendation priority="1">
      <action>Exact remediation action with specific values</action>
      <rationale>Why this resolves the root cause</rationale>
      <effort>e.g. "2 min — single config change" or "30 min — requires maintenance window"</effort>
    </recommendation>
    <!-- Add more recommendations as needed, ordered by priority -->
  </recommendations>
</triage>

SEVERITY GUIDE:
  CRITICAL — service completely unusable; SLA breach imminent or in progress
  HIGH     — significant degradation; partial service loss or intermittent failure
  MEDIUM   — test failure with working workaround; not production-impacting
  LOW      — minor non-conformance; cosmetic or edge-case issue

CONFIDENCE GUIDE (0.0–1.0):
  > 0.90 — root cause is unambiguous from logs and config alone
  0.70–0.90 — strong evidence; one minor ambiguity
  0.50–0.70 — probable cause; some information missing
  < 0.50 — hypothesis only; more data collection needed

RULES:
- Never invent log entries or config values not present in the input
- If config_snapshot contradicts log evidence, note the discrepancy
- Recommendations must be ordered: fastest/safest fix first
- Use access-network terminology (NTD not modem, OLT not switch, S-VLAN not outer VLAN)"""


# ── User prompt ───────────────────────────────────────────────────────────────

def _build_prompt(run: TestRun) -> str:
    """
    Build a deterministic, structured user prompt from the TestRun.
    Sections:
      1. Test Metadata
      2. Device Under Test
      3. Topology
      4. Failed Metrics
      5. Configuration Snapshot
      6. Error Log Events
      7. Pre-conditions (if available)
      8. Failure Summary (if available)
      9. Triage request
    """
    lines: list[str] = []

    # ── 1. Test Metadata ──────────────────────────────────────────────────────
    lines += [
        "## FAILED TEST REPORT",
        "",
        f"Test Case ID   : {run.test_case_id}",
        f"Test Case Name : {run.test_case_name}",
        f"Timestamp      : {run.timestamp.isoformat()}",
        f"Verdict        : {run.verdict.value}",
        f"Access Tech    : {run.dut.access_technology}",
    ]
    if run.extra_context.get("speed_tier"):
        lines.append(f"Speed Tier     : {run.extra_context['speed_tier']}")
    if run.extra_context.get("build_version"):
        lines.append(f"Build Version  : {run.extra_context['build_version']}")
    lines.append("")

    # ── 2. Device Under Test ──────────────────────────────────────────────────
    dut = run.dut
    lines += [
        "## DEVICE UNDER TEST",
        "",
        f"Vendor         : {dut.vendor}",
        f"Model          : {dut.model}",
        f"Firmware       : {dut.firmware}",
        f"Device ID      : {dut.device_id}",
    ]
    if dut.management_ip:
        lines.append(f"Management IP  : {dut.management_ip}")
    if dut.location:
        lines.append(f"Location       : {dut.location}")
    lines.append("")

    # ── 3. Topology ───────────────────────────────────────────────────────────
    if run.topology_summary:
        lines += ["## TOPOLOGY", "", run.topology_summary, ""]

    # ── 4. Failed Metrics ─────────────────────────────────────────────────────
    failed = [m for m in run.metrics if m.verdict.value == "FAIL"]
    if failed:
        lines += ["## FAILED METRICS", ""]
        for m in failed:
            expected = f"{m.expected}" + (f" {m.unit}" if m.unit else "")
            measured = f"{m.measured}" + (f" {m.unit}" if m.unit else "")
            lines.append(f"  [{m.verdict.value}] {m.name}: expected={expected}  measured={measured}"
                         + (f"  tolerance={m.tolerance}" if m.tolerance else ""))
        lines.append("")

    if run.metrics:
        passed = [m for m in run.metrics if m.verdict.value == "PASS"]
        if passed:
            lines += ["## PASSING METRICS", ""]
            for m in passed:
                lines.append(f"  [PASS] {m.name}: {m.measured}" + (f" {m.unit}" if m.unit else ""))
            lines.append("")

    # ── 5. Configuration Snapshot ─────────────────────────────────────────────
    config = run.extra_context.get("config_snapshot")
    if config:
        lines += [
            "## CONFIGURATION SNAPSHOT",
            "(Values as captured at test execution time)",
            "",
            json.dumps(config, indent=2),
            "",
        ]

    # ── 6. Test Parameters ────────────────────────────────────────────────────
    test_params = run.extra_context.get("test_parameters")
    if test_params:
        lines += ["## TEST PARAMETERS", ""]
        for k, v in test_params.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    # ── 7. Error Log Events ───────────────────────────────────────────────────
    if run.error_logs:
        lines += ["## LOG EVENTS (chronological)", ""]
        lines += run.error_logs
        lines.append("")

    # ── 8. Pre-conditions ─────────────────────────────────────────────────────
    pre_cond = run.extra_context.get("pre_conditions")
    if pre_cond:
        lines += ["## PRE-CONDITIONS", ""]
        if isinstance(pre_cond, list):
            for pc in pre_cond:
                lines.append(f"  - {pc}")
        else:
            lines.append(str(pre_cond))
        lines.append("")

    # ── 9. Failure Summary (from input, if present) ───────────────────────────
    failure_summary = run.extra_context.get("failure_summary")
    if failure_summary:
        lines += [
            "## FAILURE SUMMARY (from test harness)",
            "",
            failure_summary,
            "",
        ]

    # ── 10. Triage request ────────────────────────────────────────────────────
    lines += [
        "---",
        "Perform root cause analysis on the failure above.",
        "Return your findings in the <triage> XML schema specified in your instructions.",
        "Be specific: cite log timestamps, config field names and values, counter readings.",
    ]

    return "\n".join(lines)


# ── Response parsing ──────────────────────────────────────────────────────────

def _parse_response(run: TestRun, response: anthropic.types.Message) -> TriageResult:
    """
    Extract the <triage> XML block from Claude's response and map to TriageResult.

    Strategy:
      1. Concatenate all text content blocks
      2. Regex-extract the first <triage>…</triage> block
      3. Parse with xml.etree.ElementTree
      4. Map fields to TriageResult Pydantic model
      5. Raise ValueError with context if parsing fails
    """
    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    # Extract <triage> block — Claude may include a brief note before or after
    match = re.search(r"<triage>.*?</triage>", raw_text, re.DOTALL)
    if not match:
        logger.error("No <triage> block found in response:\n%s", raw_text[:500])
        raise ValueError(
            "Claude response did not contain a <triage> XML block. "
            f"Raw response (first 400 chars): {raw_text[:400]}"
        )

    xml_block = match.group(0)

    try:
        root = ET.fromstring(xml_block)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed <triage> XML: {exc}\nXML: {xml_block[:300]}") from exc

    # ── Extract required fields ───────────────────────────────────────────────

    severity_raw = _require(root, "severity", xml_block).strip().upper()
    try:
        severity = Severity(severity_raw)
    except ValueError:
        logger.warning("Unknown severity '%s' — defaulting to HIGH", severity_raw)
        severity = Severity.HIGH

    confidence_raw = _require(root, "confidence", xml_block).strip()
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except ValueError:
        logger.warning("Non-numeric confidence '%s' — defaulting to 0.5", confidence_raw)
        confidence = 0.5

    rc_node = root.find("root_cause")
    if rc_node is None:
        raise ValueError("<root_cause> element missing from <triage> response")

    summary = _text(rc_node, "summary", fallback="(no summary)")
    detail  = _text(rc_node, "detail",  fallback="(no detail)")

    # ── Extract recommendations ───────────────────────────────────────────────

    recommendations: list[Recommendation] = []
    recs_node = root.find("recommendations")
    if recs_node is not None:
        for rec_el in recs_node.findall("recommendation"):
            try:
                priority = int(rec_el.get("priority", "99"))
            except ValueError:
                priority = 99
            recommendations.append(Recommendation(
                priority         = priority,
                action           = _text(rec_el, "action",    fallback="(no action)"),
                rationale        = _text(rec_el, "rationale", fallback="(no rationale)"),
                estimated_effort = _text(rec_el, "effort",    fallback=None),
            ))

    recommendations.sort(key=lambda r: r.priority)

    return TriageResult(
        run_id              = run.run_id,
        severity            = severity,
        root_cause_summary  = summary,
        root_cause_detail   = detail,
        confidence          = confidence,
        recommendations     = recommendations,
        claude_model        = DEFAULT_MODEL,
        prompt_tokens       = response.usage.input_tokens,
        completion_tokens   = response.usage.output_tokens,
        triage_timestamp    = datetime.now(timezone.utc),
    )


# ── XML helpers ───────────────────────────────────────────────────────────────

def _require(root: ET.Element, tag: str, xml_context: str) -> str:
    """Return element text, raise ValueError if element is missing."""
    el = root.find(tag)
    if el is None or el.text is None:
        raise ValueError(
            f"Required <{tag}> element missing or empty in <triage>.\n"
            f"XML: {xml_context[:300]}"
        )
    return el.text


def _text(parent: ET.Element, tag: str, fallback: str | None = None) -> str | None:
    """Return stripped element text, or fallback if absent."""
    el = parent.find(tag)
    if el is None or el.text is None:
        return fallback
    return el.text.strip()
