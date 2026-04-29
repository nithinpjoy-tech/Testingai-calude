"""
cli/main.py — Feature #19: Full CLI with parity to the UI.
All commands use Rich for terminal output.

Usage:
  python -m cli.main analyse samples/pppoe_vlan_mismatch.json
  python -m cli.main analyse samples/pppoe_vlan_mismatch.xml --no-exec
  python -m cli.main analyse samples/pppoe_vlan_mismatch.json --approve
  python -m cli.main history --limit 10
  python -m cli.main compare <run-id-a> <run-id-b>
  python -m cli.main replay <run-id>
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich import print as rprint

console = Console()

SEV_COLOUR = {
    "CRITICAL": "bold red",
    "HIGH":     "bold yellow",
    "MEDIUM":   "bold blue",
    "LOW":      "bold green",
}


# ── CLI group ─────────────────────────────────────────────────────────────────

@click.group()
@click.version_option("0.1.0-milestone1")
def cli():
    """NBN Test Triage Tool — AI-powered test failure analysis."""


# ── analyse ───────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--mode",    default="simulated",
              type=click.Choice(["dry_run", "simulated", "live"]),
              show_default=True, help="Execution mode for fix script.")
@click.option("--approve", is_flag=True, default=False,
              help="Auto-approve fix script without interactive prompt.")
@click.option("--no-exec", "no_exec", is_flag=True, default=False,
              help="Triage only — stop before generating fix script.")
@click.option("--output",  default=None, type=click.Path(),
              help="Save full report JSON to this path.")
@click.option("--operator", default="cli-user", show_default=True,
              help="Operator name written to audit trail.")
def analyse(file: str, mode: str, approve: bool, no_exec: bool,
            output: str | None, operator: str):
    """Ingest a test result, triage with Claude, and optionally execute fix."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from core.ingestor      import ingest
    from core.triage_engine import analyse as do_triage
    from core.remediation   import generate_fix_script
    from core.executor      import execute, reset_simulated_ntd, StepResult
    from core.reporter      import build_report, save, to_run_record
    from core.models        import ExecutionMode, StepStatus
    from notifications.webhook import notify
    import db.store as store

    store.init_db()

    # ── Step 1: Ingest ────────────────────────────────────────────────────────
    console.rule("[bold]NBN Test Triage Tool[/bold]")
    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  console=console, transient=True) as prog:
        prog.add_task("Ingesting test result...", total=None)
        run = ingest(file)

    _print_run_summary(run)

    # ── Step 2: Triage ────────────────────────────────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  console=console, transient=True) as prog:
        prog.add_task("Sending to Claude for triage...", total=None)
        triage = do_triage(run)

    _print_triage_result(triage)

    if no_exec:
        console.print("\n[dim]--no-exec set — stopping after triage.[/dim]")
        _save_and_persist(run, triage, None, None, output, store)
        return

    # ── Step 3: Fix script ────────────────────────────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  console=console, transient=True) as prog:
        prog.add_task("Generating fix script...", total=None)
        script = generate_fix_script(run, triage)

    _print_fix_script(script)

    # ── Step 4: Approval ──────────────────────────────────────────────────────
    if not approve:
        if not click.confirm("\n▶  Approve and execute this fix script?"):
            console.print("[yellow]Script rejected — nothing executed.[/yellow]")
            _save_and_persist(run, triage, script, None, output, store)
            return

    script.approved_by = operator
    script.approved_at = datetime.utcnow()
    console.print(f"\n[green]✅ Approved by:[/green] {operator}")

    # ── Step 5: Execute ───────────────────────────────────────────────────────
    exec_mode_map = {
        "dry_run":   ExecutionMode.SIMULATED,  # dry_run handled inside executor
        "simulated": ExecutionMode.SIMULATED,
        "live":      ExecutionMode.LIVE,
    }
    script.execution_mode = exec_mode_map[mode]

    if mode == "simulated":
        reset_simulated_ntd()

    console.print(f"\n[bold]▶  Executing in[/bold] [cyan]{mode}[/cyan] mode\n")
    results: list[StepResult] = []
    all_passed = True

    for result in execute(script):
        results.append(result)
        icon = "✅" if result.status == StepStatus.PASSED else "❌"
        console.print(
            f"  {icon} [bold]Step {result.step.step_number}[/bold]: "
            f"{result.step.description}"
        )
        if result.stdout:
            for line in result.stdout.strip().splitlines()[:4]:
                console.print(f"       [dim]{line}[/dim]")
        if result.status == StepStatus.FAILED:
            console.print(f"  [red]     ✗ {result.stderr}[/red]")
            all_passed = False
            break

    if all_passed:
        console.print("\n[bold green]✅ All steps passed.[/bold green]")
    else:
        console.print("\n[bold red]❌ Execution halted on failure.[/bold red]")

    # ── Step 6: Report ────────────────────────────────────────────────────────
    from core.executor import StepResult as SR
    from core.models import ExecutionResult
    exec_result = ExecutionResult(
        run_id=run.run_id,
        fix_script_title=script.title,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        overall_status=results[-1].status if results else StepStatus.PENDING,
        steps=script.steps,
        execution_mode=script.execution_mode,
        operator=operator,
    )
    _save_and_persist(run, triage, script, exec_result, output, store)


