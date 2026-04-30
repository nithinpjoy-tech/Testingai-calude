"""Multi-format parsers.

Each parser accepts raw text/bytes and produces a canonical `TestRun`.
Auto-detection chooses the right one based on content (and optionally a hint).

Supported formats:
  * JSON  — application/json
  * XML   — application/xml
  * YAML  — application/yaml

Adding a new format = subclass `BaseParser` and register in `PARSERS`.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import yaml

from .models import (
    DUT,
    AccessTechnology,
    LogEvent,
    Metric,
    Severity,
    TestRun,
    Verdict,
)


# ---------------------------------------------------------------------------
# Helpers — convert a generic dict (from JSON/YAML/XML?dict) to TestRun
# ---------------------------------------------------------------------------


def _coerce_severity(v: Any) -> Severity:
    if isinstance(v, Severity):
        return v
    try:
        return Severity(str(v).upper())
    except ValueError:
        return Severity.INFO


def _coerce_verdict(v: Any) -> Verdict:
    if isinstance(v, Verdict):
        return v
    try:
        return Verdict(str(v).upper())
    except ValueError:
        return Verdict.INCONCLUSIVE


def _coerce_access_tech(v: Any) -> AccessTechnology:
    if v is None:
        return AccessTechnology.UNKNOWN
    try:
        return AccessTechnology(str(v).upper().replace("-", "_").replace(" ", "_"))
    except ValueError:
        return AccessTechnology.UNKNOWN


def _coerce_dt(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def dict_to_test_run(d: dict[str, Any], source_format: str) -> TestRun:
    """Convert a loosely-shaped dict into a strict TestRun."""
    duts = [DUT(**dut) for dut in d.get("duts", [])]
    pass_criteria = [Metric(**m) for m in d.get("pass_criteria", [])]
    measurements = [Metric(**m) for m in d.get("measurements", [])]

    log_events: list[LogEvent] = []
    for ev in d.get("log_events", []):
        log_events.append(
            LogEvent(
                timestamp=_coerce_dt(ev.get("timestamp")),
                severity=_coerce_severity(ev.get("severity", "INFO")),
                source=ev.get("source"),
                message=ev.get("message", ""),
            )
        )

    return TestRun(
        test_id=d["test_id"],
        test_name=d.get("test_name", d["test_id"]),
        description=d.get("description"),
        run_timestamp=_coerce_dt(d.get("run_timestamp")),
        build_version=d.get("build_version"),
        access_technology=_coerce_access_tech(d.get("access_technology")),
        speed_tier=d.get("speed_tier"),
        duts=duts,
        topology=d.get("topology"),
        pre_conditions=list(d.get("pre_conditions", [])),
        test_parameters=dict(d.get("test_parameters", {})),
        pass_criteria=pass_criteria,
        measurements=measurements,
        config_snapshot=dict(d.get("config_snapshot", {})),
        log_events=log_events,
        verdict=_coerce_verdict(d.get("verdict", "INCONCLUSIVE")),
        failure_summary=d.get("failure_summary"),
        raw_input_format=source_format,
    )


# ---------------------------------------------------------------------------
# Parser interface + concrete parsers
# ---------------------------------------------------------------------------


class BaseParser(ABC):
    name: str

    @abstractmethod
    def can_parse(self, raw: str) -> bool: ...

    @abstractmethod
    def parse(self, raw: str) -> TestRun: ...


class JSONParser(BaseParser):
    name = "json"

    def can_parse(self, raw: str) -> bool:
        s = raw.lstrip()
        return s.startswith("{") or s.startswith("[")

    def parse(self, raw: str) -> TestRun:
        return dict_to_test_run(json.loads(raw), self.name)


class YAMLParser(BaseParser):
    name = "yaml"

    def can_parse(self, raw: str) -> bool:
        # YAML is a superset of JSON. Only claim it if it doesn't look like JSON
        # but does have a YAML signature.
        s = raw.lstrip()
        if s.startswith("{") or s.startswith("["):
            return False
        # Look for top-level YAML key: either "key:" at start of line or "---" doc start.
        return bool(re.search(r"(?m)^[A-Za-z_][\w-]*\s*:", raw)) or s.startswith("---")

    def parse(self, raw: str) -> TestRun:
        d = yaml.safe_load(raw)
        if not isinstance(d, dict):
            raise ValueError("YAML root must be a mapping")
        return dict_to_test_run(d, self.name)


class XMLParser(BaseParser):
    name = "xml"

    def can_parse(self, raw: str) -> bool:
        return raw.lstrip().startswith("<")

    def parse(self, raw: str) -> TestRun:
        root = ET.fromstring(raw)
        d = self._element_to_dict(root)
        # If the root element is "test_run", unwrap it.
        if root.tag == "test_run":
            pass
        elif "test_run" in d:
            d = d["test_run"]
        return dict_to_test_run(d, self.name)

    # --- XML ? dict conversion (handles repeated tags as lists) ---
    def _element_to_dict(self, el: ET.Element) -> Any:
        # Leaf with text only.
        if len(el) == 0 and not el.attrib:
            text = (el.text or "").strip()
            return text or None

        result: dict[str, Any] = dict(el.attrib)
        # Group children by tag.
        children_by_tag: dict[str, list[Any]] = {}
        for child in el:
            children_by_tag.setdefault(child.tag, []).append(self._element_to_dict(child))

        # Tags that semantically must be lists in our schema.
        list_tags = {
            "duts", "dut",
            "pass_criteria", "measurements", "log_events",
            "pre_conditions", "criterion", "metric", "event", "pre_condition",
        }
        for tag, vals in children_by_tag.items():
            # If this is a wrapper tag whose only child is a repeated entry, flatten.
            if tag in {"duts", "pass_criteria", "measurements", "log_events", "pre_conditions"}:
                # vals is a list with one wrapper-dict that itself contains the repeated child
                if len(vals) == 1 and isinstance(vals[0], dict):
                    inner = vals[0]
                    # take the values of the only inner key as the list
                    inner_keys = list(inner.keys())
                    if len(inner_keys) == 1:
                        items = inner[inner_keys[0]]
                        result[tag] = items if isinstance(items, list) else [items]
                        continue
                result[tag] = vals
            elif len(vals) == 1 and tag not in list_tags:
                result[tag] = vals[0]
            else:
                result[tag] = vals
        return result


# Registry order matters for auto-detect: try the most specific first.
PARSERS: list[BaseParser] = [JSONParser(), XMLParser(), YAMLParser()]


def parse_auto(raw: str, hint: str | None = None) -> TestRun:
    """Auto-detect format and parse. `hint` may be a file extension or MIME type."""
    if hint:
        h = hint.lower().lstrip(".")
        for p in PARSERS:
            if p.name == h or h in p.name:
                return p.parse(raw)
    for p in PARSERS:
        if p.can_parse(raw):
            return p.parse(raw)
    raise ValueError("Could not detect input format. Supported: json, xml, yaml.")