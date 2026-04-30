"""
core/reporter.py
----------------
Assembles a RunReport from all pipeline components and persists it.

TODO (Step 6): implement to_markdown() for human-readable output
TODO (Step 6): implement to_pdf() for formal reports
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import ExecutionResult, FixScript, RunRecord, RunReport, RunStatus, TestRun, TriageResult

logger = logging.getLogger(__name__)


def build_report(
    run:       TestRun,
    triage:    TriageResult,
    script:    FixScript | None = None,
    execution: ExecutionResult | None = None,
    notified:  list[str] | None = None,
) -> RunReport:
    """Assemble and return a RunReport. Does not persist — call save() separately."""
    return RunReport(
        run_id              = run.run_id,
        generated_at        = datetime.now(timezone.utc),
        test_run            = run,
        triage              = triage,
        fix_script          = script,
        execution           = execution,
        notifications_sent  = notified or [],
    )


def save(report: RunReport, runs_dir: str = "data/runs") -> Path:
    """Persist report as JSON to the runs directory. Returns the file path."""
    out_dir = Path(runs_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report.run_id}.json"
    out_path.write_text(report.model_dump_json(indent=2))
    logger.info("Report saved: %s", out_path)
    return out_path


def to_run_record(report: RunReport) -> RunRecord:
    """Lightweight DB row derived from a full report."""
    status = RunStatus.INGESTED
    if report.execution:
        status = RunStatus.EXECUTED
    elif report.fix_script:
        status = RunStatus.SCRIPTED
    elif report.triage:
        status = RunStatus.TRIAGED

    return RunRecord(
        id          = report.run_id,
        created_at  = report.generated_at,
        source_file = report.test_run.raw_input_path,
        test_case   = report.test_run.test_case_name,
        verdict     = report.test_run.verdict,
        status      = status,
        root_cause  = report.triage.root_cause_summary if report.triage else None,
        severity    = report.triage.severity if report.triage else None,
    )


def to_markdown(report: RunReport) -> str:
    """Human-readable report. TODO (Step 6): full implementation."""
    raise NotImplementedError("to_markdown: implement in Step 6")