def _save_and_persist(run, triage, script, execution, output, store):
    from core.reporter import build_report, save, to_run_record
    report = build_report(run, triage, script, execution)
    path   = save(report)
    store.upsert_run(to_run_record(report), report.model_dump_json())
    console.print(f"\n[dim]Report saved → {path}[/dim]")
    if output:
        Path(output).write_text(report.model_dump_json(indent=2))
        console.print(f"[dim]Also written → {output}[/dim]")


# ── history ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--limit", default=20, show_default=True, help="Max rows to show.")
@click.option("--verdict", default=None,
              type=click.Choice(["PASS","FAIL","BLOCKED","INCONCLUSIVE"]),
              help="Filter by verdict.")
def history(limit: int, verdict: str | None):
    """List recent runs from local history."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import db.store as store
    from core.models import Verdict

    store.init_db()
    runs = store.list_runs(limit=limit)

    if verdict:
        runs = [r for r in runs if r.verdict.value == verdict]

    if not runs:
        console.print("[yellow]No runs found.[/yellow]")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold #1A3557")
    table.add_column("Timestamp",  style="dim",    width=18)
    table.add_column("Run ID",     style="cyan",   width=10)
    table.add_column("Test Case",              width=36)
    table.add_column("Verdict",               width=12)
    table.add_column("Severity",              width=10)
    table.add_column("Status",                width=12)
    table.add_column("Root Cause",            width=40)

    for r in runs:
        ts  = r.created_at.strftime("%m-%d %H:%M") if r.created_at else "—"
        rid = r.id[:8] + "…"
        vrd_style = "red" if r.verdict.value == "FAIL" else "green"
        sev = r.severity.value if r.severity else "—"
        sev_style = SEV_COLOUR.get(sev, "dim")
        root = (r.root_cause or "—")[:38] + ("…" if r.root_cause and len(r.root_cause) > 38 else "")
        table.add_row(
            ts, rid, r.test_case[:34],
            Text(r.verdict.value, style=vrd_style),
            Text(sev, style=sev_style),
            r.status.value,
            root,
        )

    console.print(table)
    console.print(f"[dim]{len(runs)} run(s) shown[/dim]")


# ── compare ───────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("run_id_a")
@click.argument("run_id_b")
def compare(run_id_a: str, run_id_b: str):
    """Diff two runs side-by-side (metrics, severity, root cause)."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import db.store as store

    store.init_db()

    raw_a = store.get_report_json(run_id_a)
    raw_b = store.get_report_json(run_id_b)

    missing = [id_ for id_, raw in [(run_id_a, raw_a), (run_id_b, raw_b)] if not raw]
    if missing:
        console.print(f"[red]Report data not found for: {', '.join(missing)}[/red]")
        console.print("[dim]Tip: run a full triage with 'analyse' first to generate report data.[/dim]")
        sys.exit(1)

    a = json.loads(raw_a)
    b = json.loads(raw_b)

    console.rule("[bold]Run Comparison[/bold]")

    # Header
    _compare_row("Test case",
                 a.get("test_run",{}).get("test_case_name","—")[:40],
                 b.get("test_run",{}).get("test_case_name","—")[:40])
    _compare_row("Verdict",
                 a.get("test_run",{}).get("verdict","—"),
                 b.get("test_run",{}).get("verdict","—"))

    ta, tb = a.get("triage",{}), b.get("triage",{})
    _compare_row("Severity",   ta.get("severity","—"),   tb.get("severity","—"))
    _compare_row("Confidence", f"{ta.get('confidence',0):.0%}", f"{tb.get('confidence',0):.0%}")

    console.print()
    console.print("[bold]Root cause A:[/bold]", ta.get("root_cause_summary","—"))
    console.print("[bold]Root cause B:[/bold]", tb.get("root_cause_summary","—"))

    # Metrics diff
    metrics_a = {m["name"]: m for m in a.get("test_run",{}).get("metrics",[])}
    metrics_b = {m["name"]: m for m in b.get("test_run",{}).get("metrics",[])}
    all_names = sorted(set(metrics_a) | set(metrics_b))

    if all_names:
        console.print()
        table = Table(box=box.SIMPLE, title="Metrics diff")
        table.add_column("Metric", style="bold")
        table.add_column("Run A")
        table.add_column("Run B")
        table.add_column("Δ")

        for name in all_names:
            ma = metrics_a.get(name, {})
            mb = metrics_b.get(name, {})
            va = str(ma.get("measured","—")) if ma else "—"
            vb = str(mb.get("measured","—")) if mb else "—"
            changed = va != vb and va != "—" and vb != "—"
            delta = "[yellow]CHANGED[/yellow]" if changed else "[dim]same[/dim]"
            table.add_row(name, va, vb, delta)

        console.print(table)


