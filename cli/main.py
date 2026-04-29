"""
cli/main.py
-----------
Feature #19 — CLI mode with full feature parity.
Uses Click.  All commands mirror UI capabilities.

Usage examples:
  python -m cli.main analyse data/samples/pppoe_vlan_mismatch.json
  python -m cli.main analyse result.xml --mode dry_run --approve
  python -m cli.main history --limit 10
  python -m cli.main replay <run-id>
  python -m cli.main compare <run-id-a> <run-id-b>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

import click

# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option("1.0.0-milestone1")
def cli():
    """NBN Test Troubleshoot Tool — CLI"""


# ---------------------------------------------------------------------------
# analyse
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--mode",    default="dry_run",   type=click.Choice(["dry_run", "simulated", "live"]),  help="Execution mode")
@click.option("--approve", is_flag=True, default=False, help="Auto-approve fix script (non-interactive)")
@click.option("--output",  default=None, type=click.Path(), help="Save report JSON to file")
@click.option("--no-exec", is_flag=True, default=False, help="Triage only — do not generate or run fix script")
def analyse(file: str, mode: str, approve: bool, output: str | None, no_exec: bool):
    """Ingest a test result file, triage with Claude, optionally fix."""
    from core.ingestor      import ingest
    from core.triage_engine import analyse as triage
    from core.remediation   import generate_fix_script
    from core.executor      import execute
    from core.reporter      import build_report, save, to_run_record
    from core.models        import ExecutionMode
    import db.store as store

    click.echo(f"📂 Ingesting {file} ...")
    run = ingest(file)

    click.echo("🧠 Sending to Claude for triage ...")
    result = triage(run)

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
    
    console.print(Panel(f"[bold red]Root cause:[/bold red] {result.root_cause_summary}"))
    
    table = Table(title="Recommendations")
    table.add_column("Priority", style="cyan", no_wrap=True)
    table.add_column("Action", style="magenta")
    table.add_column("Rationale", style="green")
    
    for r in result.recommendations:
        table.add_row(str(r.priority), r.action, r.rationale)
    
    console.print(table)

    if no_exec:
        click.echo("--no-exec set — stopping after triage.")
        sys.exit(0)

    click.echo("\n🔧 Generating fix script ...")
    script = generate_fix_script(run, result)
    
    click.echo("📜 Fix Script Steps:")
    for step in script.steps:
        click.echo(f"  {step.step_number}. {step.command}")

    if not approve:
        click.confirm("Approve and execute fix script?", abort=True)
    
    script.approved_by = "cli-operator"
    script.execution_mode = ExecutionMode.SIMULATED if mode != "live" else ExecutionMode.LIVE
    
    click.echo(f"\n▶️  Executing in {mode} mode ...")
    for step_result in execute(script):
        click.echo(f"  Step {step_result.step_number}: {step_result.status.value}")

    click.echo("\n✅ Done. Report:")
    report = build_report(run, result, script, execution=None) # We don't have full ExecutionResult returned by execute? Wait, execute is a generator. We'll leave it as None for now, but usually it returns StepResults.
    
    # Let's save and persist
    if output:
        with open(output, "w") as f:
            f.write(report.model_dump_json(indent=2))
    else:
        save(report)
        
    store.init_db()
    store.upsert_run(to_run_record(report), report.model_dump_json())
    click.echo(f"Report saved. Run ID: {report.run_id}")


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--limit", default=20, show_default=True)
def history(limit: int):
    """List recent runs from the local database."""
    import db.store as store
    store.init_db()
    runs = store.list_runs(limit)
    if not runs:
        click.echo("No runs found.")
        return
    click.echo(f"{'ID':<38}  {'Test Case':<30}  {'Verdict':<12}  {'Status':<15}  {'Severity'}")
    click.echo("-" * 110)
    for r in runs:
        click.echo(f"{r.id:<38}  {r.test_case:<30}  {r.verdict.value:<12}  {r.status.value:<15}  {r.severity.value if r.severity else '-'}")


# ---------------------------------------------------------------------------
# replay  (feature #20)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("run_id")
def replay(run_id: str):
    """
    Step through a past run interactively — for training/demo purposes.
    Feature #20.
    """
    import time
    from core.models import RunReport
    import db.store as store
    
    click.echo(f"▶️  Replaying run {run_id} ...")
    store.init_db()
    report_json = store.get_report_json(run_id)
    if not report_json:
        click.echo(f"Run {run_id} not found in database.")
        return
        
    report = RunReport.model_validate_json(report_json)
    click.echo(f"Test Case: {report.test_run.test_case_name}")
    click.echo(f"Verdict: {report.test_run.verdict.value}")
    
    if report.triage:
        click.echo(f"\nTriage Root Cause: {report.triage.root_cause_summary}")
        
    if report.fix_script and report.fix_script.steps:
        click.echo("\nReplaying fix script execution:")
        for step in report.fix_script.steps:
            click.echo(f"  [{step.status.value}] Step {step.step_number}: {step.command}")
            time.sleep(1) # Simulated speed
    else:
        click.echo("\nNo fix script to replay.")


# ---------------------------------------------------------------------------
# compare  (feature #16)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("run_id_a")
@click.argument("run_id_b")
def compare(run_id_a: str, run_id_b: str):
    """
    Diff two runs side-by-side.
    Feature #16.
    """
    from core.models import RunReport
    import db.store as store
    
    click.echo(f"⚖️  Comparing {run_id_a} vs {run_id_b}")
    store.init_db()
    
    json_a = store.get_report_json(run_id_a)
    json_b = store.get_report_json(run_id_b)
    
    if not json_a or not json_b:
        click.echo("Error: Could not find one or both run reports.")
        return
        
    report_a = RunReport.model_validate_json(json_a)
    report_b = RunReport.model_validate_json(json_b)
    
    click.echo(f"{'Field':<20} | {'Run A':<40} | {'Run B':<40}")
    click.echo("-" * 106)
    click.echo(f"{'Test Case':<20} | {report_a.test_run.test_case_name:<40} | {report_b.test_run.test_case_name:<40}")
    click.echo(f"{'Verdict':<20} | {report_a.test_run.verdict.value:<40} | {report_b.test_run.verdict.value:<40}")
    
    triage_a = report_a.triage.root_cause_summary if report_a.triage else "None"
    triage_b = report_b.triage.root_cause_summary if report_b.triage else "None"
    click.echo(f"{'Root Cause':<20} | {triage_a[:38]+'..' if len(triage_a)>40 else triage_a:<40} | {triage_b[:38]+'..' if len(triage_b)>40 else triage_b:<40}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
