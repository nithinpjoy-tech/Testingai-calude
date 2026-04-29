"""Executor backends.

The simulated backend models an NBN NTD CLI. It is deterministic so the
demo is reliable. Switching to a real device for production means setting
EXECUTOR_BACKEND=ssh and implementing the SSHExecutor (stub provided).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import structlog

from .audit import AuditLog
from .config import ExecutorConfig
from .models import (
    ExecutionReport,
    FixScript,
    StepResult,
    StepStatus,
    StepType,
    Verdict,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------


class ExecutorBackend(ABC):
    """A backend that executes a single command string and returns its output."""

    @abstractmethod
    def execute(self, command: str) -> str: ...

    @abstractmethod
    def describe(self) -> str: ...


# ---------------------------------------------------------------------------
# Simulated NTD — scenario-driven
# ---------------------------------------------------------------------------


@dataclass
class SimulatedNTDState:
    """Mutable state of the simulated NTD. Modified by 'set' / 'restart' commands."""

    interface_vlan: dict[str, int] = field(default_factory=lambda: {"wan0": 10})
    interface_admin: dict[str, str] = field(default_factory=lambda: {"wan0": "up"})
    pppoe_state: str = "padi-sent"           # init|padi-sent|pado-recv|lcp-up|down
    pppoe_last_error: str = "no PADO received within 30s"
    pppoe_session_id: str = "-"
    dhcp_state: str = "no-lease"
    dhcp_ip: str = "-"
    expected_service_vlan: int = 2           # the OLT expects VLAN 2 for nbn 100/40
    saved: bool = False


class SimulatedNTDBackend(ExecutorBackend):
    """
    Implements the command grammar the system prompt advertises.
    Initial state reproduces the PPPoE VLAN-mismatch failure scenario.
    """

    def __init__(self, state: SimulatedNTDState | None = None):
        self.state = state or SimulatedNTDState()
        self._handlers: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
            (re.compile(r"^show\s+interface\s+(\S+)\s*$"), self._show_interface),
            (re.compile(r"^show\s+pppoe\s*$"), self._show_pppoe),
            (re.compile(r"^show\s+dhcp\s*$"), self._show_dhcp),
            (re.compile(r"^show\s+vlan\s*$"), self._show_vlan),
            (re.compile(r"^show\s+config\s*$"), self._show_config),
            (re.compile(r"^set\s+interface\s+(\S+)\s+vlan\s+(\d+)\s*$"), self._set_vlan),
            (re.compile(r"^set\s+interface\s+(\S+)\s+admin\s+(up|down)\s*$"), self._set_admin),
            (re.compile(r"^restart\s+pppoe\s*$"), self._restart_pppoe),
            (re.compile(r"^save\s+config\s*$"), self._save_config),
        ]

    def describe(self) -> str:
        return "simulated-ntd-v1"

    # --- public ---
    def execute(self, command: str) -> str:
        cmd = command.strip()
        for pattern, handler in self._handlers:
            m = pattern.match(cmd)
            if m:
                return handler(m)
        return f"% Unrecognised command: '{cmd}'"

    # --- handlers ---
    def _show_interface(self, m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in self.state.interface_vlan:
            return f"% No such interface: {name}"
        return (
            f"interface: {name}\n"
            f"  admin-status: {self.state.interface_admin.get(name, 'down')}\n"
            f"  oper-status:  {'up' if self.state.interface_admin.get(name) == 'up' else 'down'}\n"
            f"  vlan-id: {self.state.interface_vlan[name]}\n"
            f"  mac: 00:1e:c9:00:11:22\n"
        )

    def _show_pppoe(self, _: re.Match[str]) -> str:
        return (
            f"pppoe-session:\n"
            f"  state: {self.state.pppoe_state}\n"
            f"  session-id: {self.state.pppoe_session_id}\n"
            f"  last-error: {self.state.pppoe_last_error}\n"
        )

    def _show_dhcp(self, _: re.Match[str]) -> str:
        return (
            f"dhcp-client:\n"
            f"  state: {self.state.dhcp_state}\n"
            f"  ip-address: {self.state.dhcp_ip}\n"
        )

    def _show_vlan(self, _: re.Match[str]) -> str:
        lines = ["vlan-config:"]
        for name, vid in self.state.interface_vlan.items():
            lines.append(f"  {name}: vlan-id {vid}")
        return "\n".join(lines) + "\n"

    def _show_config(self, _: re.Match[str]) -> str:
        return (
            "running-config:\n"
            f"  interface wan0 vlan {self.state.interface_vlan.get('wan0')}\n"
            f"  interface wan0 admin {self.state.interface_admin.get('wan0')}\n"
            f"  pppoe-client enabled\n"
        )

    def _set_vlan(self, m: re.Match[str]) -> str:
        name, vid = m.group(1), int(m.group(2))
        self.state.interface_vlan[name] = vid
        # Reset session state when VLAN changes; PPPoE will re-trigger.
        self.state.pppoe_state = "init"
        self.state.dhcp_state = "no-lease"
        return f"OK: interface {name} vlan-id set to {vid}"

    def _set_admin(self, m: re.Match[str]) -> str:
        name, st = m.group(1), m.group(2)
        self.state.interface_admin[name] = st
        return f"OK: interface {name} admin {st}"

    def _restart_pppoe(self, _: re.Match[str]) -> str:
        # The crucial scenario logic: PPPoE comes up only when VLAN matches expected.
        if self.state.interface_vlan.get("wan0") == self.state.expected_service_vlan and \
           self.state.interface_admin.get("wan0") == "up":
            self.state.pppoe_state = "lcp-up"
            self.state.pppoe_session_id = "0x4e2"
            self.state.pppoe_last_error = "none"
            self.state.dhcp_state = "bound"
            self.state.dhcp_ip = "10.40.7.231/24"
            return "OK: pppoe restarted; session established (lcp-up)"
        self.state.pppoe_state = "padi-sent"
        self.state.pppoe_last_error = "no PADO received within 30s"
        self.state.dhcp_state = "no-lease"
        self.state.dhcp_ip = "-"
        return "OK: pppoe restarted; session NOT established (still padi-sent)"

    def _save_config(self, _: re.Match[str]) -> str:
        self.state.saved = True
        return "OK: configuration saved"


# ---------------------------------------------------------------------------
# Real-device SSH backend — stub (production work in milestone 2)
# ---------------------------------------------------------------------------


class SSHExecutorBackend(ExecutorBackend):
    """Stub. Production implementation will use Netmiko/Paramiko."""

    def __init__(self, host: str, username: str, password: str | None = None, key: str | None = None):
        self.host = host
        self.username = username
        # Credentials would be fetched from a secret store, not passed plain.
        self._password = password
        self._key = key

    def describe(self) -> str:
        return f"ssh:{self.username}@{self.host}"

    def execute(self, command: str) -> str:
        raise NotImplementedError(
            "SSH backend is a stub. Configure Netmiko/Paramiko in milestone 2."
        )


# ---------------------------------------------------------------------------
# Orchestrator — runs a FixScript step-by-step against a backend
# ---------------------------------------------------------------------------


class FixExecutor:
    """Runs a FixScript through a backend, producing an ExecutionReport."""

    def __init__(self, backend: ExecutorBackend, cfg: ExecutorConfig, audit: AuditLog):
        self.backend = backend
        self.cfg = cfg
        self.audit = audit

    def run(self, test_id: str, script: FixScript) -> ExecutionReport:
        report = ExecutionReport(test_id=test_id, started_at=datetime.now(timezone.utc))
        report.overall_status = StepStatus.RUNNING

        for step in script.steps:
            sr = self._run_one(step)
            report.step_results.append(sr)
            if sr.status == StepStatus.FAILED:
                if self.cfg.halt_on_step_failure:
                    if step.on_failure.value == "rollback":
                        self._rollback(script, report)
                    report.overall_status = StepStatus.FAILED
                    report.finished_at = datetime.now(timezone.utc)
                    report.final_verdict = Verdict.FAIL
                    report.notes = f"Halted on step {step.step_id}: {step.name}"
                    return report

        report.overall_status = StepStatus.SUCCESS
        report.finished_at = datetime.now(timezone.utc)
        report.final_verdict = Verdict.PASS
        return report

    # --- internals ---
    def _run_one(self, step) -> StepResult:
        sr = StepResult(
            step_id=step.step_id,
            name=step.name,
            type=step.type,
            command=step.command,
            status=StepStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        if self.cfg.dry_run:
            sr.output = f"[DRY-RUN] would execute: {step.command}"
            sr.status = StepStatus.SKIPPED
            sr.finished_at = datetime.now(timezone.utc)
            self.audit.record("step.dry_run", sr.model_dump())
            return sr

        try:
            output = self.backend.execute(step.command)
            sr.output = output
        except Exception as e:
            sr.error = str(e)
            sr.status = StepStatus.FAILED
            sr.finished_at = datetime.now(timezone.utc)
            self.audit.record("step.error", sr.model_dump())
            return sr

        # Validate against expected pattern.
        if step.expected_pattern:
            ok = re.search(step.expected_pattern, output) is not None
            sr.matched_expected = ok
            sr.status = StepStatus.SUCCESS if ok else StepStatus.FAILED
            if not ok:
                sr.error = (
                    f"Expected pattern not found.\n"
                    f"  pattern: {step.expected_pattern}\n"
                    f"  output:  {output[:300]}"
                )
        else:
            sr.status = StepStatus.SUCCESS

        sr.finished_at = datetime.now(timezone.utc)
        self.audit.record("step.executed", sr.model_dump())
        return sr

    def _rollback(self, script: FixScript, report: ExecutionReport) -> None:
        report.rollback_executed = True
        for step in script.rollback_steps:
            sr = self._run_one(step)
            report.rollback_results.append(sr)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_executor_backend(cfg: ExecutorConfig) -> ExecutorBackend:
    backend = (cfg.backend or "simulated").lower()
    if backend == "simulated":
        return SimulatedNTDBackend()
    if backend == "ssh":
        # Wired up properly in milestone 2 with credentials from secret store.
        raise NotImplementedError("SSH backend not yet wired. Use simulated for the demo.")
    raise ValueError(f"Unknown executor backend: {backend}")