def _compare_row(label: str, a: str, b: str) -> None:
    changed = a != b
    style   = "yellow" if changed else "dim"
    console.print(f"  [bold]{label:<12}[/bold]  A: {a:<30}  B: {b:<30}",
                  style=style if changed else "")


# ── replay ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("run_id")
@click.option("--speed", default=0.8, show_default=True,
              help="Seconds to pause between steps.")
def replay(run_id: str, speed: float):
    """Step through a past run for training or demo. Feature #20."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import db.store as store

    store.init_db()
    raw = store.get_report_json(run_id)
    if not raw:
        console.print(f"[red]No report found for run {run_id}[/red]")
        sys.exit(1)

    report = json.loads(raw)
    tr     = report.get("test_run", {})
    triage = report.get("triage", {})
    exec_r = report.get("execution")

    console.rule(f"[bold]Replay: {tr.get('test_case_name','—')[:50]}[/bold]")
    console.print(f"Verdict:    [bold]{tr.get('verdict','—')}[/bold]")
    console.print(f"Root cause: {triage.get('root_cause_summary','—')}")
    console.print()

    if not exec_r or not exec_r.get("steps"):
        console.print("[yellow]No execution steps recorded in this run.[/yellow]")
        return

    steps = exec_r["steps"]
    console.print(f"Replaying [bold]{len(steps)}[/bold] steps at {speed}s/step\n")

    for step in steps:
        status = step.get("status","—")
        icon   = "✅" if status == "passed" else "❌"
        console.print(f"  {icon} [bold]Step {step.get('step_number','?')}:[/bold] "
                      f"{step.get('description','—')}")
        console.print(f"     [dim]$ {step.get('command','—')}[/dim]")
        out = step.get("actual_output") or step.get("stdout","")
        if out:
            for line in out.strip().splitlines()[:3]:
                console.print(f"     [dim]{line}[/dim]")
        time.sleep(speed)

    all_ok = all(s.get("status") == "passed" for s in steps)
    if all_ok:
        console.print("\n[bold green]✅ Replay complete — all steps passed.[/bold green]")
    else:
        console.print("\n[bold red]❌ Replay complete — some steps failed.[/bold red]")


# ── Rich helpers ──────────────────────────────────────────────────────────────

def _print_run_summary(run) -> None:
    table = Table(box=box.SIMPLE, show_header=False, padding=(0,1))
    table.add_column("key", style="bold dim", width=16)
    table.add_column("val")
    table.add_row("Test case",  run.test_case_name)
    table.add_row("Test ID",    run.test_case_id)
    table.add_row("Technology", run.dut.access_technology)
    table.add_row("Device",     f"{run.dut.vendor} {run.dut.model} ({run.dut.firmware})")
    table.add_row("Verdict",    Text(run.verdict.value,
                                    style="red bold" if run.verdict.value=="FAIL" else "green bold"))
    table.add_row("Metrics",    f"{len(run.metrics)} ({sum(1 for m in run.metrics if m.verdict.value=='FAIL')} failed)")
    table.add_row("Log events", str(len(run.error_logs)))
    console.print(Panel(table, title="[bold]Test Run[/bold]", border_style="#1A3557"))


def _print_triage_result(triage) -> None:
    sev   = triage.severity.value
    style = SEV_COLOUR.get(sev, "dim")

    console.print(f"\n[{style}]▶ {sev} SEVERITY[/{style}]  "
                  f"confidence: [bold]{triage.confidence:.0%}[/bold]")
    console.print(Panel(
        f"[bold]{triage.root_cause_summary}[/bold]\n\n{triage.root_cause_detail}",
        title="[bold]Root Cause[/bold]", border_style="red" if sev=="CRITICAL" else "yellow",
    ))

    if triage.recommendations:
        console.print("[bold]Recommendations:[/bold]")
        for rec in triage.recommendations:
            effort = f"  [dim]({rec.estimated_effort})[/dim]" if rec.estimated_effort else ""
            console.print(f"  {rec.priority}. [bold]{rec.action}[/bold]{effort}")
            console.print(f"     [dim]{rec.rationale}[/dim]")


def _print_fix_script(script) -> None:
    console.print(f"\n[bold]Fix Script:[/bold] {script.title}\n")
    for step in script.steps:
        console.print(f"  [cyan]Step {step.step_number}[/cyan]: {step.description}")
        console.print(f"  [dim]$ {step.command}[/dim]")
        if step.rollback_command:
            console.print(f"  [dim]↩ rollback: {step.rollback_command}[/dim]")
        console.print()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
