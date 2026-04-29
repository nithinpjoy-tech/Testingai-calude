"""
tests/test_executor.py
-----------------------
Tests for the simulated executor and mock NTD state machine.
No real device connections — all simulated.
"""
from __future__ import annotations
from datetime import datetime

import pytest

from core.executor import (
    StepResult, _ntd_simulate, execute, reset_simulated_ntd, rollback,
)
from core.models import (
    ExecutionMode, FixScript, FixStep, StepStatus,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _approved_script(steps: list[FixStep], mode=ExecutionMode.SIMULATED) -> FixScript:
    return FixScript(
        run_id="run-exec-001",
        title="Test Fix",
        steps=steps,
        approved_by="test-operator",
        approved_at=datetime.utcnow(),
        execution_mode=mode,
    )

def _step(n: int, cmd: str, expected: str | None = None,
          pre: str | None = None, post: str | None = None,
          rollback_cmd: str | None = None) -> FixStep:
    return FixStep(
        step_number=n, description=f"Step {n}",
        command=cmd, expected_output=expected,
        pre_check=pre, post_check=post,
        rollback_command=rollback_cmd,
    )


# ── Approval gate ─────────────────────────────────────────────────────────────

def test_unapproved_script_raises():
    script = FixScript(run_id="x", title="t", steps=[_step(1, "ping 192.168.100.1")])
    with pytest.raises(PermissionError):
        list(execute(script))


# ── Dry run mode ──────────────────────────────────────────────────────────────

def test_dry_run_always_passes():
    script = _approved_script(
        [_step(1, "set interface wan0 vlan-id 2"),
         _step(2, "commit")],
        mode=ExecutionMode.SIMULATED,
    )
    # Override to dry run via execution_mode — use DRY_RUN string workaround
    # (DRY_RUN isn't in ExecutionMode enum yet — simulated is the default)
    results = list(execute(script))
    # Just verify we get results — full dry-run mode tested via _dispatch
    assert len(results) == 2


# ── Simulated NTD — command pattern tests ────────────────────────────────────

def setup_function():
    """Reset NTD to broken state before each test."""
    reset_simulated_ntd()


def test_ntd_show_wan0_config_has_vlan():
    ok, out = _ntd_simulate("show interface wan0 config")
    assert ok
    assert "vlan-id" in out
    assert "10" in out       # initial broken state


def test_ntd_show_pppoe_status_broken():
    ok, out = _ntd_simulate("show pppoe status")
    assert ok
    assert "DISCOVERY_TIMEOUT" in out


def test_ntd_set_vlan_changes_state():
    ok, out = _ntd_simulate("set interface wan0 vlan-id 2")
    assert ok
    assert "2" in out
    # Verify state changed
    ok2, out2 = _ntd_simulate("show interface wan0 config")
    assert "vlan-id         : 2" in out2


def test_ntd_commit_with_correct_vlan_fixes_pppoe():
    _ntd_simulate("set interface wan0 vlan-id 2")
    ok, out = _ntd_simulate("commit")
    assert ok
    assert "lcp-up" in out
    assert "27.34.102.18" in out  # IP was assigned


def test_ntd_show_pppoe_after_fix_is_up():
    _ntd_simulate("set interface wan0 vlan-id 2")
    _ntd_simulate("commit")
    ok, out = _ntd_simulate("show pppoe status")
    assert ok
    assert "lcp-up" in out
    assert "session-id" in out


def test_ntd_show_dhcp_after_fix_is_bound():
    _ntd_simulate("set interface wan0 vlan-id 2")
    _ntd_simulate("commit")
    ok, out = _ntd_simulate("show dhcp client status")
    assert ok
    assert "bound" in out


def test_ntd_commit_with_wrong_vlan_stays_broken():
    _ntd_simulate("set interface wan0 vlan-id 99")
    ok, out = _ntd_simulate("commit")
    assert ok                               # commit succeeds
    ok2, out2 = _ntd_simulate("show pppoe status")
    assert "DISCOVERY_TIMEOUT" in out2     # but PPPoE still broken


def test_ntd_ping_succeeds():
    ok, out = _ntd_simulate("ping 192.168.100.1")
    assert ok
    assert "0% packet loss" in out


def test_ntd_unknown_command_returns_ok():
    ok, out = _ntd_simulate("show version")
    assert ok   # unknown commands don't crash the NTD


def test_ntd_rollback_set_vlan():
    _ntd_simulate("set interface wan0 vlan-id 2")
    _ntd_simulate("commit")
    # Now rollback: set back to 10
    _ntd_simulate("set interface wan0 vlan-id 10")
    _ntd_simulate("commit")
    ok, out = _ntd_simulate("show pppoe status")
    assert "DISCOVERY_TIMEOUT" in out


# ── Full pipeline execution ───────────────────────────────────────────────────

def test_full_pppoe_fix_pipeline():
    """End-to-end: 3-step VLAN fix — all steps should PASS."""
    reset_simulated_ntd()
    script = _approved_script([
        _step(1, "show interface wan0 config",
              expected="vlan-id"),
        _step(2, "set interface wan0 vlan-id 2",
              expected="vlan-id changed",
              rollback_cmd="set interface wan0 vlan-id 10"),
        _step(3, "commit",
              expected="lcp-up",
              post="show pppoe status",
              rollback_cmd="set interface wan0 vlan-id 10 ; commit"),
    ])

    results = list(execute(script))

    assert len(results) == 3
    for r in results:
        assert r.status == StepStatus.PASSED, f"Step {r.step.step_number} failed: {r.stderr}"

    # Verify the script's step objects were updated in-place
    assert script.steps[0].status == StepStatus.PASSED
    assert script.steps[2].status == StepStatus.PASSED
    assert "lcp-up" in (script.steps[2].actual_output or "")


def test_expected_output_mismatch_fails_step():
    reset_simulated_ntd()
    # Step expects 'lcp-up' but device will still be broken (wrong VLAN)
    script = _approved_script([
        _step(1, "show pppoe status", expected="lcp-up"),
    ])
    results = list(execute(script))
    assert results[0].status == StepStatus.FAILED
    assert "Expected" in results[0].stderr


def test_execution_halts_after_failure():
    reset_simulated_ntd()
    script = _approved_script([
        _step(1, "show pppoe status", expected="lcp-up"),   # will fail
        _step(2, "commit"),                                   # should never run
    ])
    results = list(execute(script))
    assert len(results) == 1   # halted after step 1


def test_rollback_runs_in_reverse():
    reset_simulated_ntd()
    # Apply the fix, then rollback
    script = _approved_script([
        _step(1, "set interface wan0 vlan-id 2",
              rollback_cmd="set interface wan0 vlan-id 10"),
        _step(2, "commit",
              rollback_cmd="set interface wan0 vlan-id 10 ; commit"),
    ])
    list(execute(script))   # apply fix

    # Manually mark steps as passed for rollback to pick them up
    for s in script.steps:
        s.status = StepStatus.PASSED

    rollback_results = list(rollback(script, from_step=2))
    assert len(rollback_results) == 2
    # After rollback the NTD should be broken again
    ok, out = _ntd_simulate("show pppoe status")
    assert "DISCOVERY_TIMEOUT" in out
