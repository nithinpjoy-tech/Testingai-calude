"""
tests/test_remediation.py
--------------------------
Unit tests for remediation.py — all Claude API calls mocked.
"""
from __future__ import annotations
import textwrap
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.models import (
    DeviceUnderTest, ExecutionMode, FixStep, Recommendation,
    Severity, StepStatus, TestRun, TriageResult, Verdict,
)
from core.remediation import (
    _build_remediation_prompt, _parse_fix_script, _system_prompt, generate_fix_script,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def pppoe_run() -> TestRun:
    return TestRun(
        run_id="run-rem-001", test_case_id="TC_PPPOE_FTTP_001",
        test_case_name="PPPoE session establishment on FTTP NTD (nbn 100/40)",
        timestamp=datetime(2026, 4, 28, 3, 14, 21),
        verdict=Verdict.FAIL,
        dut=DeviceUnderTest(
            device_id="NF18ACV-19A4-002871", vendor="NetComm",
            model="NF18ACV", firmware="3.7.2-r4",
            access_technology="FTTP", management_ip="192.168.100.1",
        ),
        topology_summary="NTD wan0 -- OLT g-1/0/3 -- BNG (POI-Sydney)",
        extra_context={
            "config_snapshot": {
                "ntd": {"interface_wan0_vlan": 10, "pppoe_client": "enabled"},
                "olt_port": {"service_vlan": 2, "service_profile": "NBN-RES-100-40"},
            },
            "test_parameters": {"expected_service_vlan": 2},
            "speed_tier": "100/40",
        },
    )

@pytest.fixture
def vlan_triage() -> TriageResult:
    return TriageResult(
        run_id="run-rem-001",
        severity=Severity.CRITICAL,
        root_cause_summary="NTD wan0 tagged VLAN 10 but OLT service profile expects VLAN 2.",
        root_cause_detail="Config shows ntd.interface_wan0_vlan=10 vs olt_port.service_vlan=2.",
        confidence=0.97,
        recommendations=[
            Recommendation(
                priority=1,
                action="Change NTD wan0 vlan-id from 10 to 2",
                rationale="Aligns C-VLAN with OLT S-VLAN translation rule",
                estimated_effort="2 min",
            ),
        ],
        claude_model="claude-sonnet-4-20250514",
    )


GOOD_FIX_XML = textwrap.dedent("""\
    <fix_script>
      <title>Correct wan0 VLAN mismatch on NF18ACV — VLAN 10 to 2</title>
      <pre_checks>
        <check>ping 192.168.100.1</check>
        <check>show interface wan0 config</check>
      </pre_checks>
      <steps>
        <step number="1">
          <description>Read current wan0 VLAN configuration</description>
          <command>show interface wan0 config</command>
          <expected_output>vlan-id</expected_output>
          <post_check>show interface wan0 status</post_check>
          <rollback>echo no-rollback-needed</rollback>
        </step>
        <step number="2">
          <description>Change wan0 VLAN from 10 to 2 (NBN service VLAN for 100/40)</description>
          <command>set interface wan0 vlan-id 2</command>
          <pre_check>show interface wan0 config</pre_check>
          <expected_output>vlan-id changed</expected_output>
          <post_check>show interface wan0 config</post_check>
          <rollback>set interface wan0 vlan-id 10</rollback>
        </step>
        <step number="3">
          <description>Commit the VLAN change and verify PPPoE session establishes</description>
          <command>commit</command>
          <expected_output>lcp-up</expected_output>
          <post_check>show pppoe status</post_check>
          <rollback>set interface wan0 vlan-id 10 ; commit</rollback>
        </step>
      </steps>
      <post_checks>
        <check>show pppoe status</check>
        <check>show dhcp client status</check>
      </post_checks>
    </fix_script>
""")


def _mock_response(xml: str) -> MagicMock:
    block = MagicMock(); block.type = "text"; block.text = xml
    usage = MagicMock(); usage.input_tokens = 420; usage.output_tokens = 310
    resp  = MagicMock(); resp.content = [block]; resp.usage = usage
    return resp


# ── System prompt tests ───────────────────────────────────────────────────────

def test_system_prompt_contains_vendor(pppoe_run):
    sp = _system_prompt(pppoe_run)
    assert "NetComm" in sp
    assert "NF18ACV" in sp
    assert "3.7.2-r4" in sp

def test_system_prompt_contains_rules(pppoe_run):
    sp = _system_prompt(pppoe_run)
    for rule in ["IDEMPOTENT", "ROLLBACK", "MINIMAL", "ORDERED"]:
        assert rule in sp, f"System prompt missing rule '{rule}'"

def test_system_prompt_contains_xml_schema(pppoe_run):
    sp = _system_prompt(pppoe_run)
    assert "<fix_script>" in sp
    assert "<step number=" in sp
    assert "<rollback>" in sp


# ── Prompt builder tests ──────────────────────────────────────────────────────

def test_build_prompt_contains_root_cause(pppoe_run, vlan_triage):
    prompt = _build_remediation_prompt(pppoe_run, vlan_triage)
    assert "VLAN 10" in prompt
    assert "VLAN 2" in prompt
    assert "CRITICAL" in prompt

def test_build_prompt_contains_config_snapshot(pppoe_run, vlan_triage):
    prompt = _build_remediation_prompt(pppoe_run, vlan_triage)
    assert "interface_wan0_vlan" in prompt
    assert "service_vlan" in prompt

def test_build_prompt_contains_device_info(pppoe_run, vlan_triage):
    prompt = _build_remediation_prompt(pppoe_run, vlan_triage)
    assert "NetComm" in prompt
    assert "NF18ACV" in prompt

def test_build_prompt_contains_recommendation(pppoe_run, vlan_triage):
    prompt = _build_remediation_prompt(pppoe_run, vlan_triage)
    assert "Change NTD wan0 vlan-id" in prompt


# ── Parser tests ──────────────────────────────────────────────────────────────

def test_parse_fix_script_returns_fix_script(pppoe_run):
    script = _parse_fix_script(pppoe_run, _mock_response(GOOD_FIX_XML))
    assert script.run_id == "run-rem-001"
    assert "VLAN" in script.title
    assert len(script.steps) == 3
    assert len(script.pre_checks) == 2
    assert len(script.post_checks) == 2

def test_parse_fix_script_steps_ordered(pppoe_run):
    script = _parse_fix_script(pppoe_run, _mock_response(GOOD_FIX_XML))
    nums = [s.step_number for s in script.steps]
    assert nums == sorted(nums)

def test_parse_fix_script_step_fields(pppoe_run):
    script = _parse_fix_script(pppoe_run, _mock_response(GOOD_FIX_XML))
    s2 = script.steps[1]   # step number 2
    assert s2.command == "set interface wan0 vlan-id 2"
    assert s2.rollback_command == "set interface wan0 vlan-id 10"
    assert s2.pre_check == "show interface wan0 config"
    assert s2.post_check == "show interface wan0 config"
    assert s2.status == StepStatus.PENDING

def test_parse_fix_script_execution_mode(pppoe_run):
    script = _parse_fix_script(pppoe_run, _mock_response(GOOD_FIX_XML))
    assert script.execution_mode == ExecutionMode.SIMULATED

def test_parse_no_fix_script_block_raises(pppoe_run):
    with pytest.raises(ValueError, match="<fix_script>"):
        _parse_fix_script(pppoe_run, _mock_response("I cannot generate a fix script."))

def test_parse_empty_steps_raises(pppoe_run):
    empty = "<fix_script><title>Empty</title><steps></steps></fix_script>"
    with pytest.raises(ValueError, match="no <step>"):
        _parse_fix_script(pppoe_run, _mock_response(empty))

def test_parse_with_preamble(pppoe_run):
    prefixed = "Here is the fix script:\n\n" + GOOD_FIX_XML
    script = _parse_fix_script(pppoe_run, _mock_response(prefixed))
    assert len(script.steps) == 3


# ── End-to-end mock test ──────────────────────────────────────────────────────

@patch("core.remediation.anthropic.Anthropic")
def test_generate_fix_script_e2e(mock_cls, pppoe_run, vlan_triage):
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = _mock_response(GOOD_FIX_XML)

    script = generate_fix_script(pppoe_run, vlan_triage)

    assert script.run_id == "run-rem-001"
    assert len(script.steps) == 3
    assert script.steps[0].status == StepStatus.PENDING
    assert script.approved_by is None   # not yet approved
    mock_client.messages.create.assert_called_once()
    call_kw = mock_client.messages.create.call_args[1]
    assert call_kw["model"] == "claude-sonnet-4-20250514"
