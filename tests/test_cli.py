"""
tests/test_cli.py — CLI command tests using Click's CliRunner.
All Claude API calls and DB interactions mocked.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli
from core.models import (
    DeviceUnderTest, ExecutionMode, FixScript, FixStep,
    Recommendation, RunRecord, RunStatus, Severity, StepStatus,
    TestMetric, TestRun, TriageResult, Verdict,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def sample_json():
    return str(Path("samples/pppoe_vlan_mismatch.json").resolve())

@pytest.fixture
def sample_xml():
    return str(Path("samples/pppoe_vlan_mismatch.xml").resolve())

@pytest.fixture
def mock_run() -> TestRun:
    return TestRun(
        run_id="run-cli-001", test_case_id="TC001",
        test_case_name="PPPoE test", timestamp=datetime(2026,4,28),
        verdict=Verdict.FAIL,
        dut=DeviceUnderTest(device_id="d1", vendor="NetComm",
                            model="NF18ACV", firmware="3.7.2",
                            access_technology="FTTP"),
        metrics=[TestMetric(name="pppoe_state", expected="lcp-up",
                            measured="timeout", verdict=Verdict.FAIL)],
        error_logs=["[2026-04-28] ERROR ntd: PPPoE failed"],
        extra_context={"config_snapshot": {"ntd": {"interface_wan0_vlan": 10}}},
    )

@pytest.fixture
def mock_triage() -> TriageResult:
    return TriageResult(
        run_id="run-cli-001", severity=Severity.CRITICAL,
        root_cause_summary="VLAN mismatch: NTD=10 vs OLT=2",
        root_cause_detail="Detail here.", confidence=0.97,
        recommendations=[Recommendation(priority=1,
            action="Set wan0 vlan-id to 2",
            rationale="Aligns C-VLAN", estimated_effort="2 min")],
        claude_model="claude-sonnet-4-20250514",
    )

@pytest.fixture
def mock_script(mock_run) -> FixScript:
    script = FixScript(
        run_id="run-cli-001", title="Fix VLAN mismatch",
        steps=[
            FixStep(step_number=1, description="Read config",
                    command="show interface wan0 config", expected_output="vlan-id"),
            FixStep(step_number=2, description="Fix VLAN",
                    command="set interface wan0 vlan-id 2",
                    rollback_command="set interface wan0 vlan-id 10"),
            FixStep(step_number=3, description="Commit",
                    command="commit", expected_output="lcp-up",
                    rollback_command="set interface wan0 vlan-id 10 ; commit"),
        ],
        pre_checks=["ping 192.168.100.1"],
        post_checks=["show pppoe status"],
        execution_mode=ExecutionMode.SIMULATED,
        approved_by="test-operator",
        approved_at=datetime.utcnow(),
    )
    return script

@pytest.fixture
def mock_run_records():
    return [
        RunRecord(id="aaaa-0001", test_case="TC_PPPOE_001",
                  verdict=Verdict.FAIL, status=RunStatus.TRIAGED,
                  severity=Severity.CRITICAL, root_cause="VLAN mismatch",
                  created_at=datetime(2026,4,28,3,14)),
        RunRecord(id="bbbb-0002", test_case="TC_PPPOE_002",
                  verdict=Verdict.PASS, status=RunStatus.REPORTED,
                  severity=Severity.LOW, created_at=datetime(2026,4,27)),
    ]


# ── analyse --no-exec ─────────────────────────────────────────────────────────

@patch("core.ingestor.ingest")
@patch("core.triage_engine.analyse")
@patch("db.store.init_db")
@patch("db.store.upsert_run")
def test_analyse_no_exec(mock_upsert, mock_init, mock_triage_fn, mock_ingest,
                         runner, sample_json, mock_run, mock_triage):
    mock_ingest.return_value   = mock_run
    mock_triage_fn.return_value = mock_triage  # noqa

    result = runner.invoke(cli, ["analyse", sample_json, "--no-exec"])

    assert result.exit_code == 0, result.output
    assert "CRIT" in result.output or "TC_PPPOE" in result.output
    assert "VLAN mismatch" in result.output
    mock_ingest.assert_called_once()
    mock_triage_fn.assert_called_once()


@patch("core.ingestor.ingest")
@patch("core.triage_engine.analyse")
@patch("db.store.init_db")
@patch("db.store.upsert_run")
def test_analyse_no_exec_xml(mock_upsert, mock_init, mock_triage_fn, mock_ingest,
                              runner, sample_xml, mock_run, mock_triage):
    mock_ingest.return_value    = mock_run
    mock_triage_fn.return_value = mock_triage  # noqa
    result = runner.invoke(cli, ["analyse", sample_xml, "--no-exec"])
    assert result.exit_code == 0, result.output
    assert "PPPoE" in result.output


# ── analyse with execution ────────────────────────────────────────────────────

@patch("core.ingestor.ingest")
@patch("core.triage_engine.analyse")
@patch("core.remediation.generate_fix_script")
@patch("core.executor.execute")
@patch("core.executor.reset_simulated_ntd")
@patch("db.store.init_db")
@patch("db.store.upsert_run")
def test_analyse_approve_flag(mock_upsert, mock_init, mock_reset, mock_exec,
                               mock_gen, mock_triage_fn, mock_ingest,
                               runner, sample_json, mock_run, mock_triage, mock_script):
    mock_ingest.return_value   = mock_run
    mock_triage_fn.return_value = mock_triage  # noqa
    mock_gen.return_value      = mock_script

    # simulate 3 passed steps
    results = []
    for step in mock_script.steps:
        from core.executor import StepResult
        step.status = StepStatus.PASSED
        step.actual_output = "OK"
        sr = StepResult(step=step, status=StepStatus.PASSED, stdout="OK")
        results.append(sr)
    mock_exec.return_value = iter(results)

    result = runner.invoke(cli, ["analyse", sample_json, "--approve", "--operator", "alice"])
    assert result.exit_code == 0, result.output
    assert "Approved by" in result.output or "alice" in result.output


# ── history ───────────────────────────────────────────────────────────────────

@patch("db.store.init_db")
@patch("db.store.list_runs")
def test_history_shows_runs(mock_list, mock_init, runner, mock_run_records):
    mock_list.return_value = mock_run_records
    result = runner.invoke(cli, ["history", "--limit", "10"])
    assert result.exit_code == 0, result.output
    assert "TC_PPPOE_001" in result.output
    assert "CRIT" in result.output or "TC_PPPOE" in result.output

@patch("db.store.init_db")
@patch("db.store.list_runs")
def test_history_empty(mock_list, mock_init, runner):
    mock_list.return_value = []
    result = runner.invoke(cli, ["history"])
    assert result.exit_code == 0
    assert "No runs" in result.output

@patch("db.store.init_db")
@patch("db.store.list_runs")
def test_history_verdict_filter(mock_list, mock_init, runner, mock_run_records):
    mock_list.return_value = mock_run_records
    result = runner.invoke(cli, ["history", "--verdict", "FAIL"])
    assert result.exit_code == 0
    assert "TC_PPPOE_001" in result.output
    assert "TC_PPPOE_002" not in result.output


# ── compare ───────────────────────────────────────────────────────────────────

def _make_report_json(run_id: str, test_case: str, verdict: str, sev: str) -> str:
    return json.dumps({
        "run_id": run_id,
        "test_run": {"test_case_name": test_case, "verdict": verdict, "metrics": [
            {"name": "pppoe_state", "measured": "timeout", "verdict": "FAIL"},
        ]},
        "triage": {"severity": sev, "confidence": 0.9,
                   "root_cause_summary": f"Root cause for {run_id}"},
    })

@patch("db.store.init_db")
@patch("db.store.get_report_json")
def test_compare_two_runs(mock_get, mock_init, runner):
    mock_get.side_effect = lambda rid: _make_report_json(
        rid, f"Test {rid[:4]}", "FAIL", "CRITICAL"
    )
    result = runner.invoke(cli, ["compare", "run-aaa", "run-bbb"])
    assert result.exit_code == 0, result.output
    assert "Comparison" in result.output or "Root cause" in result.output

@patch("db.store.init_db")
@patch("db.store.get_report_json")
def test_compare_missing_run(mock_get, mock_init, runner):
    mock_get.return_value = None
    result = runner.invoke(cli, ["compare", "run-aaa", "run-bbb"])
    assert result.exit_code != 0 or "not found" in result.output.lower()


# ── replay ────────────────────────────────────────────────────────────────────

@patch("db.store.init_db")
@patch("db.store.get_report_json")
def test_replay_run(mock_get, mock_init, runner):
    report = {
        "test_run": {"test_case_name": "PPPoE test", "verdict": "FAIL"},
        "triage":   {"root_cause_summary": "VLAN mismatch"},
        "execution": {"steps": [
            {"step_number": 1, "description": "Read config",
             "command": "show interface wan0 config",
             "status": "passed", "actual_output": "vlan-id : 10"},
            {"step_number": 2, "description": "Fix VLAN",
             "command": "set interface wan0 vlan-id 2",
             "status": "passed", "actual_output": "OK"},
        ]},
    }
    mock_get.return_value = json.dumps(report)
    result = runner.invoke(cli, ["replay", "run-aaa", "--speed", "0"])
    assert result.exit_code == 0, result.output
    assert "Step 1" in result.output
    assert "Step 2" in result.output
    assert "passed" in result.output.lower() or "✅" in result.output

@patch("db.store.init_db")
@patch("db.store.get_report_json")
def test_replay_missing_run(mock_get, mock_init, runner):
    mock_get.return_value = None
    result = runner.invoke(cli, ["replay", "no-such-run"])
    assert result.exit_code != 0 or "No report" in result.output
