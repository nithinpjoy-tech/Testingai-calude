"""
core/executor.py  — Milestone 4: live device execution added
--------------------------------------------------------------
Three execution modes:

  SIMULATED — pattern-matched mock NTD (PPPoE VLAN scenario state machine)
  LIVE      — real SSH via Netmiko (reads credentials from config/env)
  DRY_RUN   — logs commands only, no execution (treated as SIMULATED with no delays)

Generator: yields StepResult after each step so callers stream live updates.
Halts on first failure. rollback() generator runs in reverse order.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import NamedTuple

from .logger import audit
from .models import ExecutionMode, FixScript, FixStep, StepStatus

logger = logging.getLogger(__name__)

SIMULATED_STEP_DELAY_S = float(os.getenv("SIMULATED_STEP_DELAY", "0.8"))


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
    executed_at:       datetime = field(default_factory=lambda: datetime.now(timezone.utc))

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


# ── Public API ─────────────────────────────────────────────────────────────────

def execute(script: FixScript) -> Generator[StepResult, None, None]:
    """
    Execute each FixStep in order. Yields StepResult after each step.
    Halts on first failure — caller should call rollback() if needed.

    Raises:
        PermissionError  if script.approved_by is None
        RuntimeError     if LIVE mode requested but Netmiko unavailable
    """
    if script.approved_by is None:
        raise PermissionError("Script must be approved before execution.")

    mode = script.execution_mode
    logger.info("Starting execution  script='%s'  mode=%s  steps=%d  approved_by=%s",
                script.title, mode.value, len(script.steps), script.approved_by)

    # Global pre-checks
    for check_cmd in script.pre_checks:
        ok, out = _dispatch(check_cmd, mode)
        logger.info("Global pre-check [%s]: %s", "OK" if ok else "FAIL", check_cmd)
        if not ok:
            logger.error("Global pre-check FAILED — aborting before any steps run")
            return

    for step in sorted(script.steps, key=lambda s: s.step_number):
        step.status = StepStatus.RUNNING
        logger.info("[Step %d/%d] %s", step.step_number, len(script.steps), step.description)

        result = _execute_step(step, mode)

        step.status            = result.status
        step.actual_output     = result.stdout
        step.pre_check_output  = result.pre_check_output or None
        step.post_check_output = result.post_check_output or None
        step.exit_code         = result.exit_code

        audit("step_executed", {
            "run_id":      script.run_id,
            "step_number": step.step_number,
            "description": step.description,
            "command":     step.command,
            "mode":        mode.value,
            "status":      result.status.value,
            "exit_code":   result.exit_code,
        })

        yield result

        if result.status == StepStatus.FAILED:
            logger.error("[Step %d] FAILED — halting. Offer rollback.", step.step_number)
            return

    for check_cmd in script.post_checks:
        ok, out = _dispatch(check_cmd, mode)
        logger.info("Global post-check [%s]: %s", "OK" if ok else "FAIL", check_cmd)

    logger.info("Execution complete — all steps passed")


def rollback(script: FixScript, from_step: int) -> Generator[StepResult, None, None]:
    """
    Run rollback commands for steps from_step..1 in reverse order.
    Only rolls back steps with a rollback_command that were executed.
    """
    mode = script.execution_mode
    executed = [
        s for s in script.steps
        if s.step_number <= from_step
        and s.rollback_command
        and s.status in (StepStatus.PASSED, StepStatus.FAILED)
    ]
    for step in sorted(executed, key=lambda s: s.step_number, reverse=True):
        logger.info("[Rollback Step %d] %s", step.step_number, step.rollback_command)
        rb_step = FixStep(
            step_number  = step.step_number,
            description  = f"ROLLBACK: {step.description}",
            command      = step.rollback_command,
        )
        yield _execute_step(rb_step, mode)


# ── Step execution ─────────────────────────────────────────────────────────────

def _execute_step(step: FixStep, mode: ExecutionMode) -> StepResult:
    pre_out = post_out = ""

    if step.pre_check:
        ok, pre_out = _dispatch(step.pre_check, mode)
        if not ok:
            return StepResult(step=step, status=StepStatus.FAILED,
                              stderr=f"Pre-check failed: {step.pre_check}",
                              exit_code=1, pre_check_output=pre_out)

    ok, stdout = _dispatch(step.command, mode)
    if not ok:
        return StepResult(step=step, status=StepStatus.FAILED, stdout=stdout,
                          stderr="Command returned non-zero exit code",
                          exit_code=1, pre_check_output=pre_out)

    if step.expected_output and step.expected_output not in stdout:
        return StepResult(step=step, status=StepStatus.FAILED, stdout=stdout,
                          stderr=f"Expected '{step.expected_output}' not found in output",
                          exit_code=2, pre_check_output=pre_out)

    if step.post_check:
        ok, post_out = _dispatch(step.post_check, mode)
        if not ok:
            return StepResult(step=step, status=StepStatus.FAILED, stdout=stdout,
                              stderr=f"Post-check failed: {step.post_check}",
                              exit_code=3, pre_check_output=pre_out, post_check_output=post_out)

    return StepResult(step=step, status=StepStatus.PASSED, stdout=stdout,
                      exit_code=0, pre_check_output=pre_out, post_check_output=post_out)


def _dispatch(command: str, mode: ExecutionMode) -> tuple[bool, str]:
    """Route a command to the correct handler."""
    if mode == ExecutionMode.LIVE:
        return _run_live(command)
    else:
        time.sleep(SIMULATED_STEP_DELAY_S)
        return _ntd_simulate(command)


# ── Live execution via Netmiko ────────────────────────────────────────────────

# Connection cache — one connection per executor lifetime
_live_connection = None

def _get_live_connection():
    """Return cached Netmiko connection, creating it if necessary."""
    global _live_connection
    if _live_connection is not None:
        return _live_connection

    try:
        from netmiko import ConnectHandler
    except ImportError:
        raise RuntimeError(
            "netmiko is not installed. Add it to requirements.txt and run: "
            "pip install netmiko"
        )

    host     = os.getenv("NTD_HOST", "")
    username = os.getenv("NTD_USER", "admin")
    password = os.getenv("NTD_PASSWORD", "")
    device_type = os.getenv("NTD_DEVICE_TYPE", "linux")
    port     = int(os.getenv("NTD_SSH_PORT", "22"))

    if not host:
        raise RuntimeError(
            "NTD_HOST environment variable not set. "
            "Set NTD_HOST, NTD_USER, NTD_PASSWORD in .env for LIVE mode."
        )

    logger.info("Connecting to device %s:%d as %s", host, port, username)
    _live_connection = ConnectHandler(
        device_type = device_type,
        host        = host,
        username    = username,
        password    = password,
        port        = port,
    )
    logger.info("SSH connection established to %s", host)
    return _live_connection


def _run_live(command: str) -> tuple[bool, str]:
    """Execute command on real device via Netmiko SSH."""
    try:
        conn   = _get_live_connection()
        output = conn.send_command(command, read_timeout=30)
        # Heuristic: if the device echoes common error keywords, treat as failure
        error_indicators = ["Error:", "error:", "% Invalid", "% Unknown", "command not found"]
        failed = any(ind in output for ind in error_indicators)
        return (not failed), output
    except Exception as exc:
        logger.error("Live execution error for command '%s': %s", command, exc)
        return False, str(exc)


def disconnect_live() -> None:
    """Close the live SSH connection. Call at end of execution session."""
    global _live_connection
    if _live_connection:
        try:
            _live_connection.disconnect()
        except Exception:
            pass
        _live_connection = None
        logger.info("SSH connection closed")


# ── Simulated NTD state machine ───────────────────────────────────────────────

_ntd_state: dict = {"vlan": 10, "pppoe": "DISCOVERY_TIMEOUT", "dhcp": "no-lease"}


def _ntd_simulate(command: str) -> tuple[bool, str]:
    """Match command against mock NTD response table."""
    global _ntd_state
    cmd = command.strip()

    # Handle semicolon-chained commands (e.g. rollback: "set vlan 10 ; commit")
    if ";" in cmd:
        outputs: list[str] = []
        for sub in cmd.split(";"):
            ok, out = _ntd_simulate(sub.strip())
            outputs.append(out)
            if not ok:
                return False, "\n".join(outputs)
        return True, "\n".join(outputs)

    if re.search(r"show\s+interface\s+wan0\s+config", cmd, re.I):
        return True, _render_wan0_config()
    if re.search(r"show\s+interface\s+wan0\s+status", cmd, re.I):
        return True, _render_wan0_status()
    if re.search(r"show\s+pppoe\s+status", cmd, re.I):
        return True, _render_pppoe_status()
    if re.search(r"show\s+dhcp\s+(client\s+)?status", cmd, re.I):
        return True, _render_dhcp_status()
    if re.search(r"show\s+olt.*(vlan|counter|mismatch)", cmd, re.I):
        vlan = _ntd_state["vlan"]
        if vlan == 2:
            return True, "OLT port g-1/0/3  sv-vlan-mismatch-count: 0  (all frames forwarded)"
        return True, f"OLT port g-1/0/3  sv-vlan-mismatch-count: 42  (frames tagged VLAN {vlan} dropped)"

    m = re.search(r"set\s+interface\s+wan0\s+vlan[-_]?id\s+(\d+)", cmd, re.I)
    if m:
        new_vlan = int(m.group(1))
        old_vlan = _ntd_state["vlan"]
        _ntd_state["vlan"] = new_vlan
        return True, (f"OK: interface wan0 vlan-id changed {old_vlan} → {new_vlan}\n"
                      f"Note: change will take effect after commit")

    if re.search(r"^commit$", cmd, re.I):
        vlan = _ntd_state["vlan"]
        if vlan == 2:
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
        _ntd_state["pppoe"] = "DISCOVERY_TIMEOUT"
        _ntd_state["dhcp"]  = "no-lease"
        return True, f"Commit successful. interface wan0: vlan-id={vlan} applied"

    if re.search(r"ping\s+192\.168\.100\.1", cmd, re.I):
        return True, ("PING 192.168.100.1: 56 data bytes\n"
                      "64 bytes from 192.168.100.1: icmp_seq=0 ttl=64 time=0.4 ms\n"
                      "2 packets transmitted, 2 received, 0% packet loss")

    if re.search(r"restart\s+pppoe|pppoe\s+restart", cmd, re.I):
        if _ntd_state["vlan"] == 2:
            _ntd_state["pppoe"] = "lcp-up"
            _ntd_state["dhcp"]  = "bound"
            return True, "PPPoE client restarted — state: lcp-up"
        return True, "PPPoE client restarted — state: DISCOVERY_TIMEOUT (VLAN still wrong)"

    if re.search(r"show\s+pppoe.*lcp|verify\s+pppoe", cmd, re.I):
        if _ntd_state["pppoe"] == "lcp-up":
            return True, "PPPoE state: lcp-up  session-id: 1042  server: BNG-SYD-01"
        return False, f"PPPoE state: {_ntd_state['pppoe']}  (not lcp-up)"

    if re.search(r"show\s+(running|run)\s*config", cmd, re.I):
        return True, _render_running_config()

    logger.warning("Simulated NTD: unrecognised command '%s' — returning generic OK", cmd)
    return True, f"% Command executed: {cmd}\nOK"


# ── NTD output renderers ──────────────────────────────────────────────────────

def _render_wan0_config() -> str:
    vlan = _ntd_state["vlan"]
    return (f"interface wan0\n  description     : WAN (PPPoE uplink)\n"
            f"  admin-state     : up\n  vlan-id         : {vlan}\n"
            f"  mode            : PPPoE\n  auth-type       : PAP\n"
            f"  pppoe-client    : enabled\n  mtu             : 1492\n")

def _render_wan0_status() -> str:
    vlan  = _ntd_state["vlan"]
    pppoe = _ntd_state["pppoe"]
    link  = "up" if pppoe == "lcp-up" else "up (PPPoE failed)"
    return (f"interface wan0\n  link-state      : {link}\n"
            f"  vlan-id         : {vlan}\n  pppoe-state     : {pppoe}\n"
            f"  rx-packets      : 3,842\n  tx-packets      : 3,156\n  rx-errors       : 0\n")

def _render_pppoe_status() -> str:
    state = _ntd_state["pppoe"]
    if state == "lcp-up":
        return ("PPPoE Client Status\n  state           : lcp-up\n"
                "  session-id      : 1042\n  server-mac      : 00:1A:2B:3C:4D:5E  (BNG-SYD-01)\n"
                "  ip-address      : 27.34.102.18\n  gateway         : 27.34.102.1\n"
                "  dns-primary     : 61.9.0.1\n  uptime          : 0d 00:01:14\n")
    return (f"PPPoE Client Status\n  state           : {state}\n"
            f"  last-error      : No PADO received after 3 attempts (90s)\n"
            f"  wan-vlan        : {_ntd_state['vlan']}\n  attempts        : 3\n")

def _render_dhcp_status() -> str:
    state = _ntd_state["dhcp"]
    if state == "bound":
        return ("DHCP Client Status\n  state           : bound\n"
                "  ip-address      : 27.34.102.18\n  subnet-mask     : 255.255.255.0\n"
                "  gateway         : 27.34.102.1\n  lease-expires   : 2026-04-28T15:14:21Z\n")
    return f"DHCP Client Status\n  state           : {state}\n  reason          : PPPoE session not established\n"

def _render_running_config() -> str:
    vlan = _ntd_state["vlan"]
    return (f"! NetComm NF18ACV Running Configuration\n! Firmware: 3.7.2-r4\n!\n"
            f"interface wan0\n  admin-state up\n  vlan-id {vlan}\n  mode pppoe\n  auth-type pap\n!\n"
            f"interface lan0\n  admin-state up\n  ip-address 192.168.1.1/24\n!\n")

def reset_simulated_ntd() -> None:
    """Reset NTD state to broken (pre-fix). Call between test runs."""
    global _ntd_state
    _ntd_state = {"vlan": 10, "pppoe": "DISCOVERY_TIMEOUT", "dhcp": "no-lease"}
