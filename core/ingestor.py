"""
core/ingestor.py
----------------
Auto-detects format (JSON / XML / raw log) and returns a normalised TestRun.
All downstream services consume TestRun — format details stay here.

TODO (Step 2): implement _from_raw_log() — regex + LLM-assisted parser
"""
from __future__ import annotations
import json
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from .models import DeviceUnderTest, TestMetric, TestRun, Verdict
from .logger import get_logger

log = get_logger(__name__)


def ingest(file_path: str) -> TestRun:
    """Auto-detect format from extension and return a normalised TestRun."""
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
        raise ValueError(f"Unsupported file type: {suffix}")


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
    Parse raw device log into TestRun.
    TODO (Step 2): regex-based extraction of DUT, verdict, errors.
    For now returns a minimal stub from filename so the pipeline doesn't crash.
    """
    raise NotImplementedError("Raw log ingestion: implement in Step 2")


# ── Normalised mapping ────────────────────────────────────────────────────────

def _map(data: dict, fmt: str, raw_path: str) -> TestRun:
    """Map a parsed dict → TestRun regardless of source format."""

    # DUT — support both 'dut' (dict) and 'duts' (list, take first NTD)
    dut_raw = data.get("dut") or {}
    if not dut_raw and "duts" in data:
        duts_val = data["duts"]
        # XML parser wraps repeated <dut> as {"dut": [...]}, JSON uses a plain list
        if isinstance(duts_val, dict) and "dut" in duts_val:
            duts_val = duts_val["dut"]
        if isinstance(duts_val, list):
            ntd = next((d for d in duts_val if isinstance(d, dict) and d.get("role") == "NTD"), duts_val[0])
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

    # Metrics — from pass_criteria + measurements (JSON schema)
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

    # Error logs — flatten log_events (JSON list or XML {"event": [...]})
    raw_events = data.get("log_events", [])
    if isinstance(raw_events, dict):           # XML wraps repeated <event> tags
        raw_events = raw_events.get("event", [])
    if isinstance(raw_events, dict):           # single event element
        raw_events = [raw_events]
    error_logs = [
        "[{}] {:6s} {}: {}".format(
            e.get("timestamp", ""),
            str(e.get("severity", "INFO")).upper(),
            e.get("source", ""),
            e.get("message", ""),
        )
        for e in raw_events if isinstance(e, dict)
    ]

    return TestRun(
        run_id            = data.get("run_id") or str(uuid.uuid4()),
        test_case_id      = data.get("test_id", "unknown"),
        test_case_name    = data.get("test_name", "unknown"),
        timestamp         = datetime.fromisoformat(
                                data.get("run_timestamp", datetime.utcnow().isoformat())
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
                "pre_conditions", "test_parameters", "description",
                "build_version",
            ) if k in data
        },
    )


# ── XML helper ────────────────────────────────────────────────────────────────

def _xml_to_dict(element: ET.Element) -> dict | list | str:
    """Recursively convert an XML element to a Python dict/list/str."""
    children = list(element)
    if not children:
        return element.text or ""

    # Detect repeated tags → list
    tags = [c.tag for c in children]
    if len(tags) != len(set(tags)):
        # Has duplicates — collect into a list under the common tag
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

    return {child.tag: _xml_to_dict(child) for child in children}
