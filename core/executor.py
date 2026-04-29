"""
core/executor.py  — Step 4: COMPLETE
--------------------------------------
Runs FixScript steps one at a time. Three modes:

  DRY_RUN   — logs commands, no execution, always passes
  SIMULATED — pattern-matched canned responses (mock NTD for demo)
  LIVE      — real SSH/Netmiko (stub — Step 6)

Generator: yields StepResult after each step so the UI streams live updates.
Halts on first failure. Rollback is the caller's responsibility.

Simulated NTD covers the PPPoE VLAN mismatch scenario end-to-end:
  - Pre-fix:  interface wan0 vlan-id=10, pppoe=DISCOVERY_TIMEOUT
  - Post-fix: interface wan0 vlan-id=2,  pppoe=lcp-up, dhcp=bound
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple

from .logger import audit
from .models import ExecutionMode, FixScript, FixStep, StepStatus

logger = logging.getLogger(__name__)

# Simulated step delay — makes the demo feel real
SIMULATED_STEP_DELAY_S = 0.8


# ── StepResult ────────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    step:              FixStep
    status:            StepStatus
    stdout:            str = ""
    stderr:            str = ""
    exit_code:         int = 0
    pre_check_output:  str = ""
    post_check_output: str = ""
    executed_at:       datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "step_number":       self.step.step_number,
            "description":       self.step.description,
            "command":           self.step.command,
            "status":            self.status.value,
            "stdout":            self.stdout,
            "stderr":            self.stderr,
            "exit_code":         self.exit_code,
            "pre_check_output":  self.pre_check_output,
            "post_check_output": self.post_check_output,
            "executed_at":       self.executed_at.isoformat(),
        }


# ── Public entry point ────────────────────────────────────────────────────────

def execute(script: FixScript) -> Generator[StepResult, None, None]:
    """
    Execute each FixStep in order. Yields StepResult after each step.
    Halts on first failure — caller should offer rollback.

    Raises:
        PermissionError if script.approved_by is None
    """
    if script.approved_by is None:
        raise PermissionError("Script must be approved before execution.")

    mode = script.execution_mode
    logger.info(
        "Starting execution  script='%s'  mode=%s  steps=%d  approved_by=%s",
        script.title, mode.value, len(script.steps), script.approved_by,
    )

    # Run global pre-checks first
    for check_cmd in script.pre_checks:
        ok, out = _dispatch_command(check_cmd, mode)
        logger.info("Global pre-check: %s → %s", check_cmd, "OK" if ok else "FAIL")
        if not ok:
            logger.error("Global pre-check FAILED — aborting before any steps run")
            return   # don't yield — nothing was executed

    for step in sorted(script.steps, key=lambda s: s.step_number):
        step.status = StepStatus.RUNNING
        logger.info("[Step %d/%d] %s", step.step_number, len(script.steps), step.description)

        result = _execute_step(step, mode)

        # Write result back into the step model (FixScript carries live status)
        step.status            = result.status
        step.actual_output     = result.stdout
        step.pre_check_output  = result.pre_check_output or None
        step.post_check_output = result.post_check_output or None
        step.exit_code         = result.exit_code

        audit("step_executed", {
            "run_id":       script.run_id,
            "step_number":  step.step_number,
            "description":  step.description,
            "command":      step.command,
            "mode":         mode.value,
            "status":       result.status.value,
            "exit_code":    result.exit_code,
        })

        yield result

        if result.status == StepStatus.FAILED:
            logger.error("[Step %d] FAILED — halting. Offer rollback.", step.step_number)
            return

    # Run global post-checks
    for check_cmd in script.post_checks:
        ok, out = _dispatch_command(check_cmd, mode)
        status = "PASS" if ok else "FAIL"
        logger.info("Global post-check: %s → %s", check_cmd, status)

    logger.info("Execution complete — all steps passed")


def rollback(script: FixScript, from_step: int) -> Generator[StepResult, None, None]:
    """
    Run rollback commands for steps from_step..1 in reverse order.
    Only rolls back steps that have a rollback_command and were executed.
    """
    mode = script.execution_mode
    executed_steps = [
        s for s in script.steps
        if s.step_number <= from_step
        and s.rollback_command
        and s.status in (StepStatus.PASSED, StepStatus.FAILED)
    ]
    for step in sorted(executed_steps, key=lambda s: s.step_number, reverse=True):
        logger.info("[Rollback Step %d] %s", step.step_number, step.rollback_command)
        rollback_step = FixStep(
            step_number  = step.step_number,
            description  = f"ROLLBACK: {step.description}",
            command      = step.rollback_command,
        )
        result = _execute_step(rollback_step, mode)
        yield result


# ── Step execution ────────────────────────────────────────────────────────────

def _execute_step(step: FixStep, mode: ExecutionMode) -> StepResult:
    """Run one step: optional pre_check → command → verify expected_output → optional post_check."""

    pre_out = ""
    post_out = ""

    # 1. Per-step pre_check
    if step.pre_check:
        ok, pre_out = _dispatch_command(step.pre_check, mode)
        if not ok:
            return StepResult(
                step=step, status=StepStatus.FAILED,
                stdout="", stderr=f"Pre-check failed: {step.pre_check}",
                exit_code=1, pre_check_output=pre_out,
            )

    # 2. Main command
    ok, stdout = _dispatch_command(step.command, mode)
    if not ok:
        return StepResult(
            step=step, status=StepStatus.FAILED,
            stdout=stdout, stderr="Command returned non-zero exit code",
            exit_code=1, pre_check_output=pre_out,
        )

    # 3. expected_output assertion
    if step.expected_output and step.expected_output not in stdout:
        return StepResult(
            step=step, status=StepStatus.FAILED,
            stdout=stdout,
            stderr=f"Expected '{step.expected_output}' not found in output",
            exit_code=2, pre_check_output=pre_out,
        )

    # 4. Per-step post_check
    if step.post_check:
        ok, post_out = _dispatch_command(step.post_check, mode)
        if not ok:
            return StepResult(
                step=step, status=StepStatus.FAILED,
                stdout=stdout,
                stderr=f"Post-check failed: {step.post_check}",
                exit_code=3, pre_check_output=pre_out, post_check_output=post_out,
            )

    return StepResult(
        step=step, status=StepStatus.PASSED,
        stdout=stdout, exit_code=0,
        pre_check_output=pre_out, post_check_output=post_out,
    )


def _dispatch_command(command: str, mode: ExecutionMode) -> tuple[bool, str]:
    """Route a command to the correct mode handler. Returns (success, output)."""
    if mode == ExecutionMode.SIMULATED:
        time.sleep(SIMULATED_STEP_DELAY_S)
        return _ntd_simulate(command)
    else:  # DRY_RUN and anything else — safe default
        return True, f"[DRY RUN] {command}"


# ── Simulated NTD ─────────────────────────────────────────────────────────────
#
# Models a NetComm NF18ACV (firmware 3.7.2-r4) responding to CLI commands.
# State machine: the VLAN fix transitions the device from broken → fixed.
#
# Pattern-match order matters — more specific patterns before general ones.
# ─────────────────────────────────────────────────────────────────────────────

class _MockResponse(NamedTuple):
    pattern:     str        # regex matched against the command string (case-insensitive)
    output:      str        # stdout to return
    success:     bool = True
    # If state_required is set, only match when NTD state matches
    state_required: str | None = None
    # If state_after is set, transition NTD state on match
    state_after:    str | None = None


# Mutable state shared across one execution session
_ntd_state: dict = {"vlan": 10, "pppoe": "DISCOVERY_TIMEOUT", "dhcp": "no-lease"}


def _ntd_simulate(command: str) -> tuple[bool, str]:
    """
    Match command against the response table and return (success, output).
    Handles semicolon-chained commands (e.g. rollback: "set vlan 10 ; commit").
    Maintains _ntd_state so the device evolves correctly across steps.
    """
    global _ntd_state
    cmd = command.strip()

    # Handle chained commands separated by ';'
    if ";" in cmd:
        outputs: list[str] = []
        for sub in cmd.split(";"):
            ok, out = _ntd_simulate(sub.strip())
            outputs.append(out)
            if not ok:
                return False, "\n".join(outputs)
        return True, "\n".join(outputs)

    # ── Show interface config (read current state) ────────────────────────────
    if re.search(r"show\s+interface\s+wan0\s+config", cmd, re.I):
        return True, _render_wan0_config()

    # ── Show interface status ─────────────────────────────────────────────────
    if re.search(r"show\s+interface\s+wan0\s+status", cmd, re.I):
        return True, _render_wan0_status()

    # ── Show PPPoE status ─────────────────────────────────────────────────────
    if re.search(r"show\s+pppoe\s+status", cmd, re.I):
        return True, _render_pppoe_status()

    # ── Show DHCP status ──────────────────────────────────────────────────────
    if re.search(r"show\s+dhcp\s+(client\s+)?status", cmd, re.I):
        return True, _render_dhcp_status()

    # ── Show OLT VLAN counters ────────────────────────────────────────────────
    if re.search(r"show\s+olt.*(vlan|counter|mismatch)", cmd, re.I):
        vlan = _ntd_state["vlan"]
        if vlan == 2:
            return True, "OLT port g-1/0/3  sv-vlan-mismatch-count: 0  (all frames forwarded)"
        else:
            return True, f"OLT port g-1/0/3  sv-vlan-mismatch-count: 42  (frames tagged VLAN {vlan} dropped)"

    # ── Set VLAN — the core fix ───────────────────────────────────────────────
    m = re.search(r"set\s+interface\s+wan0\s+vlan[-_]?id\s+(\d+)", cmd, re.I)
    if m:
        new_vlan = int(m.group(1))
        old_vlan = _ntd_state["vlan"]
        _ntd_state["vlan"] = new_vlan
        return True, (
            f"OK: interface wan0 vlan-id changed {old_vlan} → {new_vlan}\n"
            f"Note: change will take effect after commit"
        )

    # ── Commit ────────────────────────────────────────────────────────────────
    if re.search(r"^commit$", cmd, re.I):
        vlan = _ntd_state["vlan"]
        if vlan == 2:
            # Correct VLAN — PPPoE should now work
            _ntd_state["pppoe"] = "lcp-up"
            _ntd_state["dhcp"]  = "bound"
            return True, (
                "Commit successful.\n"
                "interface wan0: vlan-id=2 applied\n"
                "PPPoE client restarting on wan0...\n"
                "PPPoE PADI sent, PADO received from BNG (10.240.1.1)\n"
                "PPPoE LCP negotiation complete — state: lcp-up\n"
                "PPPoE IPCP complete — IP assigned: 27.34.102.18\n"
                "DHCP client: lease bound — 27.34.102.18/24 gw 27.34.102.1"
            )
        else:
            _ntd_state["pppoe"] = "DISCOVERY_TIMEOUT"
            _ntd_state["dhcp"]  = "no-lease"
            return True, f"Commit successful. interface wan0: vlan-id={vlan} applied"

    # ── Ping NTD management ───────────────────────────────────────────────────
    if re.search(r"ping\s+192\.168\.100\.1", cmd, re.I):
        return True, (
            "PING 192.168.100.1: 56 data bytes\n"
            "64 bytes from 192.168.100.1: icmp_seq=0 ttl=64 time=0.4 ms\n"
            "64 bytes from 192.168.100.1: icmp_seq=1 ttl=64 time=0.3 ms\n"
            "2 packets transmitted, 2 received, 0% packet loss"
        )

    # ── Restart PPPoE client ──────────────────────────────────────────────────
    if re.search(r"restart\s+pppoe|pppoe\s+restart", cmd, re.I):
        if _ntd_state["vlan"] == 2:
            _ntd_state["pppoe"] = "lcp-up"
            _ntd_state["dhcp"]  = "bound"
            return True, "PPPoE client restarted — state: lcp-up"
        else:
            return True, "PPPoE client restarted — state: DISCOVERY_TIMEOUT (VLAN still wrong)"

    # ── Verify PPPoE is up (post-check assertion) ────────────────────────────
    if re.search(r"show\s+pppoe.*lcp|verify\s+pppoe", cmd, re.I):
        if _ntd_state["pppoe"] == "lcp-up":
            return True, "PPPoE state: lcp-up  session-id: 1042  server: BNG-SYD-01"
        else:
            return False, f"PPPoE state: {_ntd_state['pppoe']}  (not lcp-up)"

    # ── Show running config (full) ────────────────────────────────────────────
    if re.search(r"show\s+(running|run)\s*config", cmd, re.I):
        return True, _render_running_config()

    # ── Unknown command ───────────────────────────────────────────────────────
    logger.warning("Simulated NTD: unrecognised command '%s' — returning generic OK", cmd)
    return True, f"% Command executed: {cmd}\nOK"


# ── NTD output renderers ──────────────────────────────────────────────────────

def _render_wan0_config() -> str:
    vlan = _ntd_state["vlan"]
    return (
        f"interface wan0\n"
        f"  description     : WAN (PPPoE uplink)\n"
        f"  admin-state     : up\n"
        f"  vlan-id         : {vlan}\n"
        f"  mode            : PPPoE\n"
        f"  auth-type       : PAP\n"
        f"  pppoe-client    : enabled\n"
        f"  mtu             : 1492\n"
    )


def _render_wan0_status() -> str:
    vlan  = _ntd_state["vlan"]
    pppoe = _ntd_state["pppoe"]
    link  = "up" if pppoe == "lcp-up" else "up (PPPoE failed)"
    return (
        f"interface wan0\n"
        f"  link-state      : {link}\n"
        f"  vlan-id         : {vlan}\n"
        f"  pppoe-state     : {pppoe}\n"
        f"  rx-packets      : 3,842\n"
        f"  tx-packets      : 3,156\n"
        f"  rx-errors       : 0\n"
    )


def _render_pppoe_status() -> str:
    state = _ntd_state["pppoe"]
    if state == "lcp-up":
        return (
            "PPPoE Client Status\n"
            "  state           : lcp-up\n"
            "  session-id      : 1042\n"
            "  server-mac      : 00:1A:2B:3C:4D:5E  (BNG-SYD-01)\n"
            "  ip-address      : 27.34.102.18\n"
            "  gateway         : 27.34.102.1\n"
            "  dns-primary     : 61.9.0.1\n"
            "  dns-secondary   : 61.9.0.2\n"
            "  uptime          : 0d 00:01:14\n"
        )
    vlan = _ntd_state["vlan"]
    return (
        f"PPPoE Client Status\n"
        f"  state           : {state}\n"
        f"  last-error      : No PADO received after 3 attempts (90s)\n"
        f"  wan-vlan        : {vlan}\n"
        f"  attempts        : 3\n"
        f"  last-attempt    : 2026-04-28T03:15:51Z\n"
    )


def _render_dhcp_status() -> str:
    state = _ntd_state["dhcp"]
    if state == "bound":
        return (
            "DHCP Client Status\n"
            "  state           : bound\n"
            "  ip-address      : 27.34.102.18\n"
            "  subnet-mask     : 255.255.255.0\n"
            "  gateway         : 27.34.102.1\n"
            "  lease-expires   : 2026-04-28T15:14:21Z\n"
        )
    return (
        f"DHCP Client Status\n"
        f"  state           : {state}\n"
        f"  reason          : PPPoE session not established\n"
    )


def _render_running_config() -> str:
    vlan = _ntd_state["vlan"]
    return (
        f"! NetComm NF18ACV Running Configuration\n"
        f"! Firmware: 3.7.2-r4\n"
        f"!\n"
        f"interface wan0\n"
        f"  admin-state up\n"
        f"  vlan-id {vlan}\n"
        f"  mode pppoe\n"
        f"  auth-type pap\n"
        f"!\n"
        f"interface lan0\n"
        f"  admin-state up\n"
        f"  ip-address 192.168.1.1/24\n"
        f"!\n"
    )


def reset_simulated_ntd() -> None:
    """Reset NTD state to broken (pre-fix). Used between test runs."""
    global _ntd_state
    _ntd_state = {"vlan": 10, "pppoe": "DISCOVERY_TIMEOUT", "dhcp": "no-lease"}
