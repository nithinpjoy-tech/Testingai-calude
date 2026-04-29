"""
Pydantic domain models — single source of truth for all data structures.
Schema approved in milestone planning. Do not change without versioning.
"""
from __future__ import annotations
from enum import Enum
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    INCONCLUSIVE = "INCONCLUSIVE"

class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

class ExecutionMode(str, Enum):
    SIMULATED = "simulated"
    LIVE = "live"

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── Test Input Schema (approved as-is) ───────────────────────────────────────

class DeviceUnderTest(BaseModel):
    device_id: str
    vendor: str
    model: str
    firmware: str
    access_technology: str           # FTTP | FTTN | HFC | FTTC | FW | SATL
    management_ip: str | None = None
    location: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

class TestMetric(BaseModel):
    name: str
    expected: Any
    measured: Any
    unit: str | None = None
    verdict: Verdict
    tolerance: str | None = None

class TestRun(BaseModel):
    """Normalised test result — ingested from JSON, XML, or raw log."""
    run_id: str
    test_case_id: str
    test_case_name: str
    timestamp: datetime
    verdict: Verdict
    severity: Severity | None = None   # derived by triage engine
    dut: DeviceUnderTest
    topology_summary: str | None = None
    metrics: list[TestMetric] = Field(default_factory=list)
    error_logs: list[str] = Field(default_factory=list)
    raw_input_format: str = "json"     # json | xml | log
    raw_input_path: str | None = None
    extra_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Carries format-specific fields not in the standard schema: "
                    "config_snapshot, failure_summary, speed_tier, pre_conditions, etc."
    )


# ── Triage Output ─────────────────────────────────────────────────────────────

class Recommendation(BaseModel):
    priority: int                      # 1 = highest
    action: str
    rationale: str
    estimated_effort: str | None = None  # e.g. "5 min", "config change only"

class TriageResult(BaseModel):
    run_id: str
    severity: Severity
    root_cause_summary: str
    root_cause_detail: str
    confidence: float = Field(ge=0.0, le=1.0)
    recommendations: list[Recommendation] = Field(default_factory=list)
    claude_model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    triage_timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Remediation / Fix Script ──────────────────────────────────────────────────

class FixStep(BaseModel):
    step_number: int
    description: str
    command: str                       # CLI / shell command to execute
    expected_output: str | None = None # substring to assert in actual output
    pre_check: str | None = None       # command to run before step; must exit 0
    post_check: str | None = None      # command to run after step; must exit 0
    rollback_command: str | None = None
    status: StepStatus = StepStatus.PENDING
    actual_output: str | None = None
    pre_check_output: str | None = None
    post_check_output: str | None = None
    exit_code: int | None = None

class FixScript(BaseModel):
    run_id: str
    title: str
    pre_checks: list[str] = Field(default_factory=list)
    steps: list[FixStep] = Field(default_factory=list)
    post_checks: list[str] = Field(default_factory=list)
    approved_by: str | None = None
    approved_at: datetime | None = None
    execution_mode: ExecutionMode = ExecutionMode.SIMULATED


# ── Execution Result ──────────────────────────────────────────────────────────

class ExecutionResult(BaseModel):
    run_id: str
    fix_script_title: str
    started_at: datetime
    completed_at: datetime | None = None
    overall_status: StepStatus = StepStatus.PENDING
    steps: list[FixStep] = Field(default_factory=list)
    execution_mode: ExecutionMode
    operator: str | None = None


# ── Run Report ────────────────────────────────────────────────────────────────

class RunReport(BaseModel):
    run_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    test_run: TestRun
    triage: TriageResult
    fix_script: FixScript | None = None
    execution: ExecutionResult | None = None
    notifications_sent: list[str] = Field(default_factory=list)


# ── DB Lightweight Row (run history) ─────────────────────────────────────────

class RunStatus(str, Enum):
    """Lifecycle status of a run in the DB (separate from test Verdict)."""
    INGESTED   = "ingested"
    TRIAGED    = "triaged"
    SCRIPTED   = "scripted"
    APPROVED   = "approved"
    EXECUTED   = "executed"
    REPORTED   = "reported"

class RunRecord(BaseModel):
    """Lightweight row stored in SQLite — not the full RunReport graph."""
    id:          str
    created_at:  datetime = Field(default_factory=datetime.utcnow)
    source_file: str | None = None
    test_case:   str
    verdict:     Verdict
    status:      RunStatus = RunStatus.INGESTED
    root_cause:  str | None = None
    severity:    Severity | None = None


# ── Chat models ────────────────────────────────────────────────────────────────

class ChatRole(str, Enum):
    SYSTEM    = "system"
    USER      = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """A single turn in the mid-triage chat sidebar."""
    role:      ChatRole
    content:   str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatSession(BaseModel):
    """All state for one operator conversation tied to a specific run."""
    run_id:   str
    messages: list[ChatMessage] = []

    def add(self, role: ChatRole, content: str) -> "ChatMessage":
        msg = ChatMessage(role=role, content=content)
        self.messages.append(msg)
        return msg

    def to_api_messages(self) -> list[dict[str, str]]:
        """Return message list in the shape Anthropic's API expects."""
        return [
            {"role": m.role.value, "content": m.content}
            for m in self.messages
            if m.role != ChatRole.SYSTEM
        ]
