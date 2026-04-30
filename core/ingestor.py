"""
core/ingestor.py  — Milestone 2: raw log ingestion added
---------------------------------------------------------
Supports JSON, XML, and raw device log (*.log / *.txt).

Raw log parser uses regex to extract:
  - DUT metadata from comment header lines
  - Log events (timestamp / severity / source / message)
  - Verdict from final comment line
  - Config snapshot from inline JSON comment blocks (optional)

For devices that don't write structured headers, falls back to
extracting all log lines as error_logs and marking verdict as INCONCLUSIVE
unless a "verdict: FAIL/PASS" comment is found.
"""
from __future__ import annotations

import json
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from .models import DeviceUnderTest, TestMetric, TestRun, Verdict
from .logger import get_logger

log = get_logger(__name__)


def ingest(file_path: str) -> TestRun:
    """Auto-detect format by extension and return a normalised TestRun."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    suffix = path.suffix.lower()
    log.info("Ingesting %s (format=%s)", path.name, suffix)

    if suffix == ".json":
        return _from_json(path)
    elif suffix == ".xml":
        return _from_xml(path)
    elif suffix in {".log", ".txt"}:
        return _from_raw_log(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Supported: .json .xml .log .txt")


# ── Format parsers ────────────────────────────────────────────────────────────

def _from_json(path: Path) -> TestRun:
    data = json.loads(path.read_text())
    return _map(data, "json", str(path))


def _from_xml(path: Path) -> TestRun:
    root = ET.parse(path).getroot()
    data = _xml_to_dict(root)
    return _map(data, "xml", str(path))


def _from_raw_log(path: Path) -> TestRun:
    """
    Parse a raw device log file into a TestRun.

    Expected log format (# comment lines carry metadata):
      # Device: <vendor> <model>  FW: <firmware>  Serial: <serial>
      # Capture start: <ISO timestamp>
      YYYY-MM-DDTHH:MM:SS.sssZ [LEVEL] source: message
      ...
      # End of log — test verdict: FAIL|PASS

    Also supports the  sample log format used in pppoe_vlan_mismatch.log.
    """
    text  = path.read_text()
    lines = text.splitlines()

    # ── Extract metadata from # comment header ────────────────────────────────
    device_id = "unknown"
    vendor    = "unknown"
    model_    = "unknown"
    firmware  = "unknown"
    timestamp = datetime.now(timezone.utc)
    verdict   = Verdict.INCONCLUSIVE
    failure_summary = None

    for line in lines:
        s = line.strip()
        if not s.startswith("#"):
            continue

        # Device line: "# Device: NetComm NF18ACV  FW: 3.7.2-r4  Serial: NF18ACV-19A4-002871"
        m = re.search(r"Device:\s+(\S+)\s+(\S+)\s+FW:\s+(\S+)\s+Serial:\s+(\S+)", s, re.I)
        if m:
            vendor, model_, firmware, device_id = m.group(1,2,3,4)

        # Capture timestamp: "# Capture start: 2026-04-28T03:14:20Z"
        m = re.search(r"Capture\s+start:\s+(\S+)", s, re.I)
        if m:
            try:
                timestamp = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            except ValueError:
                pass

        # Verdict: "# End of log — test verdict: FAIL"  or  "# test verdict: PASS"
        m = re.search(r"(?:test\s+)?verdict:\s+(PASS|FAIL|BLOCKED|INCONCLUSIVE)", s, re.I)
        if m:
            verdict = Verdict(m.group(1).upper())

        # Failure summary: "# Failure summary: ..."
        m = re.search(r"Failure\s+summary:\s+(.+)", s, re.I)
        if m:
            failure_summary = m.group(1).strip()

    # ── Extract log events (non-comment lines) ────────────────────────────────
    # Pattern: 2026-04-28T03:14:21.003Z [INFO ] ntd.pppoe: Starting PPPoE...
    event_re = re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[\.\d]*Z?)"
        r"\s+\[(?P<sev>[A-Z ]+)\]"
        r"\s+(?P<src>[^\s:]+):\s*"
        r"(?P<msg>.+)$"
    )
    error_logs: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = event_re.match(s)
        if m:
            ts  = m.group("ts")
            sev = m.group("sev").strip()
            src = m.group("src")
            msg = m.group("msg")
            error_logs.append(f"[{ts}] {sev:<6} {src}: {msg}")
        else:
            # Unstructured line — include as-is (avoids data loss)
            error_logs.append(s)

    # ── Build minimal config snapshot from log evidence ───────────────────────
    # Look for key=value patterns in log messages that reveal config
    config_snapshot: dict = {}
    vlan_re = re.compile(r"vlan[-_]?id?[=:\s]+(\d+)", re.I)
    for entry in error_logs:
        m = vlan_re.search(entry)
        if m:
            # Take first VLAN seen as configured value
            if "ntd" not in config_snapshot:
                config_snapshot["ntd"] = {"interface_wan0_vlan": int(m.group(1))}
            break

    # Expected VLAN from log: "expected service-vlan 2" or "expected=2"
    exp_re = re.compile(r"expected(?:\s+service-?vlan|\s*=\s*|\s+)(\d+)", re.I)
    for entry in error_logs:
        m = exp_re.search(entry)
        if m:
            config_snapshot.setdefault("olt_port", {})["service_vlan"] = int(m.group(1))
            break

    # ── Determine test case name from filename ────────────────────────────────
    test_case_id   = path.stem.upper().replace("-", "_")
    test_case_name = path.stem.replace("_", " ").replace("-", " ").title()

    extra: dict = {}
    if failure_summary:
        extra["failure_summary"] = failure_summary
    if config_snapshot:
        extra["config_snapshot"] = config_snapshot

    dut = DeviceUnderTest(
        device_id         = device_id,
        vendor            = vendor,
        model             = model_,
        firmware          = firmware,
        access_technology = "FTTP",   # default; override if detectable in log
    )

    return TestRun(
        run_id           = str(uuid.uuid4()),
        test_case_id     = test_case_id,
        test_case_name   = test_case_name,
        timestamp        = timestamp,
        verdict          = verdict,
        dut              = dut,
        metrics          = [],      # no structured metrics in raw log
        error_logs       = error_logs,
        raw_input_format = "log",
        raw_input_path   = str(path),
        extra_context    = extra,
    )


# ── Normalised JSON/XML mapping ───────────────────────────────────────────────

def _map(data: dict, fmt: str, raw_path: str) -> TestRun:
    # DUT — support both 'dut' (dict) and 'duts' (list)
    dut_raw = data.get("dut") or {}
    if not dut_raw and "duts" in data:
        duts_val = data["duts"]
        if isinstance(duts_val, dict) and "dut" in duts_val:
            duts_val = duts_val["dut"]
        if isinstance(duts_val, list):
            ntd = next((d for d in duts_val if isinstance(d, dict) and d.get("role") == "NTD"),
                       duts_val[0])
        else:
            ntd = duts_val
        dut_raw = ntd if isinstance(ntd, dict) else {}

    dut = DeviceUnderTest(
        device_id         = dut_raw.get("serial") or dut_raw.get("device_id") or "unknown",
        vendor            = dut_raw.get("vendor", "unknown"),
        model             = dut_raw.get("model", "unknown"),
        firmware          = dut_raw.get("firmware", "unknown"),
        access_technology = data.get("access_technology", "FTTP"),
        management_ip     = dut_raw.get("mgmt_address") or dut_raw.get("management_ip"),
    )

    # Metrics
    metrics: list[TestMetric] = []
    measurements = {m["name"]: m for m in data.get("measurements", [])}
    for criterion in data.get("pass_criteria", []):
        name = criterion["name"]
        meas = measurements.get(name, {})
        metrics.append(TestMetric(
            name     = name,
            expected = criterion.get("expected"),
            measured = meas.get("actual"),
            verdict  = Verdict.PASS if criterion.get("passed") else Verdict.FAIL,
        ))

    # Log events — JSON list or XML {"event": [...]}
    raw_events = data.get("log_events", [])
    if isinstance(raw_events, dict):
        raw_events = raw_events.get("event", [])
    if isinstance(raw_events, dict):
        raw_events = [raw_events]
    error_logs = [
        "[{}] {:6s} {}: {}".format(
            e.get("timestamp", ""), str(e.get("severity", "INFO")).upper(),
            e.get("source", ""),    e.get("message", ""),
        )
        for e in raw_events if isinstance(e, dict)
    ]

    return TestRun(
        run_id            = data.get("run_id") or str(uuid.uuid4()),
        test_case_id      = data.get("test_id", "unknown"),
        test_case_name    = data.get("test_name", "unknown"),
        timestamp         = datetime.fromisoformat(
                                data.get("run_timestamp", datetime.now(timezone.utc).isoformat())
                                .replace("Z", "+00:00")
                            ),
        verdict           = Verdict(data.get("verdict", "FAIL")),
        dut               = dut,
        topology_summary  = data.get("topology"),
        metrics           = metrics,
        error_logs        = error_logs,
        raw_input_format  = fmt,
        raw_input_path    = raw_path,
        extra_context     = {
            k: data[k] for k in (
                "config_snapshot", "failure_summary", "speed_tier",
                "pre_conditions", "test_parameters", "description", "build_version",
            ) if k in data
        },
    )


# ── XML helper ────────────────────────────────────────────────────────────────

def _xml_to_dict(element: ET.Element) -> dict | list | str:
    children = list(element)
    if not children:
        return element.text or ""
    tags = [c.tag for c in children]
    result: dict = {}
    for child in children:
        val = _xml_to_dict(child)
        if child.tag in result:
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(val)
        else:
            result[child.tag] = val
    return result
