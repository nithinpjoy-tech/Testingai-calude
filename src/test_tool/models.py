"""Canonical data models for theTest Tool.

Every parser converts a raw input file into a `TestRun`. The triage engine
returns a `TriageResult`. The executor returns an `ExecutionReport`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Test input domain
# ---------------------------------------------------------------------------


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    INCONCLUSIVE = "INCONCLUSIVE"


class Severity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


class AccessTechnology(str, Enum):
    FTTP = "FTTP"
    FTTN = "FTTN"
    FTTC = "FTTC"
    HFC = "HFC"
    FIXED_WIRELESS = "FIXED_WIRELESS"
    SKY_MUSTER = "SKY_MUSTER"
    UNKNOWN = "UNKNOWN"


class DUT(BaseModel):
    """Device Under Test."""

    role: str = Field(..., description="e.g. NTD, OLT, DPU, BNG, RG")
    vendor: Optional[str] = None
    model: Optional[str] = None
    firmware: Optional[str] = None
    serial: Optional[str] = None
    mgmt_address: Optional[str] = None


class Metric(BaseModel):
    """A measured metric with its expected vs actual."""

    name: str
    expected: Any | None = None
    actual: Any | None = None
    unit: Optional[str] = None
    tolerance: Optional[str] = None
    passed: Optional[bool] = None


class LogEvent(BaseModel):
    timestamp: Optional[datetime] = None
    severity: Severity = Severity.INFO
    source: Optional[str] = None
    message: str


class TestRun(BaseModel):
    """The canonical normalised representation of a single test execution."""

    test_id: str
    test_name: str
    description: Optional[str] = None
    run_timestamp: Optional[datetime] = None
    build_version: Optional[str] = None
    access_technology: AccessTechnology = AccessTechnology.UNKNOWN
    speed_tier: Optional[str] = Field(None, description='e.g. "100/40", "250/25"')

    duts: list[DUT] = Field(default_factory=list)
    topology: Optional[str] = Field(None, description="Free text or simple notation")
    pre_conditions: list[str] = Field(default_factory=list)
    test_parameters: dict[str, Any] = Field(default_factory=dict)
    pass_criteria: list[Metric] = Field(default_factory=list)
    measurements: list[Metric] = Field(default_factory=list)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    log_events: list[LogEvent] = Field(default_factory=list)

    verdict: Verdict = Verdict.INCONCLUSIVE
    failure_summary: Optional[str] = None
    raw_input_format: Optional[str] = None  # set by parser: json|xml|yaml


# ---------------------------------------------------------------------------
# LLM triage output domain
# ---------------------------------------------------------------------------


class FailureCategory(str, Enum):
    CONFIGURATION = "configuration"
    HARDWARE = "hardware"
    PROTOCOL = "protocol"
    CAPACITY = "capacity"
    ENVIRONMENTAL = "environmental"
    SOFTWARE = "software"
    OTHER = "other"


class Diagnosis(BaseModel):
    summary: str = Field(..., description="One-line headline of the failure")
    root_cause: str = Field(..., description="Detailed root-cause statement")
    evidence: list[str] = Field(
        default_factory=list,
        description="Concrete log timestamps / metric names that support the conclusion",
    )
    category: FailureCategory = FailureCategory.OTHER
    confidence: float = Field(..., ge=0.0, le=1.0)


class Recommendation(BaseModel):
    priority: int = Field(..., ge=1, description="1 = highest priority")
    action: str
    rationale: str


class StepType(str, Enum):
    PRE_CHECK = "pre_check"
    ACTION = "action"
    POST_CHECK = "post_check"


class FailureBehaviour(str, Enum):
    ABORT = "abort"
    CONTINUE = "continue"
    ROLLBACK = "rollback"


class FixStep(BaseModel):
    step_id: int
    name: str
    type: StepType
    command: str = Field(..., description="Exact CLI command to execute on the DUT")
    expected_pattern: Optional[str] = Field(
        None,
        description="Regex the response must match for the step to be considered successful",
    )
    on_failure: FailureBehaviour = FailureBehaviour.ABORT
    notes: Optional[str] = None


class FixScript(BaseModel):
    description: str
    estimated_duration_seconds: int = Field(default=60, ge=1)
    requires_service_impact: bool = False
    target_dut_role: str = Field(..., description="Which DUT role the script runs against, e.g. NTD")
    steps: list[FixStep]
    rollback_steps: list[FixStep] = Field(default_factory=list)


class TriageResult(BaseModel):
    """Full output of one GPT-4 triage call."""

    diagnosis: Diagnosis
    recommendations: list[Recommendation]
    fix_script: FixScript
    raw_llm_response: Optional[str] = None  # for demo transparency


# ---------------------------------------------------------------------------
# Executor domain
# ---------------------------------------------------------------------------


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepResult(BaseModel):
    step_id: int
    name: str
    type: StepType
    command: str
    status: StepStatus
    output: str = ""
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    matched_expected: Optional[bool] = None


class ExecutionReport(BaseModel):
    test_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    overall_status: StepStatus = StepStatus.PENDING
    step_results: list[StepResult] = Field(default_factory=list)
    rollback_executed: bool = False
    rollback_results: list[StepResult] = Field(default_factory=list)
    final_verdict: Verdict = Verdict.INCONCLUSIVE
    notes: Optional[str] = None