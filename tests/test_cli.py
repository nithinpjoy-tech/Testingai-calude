import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from datetime import datetime

from cli.main import cli
from core.models import TestRun, DeviceUnderTest, Verdict, TriageResult, Severity, FixScript, FixStep, ExecutionMode, StepStatus

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def mock_run():
    return TestRun(
        run_id="run-123",
        test_case_id="tc-1",
        test_case_name="test",
        timestamp=datetime.utcnow(),
        verdict=Verdict.FAIL,
        dut=DeviceUnderTest(
            device_id="d1",
            vendor="v1",
            model="m1",
            firmware="f1",
            access_technology="FTTP"
        )
    )

@pytest.fixture
def mock_triage():
    return TriageResult(
        run_id="run-123",
        severity=Severity.HIGH,
        root_cause_summary="Bad config",
        root_cause_detail="Details...",
        confidence=0.9,
        claude_model="claude"
    )

@pytest.fixture
def mock_script():
    return FixScript(
        run_id="run-123",
        title="Fix",
        steps=[FixStep(step_number=1, description="Do this", command="echo 1")]
    )

@patch("core.ingestor.ingest")
@patch("core.triage_engine.analyse")
@patch("core.remediation.generate_fix_script")
@patch("core.executor.execute")
@patch("core.reporter.save")
@patch("db.store.upsert_run")
@patch("db.store.init_db")
def test_analyse_dry_run_approve(mock_init_db, mock_upsert, mock_save, mock_execute, mock_generate, mock_triage_engine, mock_ingest, runner, mock_run, mock_triage, mock_script):
    mock_ingest.return_value = mock_run
    mock_triage_engine.return_value = mock_triage
    mock_generate.return_value = mock_script
    
    step_result = mock_script.steps[0].model_copy()
    step_result.status = StepStatus.PASSED
    mock_execute.return_value = [step_result]
    
    with runner.isolated_filesystem():
        with open("test.json", "w") as f:
            f.write("{}")
        
        result = runner.invoke(cli, ["analyse", "test.json", "--approve"])
        
    assert result.exit_code == 0
    assert "Ingesting test.json" in result.output
    assert "Root cause: Bad config" in result.output
    assert "Step 1: passed" in result.output

@patch("core.ingestor.ingest")
@patch("core.triage_engine.analyse")
def test_analyse_no_exec(mock_triage_engine, mock_ingest, runner, mock_run, mock_triage):
    mock_ingest.return_value = mock_run
    mock_triage_engine.return_value = mock_triage
    
    with runner.isolated_filesystem():
        with open("test.json", "w") as f:
            f.write("{}")
            
        result = runner.invoke(cli, ["analyse", "test.json", "--no-exec"])
        
    assert result.exit_code == 0
    assert "--no-exec set" in result.output
    assert "Generating fix script" not in result.output
