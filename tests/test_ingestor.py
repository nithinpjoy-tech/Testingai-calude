"""
tests/test_ingestor.py — ingestor unit tests.
Tests format detection, JSON/XML parsing, extra_context population.
"""
import pytest
from pathlib import Path
from core.ingestor import ingest
from core.models import Verdict


SAMPLE_JSON = Path("samples/pppoe_vlan_mismatch.json")
SAMPLE_XML  = Path("samples/pppoe_vlan_mismatch.xml")


def test_ingest_json_verdict():
    run = ingest(str(SAMPLE_JSON))
    assert run.verdict == Verdict.FAIL

def test_ingest_json_dut():
    run = ingest(str(SAMPLE_JSON))
    assert run.dut.vendor == "NetComm"
    assert run.dut.model  == "NF18ACV"
    assert run.dut.access_technology == "FTTP"

def test_ingest_json_metrics():
    run = ingest(str(SAMPLE_JSON))
    assert len(run.metrics) == 3
    failed = [m for m in run.metrics if m.verdict == Verdict.FAIL]
    assert len(failed) == 3

def test_ingest_json_logs():
    run = ingest(str(SAMPLE_JSON))
    assert len(run.error_logs) == 7
    joined = "\n".join(run.error_logs)
    assert "PADO" in joined
    assert "S-VLAN" in joined or "sv-vlan" in joined.lower() or "VLAN" in joined

def test_ingest_json_extra_context():
    run = ingest(str(SAMPLE_JSON))
    assert "config_snapshot" in run.extra_context
    assert "failure_summary" in run.extra_context
    assert run.extra_context["config_snapshot"]["ntd"]["interface_wan0_vlan"] == 10

def test_ingest_xml_verdict():
    run = ingest(str(SAMPLE_XML))
    assert run.verdict == Verdict.FAIL

def test_ingest_xml_dut():
    run = ingest(str(SAMPLE_XML))
    assert run.dut.model == "NF18ACV"

def test_ingest_xml_logs():
    run = ingest(str(SAMPLE_XML))
    assert len(run.error_logs) == 7

def test_ingest_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        ingest("no_such_file.json")

def test_ingest_unsupported_format_raises(tmp_path):
    f = tmp_path / "result.csv"
    f.write_text("a,b,c")
    with pytest.raises(ValueError, match="Unsupported"):
        ingest(str(f))
