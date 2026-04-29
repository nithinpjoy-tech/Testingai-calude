"""Smoke tests — models parse correctly and DB round-trips. No LLM calls."""
import json
from datetime import datetime
from pathlib import Path
import pytest
from core.models import (
    DeviceUnderTest, ExecutionMode, FixScript, FixStep,
    RunRecord, RunStatus, Severity, StepStatus, TestMetric,
    TestRun, TriageResult, Verdict,
)

SAMPLE_JSON = Path("samples/pppoe_vlan_mismatch.json")

def test_sample_json_exists():
    assert SAMPLE_JSON.exists()

def test_ingestor_json():
    from core.ingestor import ingest
    run = ingest(str(SAMPLE_JSON))
    assert run.verdict == Verdict.FAIL
    assert run.dut.access_technology == "FTTP"
    assert len(run.error_logs) > 0

def test_ingestor_xml():
    from core.ingestor import ingest
    run = ingest("samples/pppoe_vlan_mismatch.xml")
    assert run.verdict == Verdict.FAIL

def test_fix_script_requires_approval():
    from core.executor import execute
    script = FixScript(
        run_id="test-123", title="Test",
        steps=[FixStep(step_number=1, description="ping", command="ping -c1 8.8.8.8")],
    )
    with pytest.raises(PermissionError):
        list(execute(script))

def test_db_round_trip(tmp_path, monkeypatch):
    import db.store as store
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    store.init_db()
    record = RunRecord(
        id="run-abc", test_case="TC_001", verdict=Verdict.FAIL,
        status=RunStatus.TRIAGED, severity=Severity.HIGH,
        root_cause="VLAN mismatch",
    )
    store.upsert_run(record)
    loaded = store.get_run("run-abc")
    assert loaded is not None
    assert loaded.severity == Severity.HIGH
