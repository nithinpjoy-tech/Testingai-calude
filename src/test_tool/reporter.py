"""Verdict reporter — produces a downloadable end-to-end report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .models import ExecutionReport, TestRun, TriageResult


def build_report(run: TestRun, triage: TriageResult, execution: ExecutionReport) -> dict[str, Any]:
    """Combined human-readable report (also serialises cleanly to JSON)."""
    return {
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "test": {
            "id": run.test_id,
            "name": run.test_name,
            "access_technology": run.access_technology.value,
            "speed_tier": run.speed_tier,
            "original_verdict": run.verdict.value,
            "failure_summary": run.failure_summary,
        },
        "diagnosis": triage.diagnosis.model_dump(),
        "recommendations": [r.model_dump() for r in triage.recommendations],
        "fix_script": {
            "description": triage.fix_script.description,
            "step_count": len(triage.fix_script.steps),
            "rollback_step_count": len(triage.fix_script.rollback_steps),
            "service_impact": triage.fix_script.requires_service_impact,
        },
        "execution": {
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
            "overall_status": execution.overall_status.value,
            "rollback_executed": execution.rollback_executed,
            "final_verdict": execution.final_verdict.value,
            "steps": [s.model_dump() for s in execution.step_results],
        },
    }


def report_to_json(run: TestRun, triage: TriageResult, execution: ExecutionReport) -> str:
    return json.dumps(build_report(run, triage, execution), indent=2, default=str)