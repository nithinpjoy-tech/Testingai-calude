"""
tests/test_triage_engine.py
---------------------------
Unit tests for triage_engine.py.
All Claude API calls are mocked — no real API calls, no token spend.

Run: pytest tests/test_triage_engine.py -v
"""
from __future__ import annotations
import textwrap
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.models import (
    DeviceUnderTest, Severity, TestMetric, TestRun, Verdict,
)
from core.triage_engine import (
    _build_prompt, _parse_response, _system_prompt, analyse,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def pppoe_run() -> TestRun:
    """Minimal TestRun matching the PPPoE VLAN mismatch sample."""
    return TestRun(
        run_id         = "run-test-001",
        test_case_id   = "TC_PPPOE_FTTP_001",
        test_case_name = "PPPoE session establishment on FTTP NTD (nbn 100/40)",
        timestamp      = datetime(2026, 4, 28, 3, 14, 21),
        verdict        = Verdict.FAIL,
        dut            = DeviceUnderTest(
            device_id="NF18ACV-19A4-002871",
            vendor="NetComm", model="NF18ACV", firmware="3.7.2-r4",
            access_technology="FTTP", management_ip="192.168.100.1",
        ),
        topology_summary="NTD wan0 -- OLT g-1/0/3 -- BNG (POI-Sydney) — service VLAN expected=2",
        metrics=[
            TestMetric(name="pppoe_state",          expected="lcp-up",  measured="padi-sent", verdict=Verdict.FAIL),
            TestMetric(name="dhcp_state",           expected="bound",   measured="no-lease",  verdict=Verdict.FAIL),
            TestMetric(name="session_setup_time_ms",expected="<5000",   measured="timeout",   verdict=Verdict.FAIL),
        ],
        error_logs=[
            "[2026-04-28T03:14:21Z] INFO   ntd.pppoe: Starting PPPoE discovery on wan0 (vlan-id=10)",
            "[2026-04-28T03:15:51Z] ERROR  ntd.pppoe: PPPoE discovery failed: no PADO received after 3 attempts",
            "[2026-04-28T03:15:52Z] INFO   olt.access: Frame dropped — S-VLAN mismatch got=10 expected=2",
        ],
        extra_context={
            "config_snapshot": {
                "ntd": {"interface_wan0_vlan": 10, "pppoe_client": "enabled"},
                "olt_port": {"service_vlan": 2, "service_profile": "NBN-RES-100-40"},
            },
            "failure_summary": "PADI sent but no PADO received. OLT drops frames with VLAN 10.",
            "speed_tier": "100/40",
        },
    )


def _make_mock_response(xml_body: str) -> MagicMock:
    """Build a mock anthropic.Message with the given XML as the text content."""
    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = xml_body
    usage = MagicMock()
    usage.input_tokens  = 350
    usage.output_tokens = 180
    response = MagicMock()
    response.content = [content_block]
    response.usage   = usage
    return response


# ── System prompt tests ───────────────────────────────────────────────────────

def test_system_prompt_contains_nbn_tech():
    sp = _system_prompt()
    for tech in ["FTTP", "FTTN", "HFC", "Fixed Wireless", "PPPoE"]:
        assert tech in sp, f"System prompt missing '{tech}'"


def test_system_prompt_contains_xml_schema():
    sp = _system_prompt()
    assert "<triage>" in sp
    assert "<severity>" in sp
    assert "<root_cause>" in sp
    assert "<recommendations>" in sp


# ── Prompt builder tests ──────────────────────────────────────────────────────

def test_build_prompt_contains_test_metadata(pppoe_run):
    prompt = _build_prompt(pppoe_run)
    assert "TC_PPPOE_FTTP_001" in prompt
    assert "PPPoE session establishment" in prompt
    assert "FTTP" in prompt


def test_build_prompt_contains_dut_details(pppoe_run):
    prompt = _build_prompt(pppoe_run)
    assert "NetComm" in prompt
    assert "NF18ACV" in prompt
    assert "3.7.2-r4" in prompt


def test_build_prompt_contains_failed_metrics(pppoe_run):
    prompt = _build_prompt(pppoe_run)
    assert "pppoe_state" in prompt
    assert "lcp-up" in prompt
    assert "padi-sent" in prompt


def test_build_prompt_contains_config_snapshot(pppoe_run):
    prompt = _build_prompt(pppoe_run)
    assert "interface_wan0_vlan" in prompt
    assert "10" in prompt   # the wrong VLAN
    assert "service_vlan" in prompt
    assert "2" in prompt    # the correct VLAN


def test_build_prompt_contains_error_logs(pppoe_run):
    prompt = _build_prompt(pppoe_run)
    assert "PADO" in prompt
    assert "S-VLAN mismatch" in prompt


def test_build_prompt_contains_failure_summary(pppoe_run):
    prompt = _build_prompt(pppoe_run)
    assert "PADI sent but no PADO received" in prompt


# ── Response parser tests ─────────────────────────────────────────────────────

GOOD_RESPONSE = textwrap.dedent("""\
    <triage>
      <severity>CRITICAL</severity>
      <confidence>0.97</confidence>
      <root_cause>
        <summary>NTD wan0 is tagged with VLAN 10 but the OLT service profile NBN-RES-100-40 expects service-VLAN 2, causing all PPPoE discovery frames to be silently dropped.</summary>
        <detail>
          At 03:14:21Z the NTD sent PADI frames tagged VLAN 10 on wan0. The OLT port g-1/0/3
          is provisioned with service-profile NBN-RES-100-40 which maps to S-VLAN 2. The
          S-VLAN translation table has no entry for VLAN 10, so every frame is dropped and
          the sv-vlan-mismatch counter incremented to 42 within 90 seconds. The NTD retried
          3 times over 90 seconds without receiving a PADO, then declared discovery timeout.
          config_snapshot confirms: ntd.interface_wan0_vlan=10, olt_port.service_vlan=2.
        </detail>
      </root_cause>
      <recommendations>
        <recommendation priority="1">
          <action>Change NTD wan0 VLAN from 10 to 2: set interface wan0 vlan-id 2; commit</action>
          <rationale>Aligns the NTD C-VLAN with the OLT S-VLAN translation rule for NBN-RES-100-40. PPPoE PADI will be forwarded and PADO returned.</rationale>
          <effort>2 min — single CLI config change, no maintenance window required</effort>
        </recommendation>
        <recommendation priority="2">
          <action>Verify TR-069 ACS profile 4711 has correct VLAN=2 for speed tier 100/40 to prevent recurrence</action>
          <rationale>If ACS provisioned VLAN 10, the same misconfiguration will recur on every factory-reset NTD provisioned from this profile.</rationale>
          <effort>10 min — ACS portal check; no device downtime</effort>
        </recommendation>
      </recommendations>
    </triage>
""")

def test_parse_response_returns_triage_result(pppoe_run):
    mock_resp = _make_mock_response(GOOD_RESPONSE)
    result = _parse_response(pppoe_run, mock_resp)
    assert result.run_id == "run-test-001"
    assert result.severity == Severity.CRITICAL
    assert abs(result.confidence - 0.97) < 0.001
    assert "VLAN 10" in result.root_cause_summary or "wan0" in result.root_cause_summary
    assert len(result.recommendations) == 2
    assert result.recommendations[0].priority == 1
    assert "2" in result.recommendations[0].action     # VLAN 2
    assert result.prompt_tokens  == 350
    assert result.completion_tokens == 180


def test_parse_response_recommendations_sorted(pppoe_run):
    # Swap priority order in XML — parser must sort
    swapped = GOOD_RESPONSE.replace('priority="1"', 'priority="ZZZ"').replace('priority="2"', 'priority="1"').replace('priority="ZZZ"', 'priority="2"')
    result = _parse_response(pppoe_run, _make_mock_response(swapped))
    priorities = [r.priority for r in result.recommendations]
    assert priorities == sorted(priorities)


def test_parse_response_no_triage_block_raises(pppoe_run):
    mock_resp = _make_mock_response("I cannot determine the root cause without more information.")
    with pytest.raises(ValueError, match="<triage>"):
        _parse_response(pppoe_run, mock_resp)


def test_parse_response_malformed_xml_raises(pppoe_run):
    mock_resp = _make_mock_response("<triage><severity>CRITICAL</triage>")
    with pytest.raises(ValueError):
        _parse_response(pppoe_run, mock_resp)


def test_parse_response_unknown_severity_defaults_high(pppoe_run):
    xml = GOOD_RESPONSE.replace("<severity>CRITICAL</severity>", "<severity>EXTREME</severity>")
    result = _parse_response(pppoe_run, _make_mock_response(xml))
    assert result.severity == Severity.HIGH  # fallback


def test_parse_response_confidence_clamped(pppoe_run):
    xml = GOOD_RESPONSE.replace("<confidence>0.97</confidence>", "<confidence>1.5</confidence>")
    result = _parse_response(pppoe_run, _make_mock_response(xml))
    assert result.confidence == 1.0


def test_parse_response_text_before_xml_block(pppoe_run):
    """Claude sometimes adds a brief note before the XML — parser must handle it."""
    prefixed = "Here is my triage analysis:\n\n" + GOOD_RESPONSE
    result = _parse_response(pppoe_run, _make_mock_response(prefixed))
    assert result.severity == Severity.CRITICAL


# ── End-to-end mock test ──────────────────────────────────────────────────────

@patch("core.triage_engine.anthropic.Anthropic")
def test_analyse_end_to_end(mock_anthropic_cls, pppoe_run):
    """Full analyse() call with a mocked Anthropic client."""
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(GOOD_RESPONSE)

    result = analyse(pppoe_run)

    assert result.severity == Severity.CRITICAL
    assert result.confidence > 0.9
    assert len(result.recommendations) == 2
    assert result.claude_model == "claude-sonnet-4-20250514"
    mock_client.messages.create.assert_called_once()

    # Verify the call used the right model and max_tokens
    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-sonnet-4-20250514"
    assert call_kwargs["max_tokens"] == 4096
