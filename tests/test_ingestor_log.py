"""
tests/test_ingestor_log.py — raw log ingestion tests.
"""
from pathlib import Path
import pytest
from core.ingestor import ingest
from core.models import Verdict

SAMPLE_LOG = Path("samples/pppoe_vlan_mismatch.log")

def test_log_exists():
    assert SAMPLE_LOG.exists()

def test_ingest_log_verdict():
    run = ingest(str(SAMPLE_LOG))
    assert run.verdict == Verdict.FAIL

def test_ingest_log_dut_fields():
    run = ingest(str(SAMPLE_LOG))
    assert run.dut.vendor == "NetComm"
    assert run.dut.model  == "NF18ACV"
    assert run.dut.firmware == "3.7.2-r4"
    assert run.dut.device_id == "NF18ACV-19A4-002871"

def test_ingest_log_has_events():
    run = ingest(str(SAMPLE_LOG))
    assert len(run.error_logs) > 5

def test_ingest_log_detects_vlan_in_extra_context():
    run = ingest(str(SAMPLE_LOG))
    snap = run.extra_context.get("config_snapshot", {})
    # Should extract VLAN 10 from log
    ntd_vlan = snap.get("ntd", {}).get("interface_wan0_vlan")
    assert ntd_vlan == 10

def test_ingest_log_failure_summary():
    run = ingest(str(SAMPLE_LOG))
    summary = run.extra_context.get("failure_summary", "")
    assert len(summary) > 0

def test_ingest_log_format_field():
    run = ingest(str(SAMPLE_LOG))
    assert run.raw_input_format == "log"

def test_ingest_log_has_run_id():
    run = ingest(str(SAMPLE_LOG))
    assert run.run_id and len(run.run_id) > 0
