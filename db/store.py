"""
db/store.py — SQLite-backed run history. Zero external deps beyond stdlib.

Schema: one lightweight 'runs' row per pipeline execution.
Full report JSON stored as blob for replay.

TODO (Step 7): Alembic migrations if we graduate to Postgres.
"""
from __future__ import annotations
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.models import RunRecord, RunStatus, Severity, Verdict

DB_PATH = Path("data/triage.db")

DDL = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    source_file TEXT,
    test_case   TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ingested',
    root_cause  TEXT,
    severity    TEXT,
    report_json TEXT
);
"""

@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

def init_db() -> None:
    with _conn() as con:
        con.executescript(DDL)

def upsert_run(record: RunRecord, report_json: str | None = None) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO runs (id,created_at,source_file,test_case,verdict,status,root_cause,severity,report_json)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status, root_cause=excluded.root_cause,
                 severity=excluded.severity, report_json=excluded.report_json""",
            (str(record.id), record.created_at.isoformat(), record.source_file,
             record.test_case, record.verdict.value, record.status.value,
             record.root_cause, record.severity.value if record.severity else None, report_json),
        )

def list_runs(limit: int = 50) -> list[RunRecord]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_to_record(r) for r in rows]

def count_pending() -> int:
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS count FROM runs WHERE status IN (?, ?)",
            (RunStatus.SCRIPTED.value, RunStatus.APPROVED.value),
        ).fetchone()
    return int(row["count"]) if row else 0

def get_all_runs(limit: int = 50) -> list[RunRecord]:
    return list_runs(limit)

def get_dashboard_stats() -> dict[str, float | int]:
    init_db()
    runs = list_runs(500)
    now = datetime.now(timezone.utc)
    today = now.date()
    yesterday = today - timedelta(days=1)
    week_start = now - timedelta(days=7)

    runs_today = sum(1 for run in runs if run.created_at.date() == today)
    runs_yesterday = sum(1 for run in runs if run.created_at.date() == yesterday)
    runs_week = sum(1 for run in runs if run.created_at >= week_start)
    resolved = sum(1 for run in runs if run.status in (RunStatus.EXECUTED, RunStatus.REPORTED))
    pending = count_pending()

    return {
        "runs_today": runs_today,
        "runs_delta": runs_today - runs_yesterday,
        "resolved": resolved,
        "resolve_rate": (resolved / len(runs) * 100) if runs else 0,
        "pending": pending,
        "runs_week": runs_week,
        "avg_daily": runs_week / 7,
        "api_cost_today": round(runs_today * 0.06, 2),
    }

def get_recent_runs(limit: int = 6) -> list[dict[str, str]]:
    init_db()
    status_map = {
        RunStatus.EXECUTED: "resolved",
        RunStatus.REPORTED: "resolved",
        RunStatus.SCRIPTED: "pending",
        RunStatus.APPROVED: "pending",
    }
    return [
        {
            "run_id": str(run.id),
            "status": status_map.get(run.status, "failed" if run.verdict == Verdict.FAIL else "pending"),
            "name": run.test_case,
            "severity": run.severity.value if run.severity else "",
            "time": run.created_at.strftime("%H:%M"),
        }
        for run in list_runs(limit)
    ]

def get_failure_categories(days: int = 30) -> list[dict[str, int | str]]:
    init_db()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    runs = [run for run in list_runs(500) if run.created_at >= since and run.root_cause]
    labels = Counter(" ".join((run.root_cause or "").split()[:3]) or "Other" for run in runs)
    total = sum(labels.values())
    if total == 0:
        return []
    return [
        {"label": label, "pct": round(count / total * 100)}
        for label, count in labels.most_common(5)
    ]

def clear_run_history(delete_reports: bool = True) -> None:
    """Remove persisted run rows and optional saved report JSON files."""
    init_db()
    with _conn() as con:
        con.execute("DELETE FROM runs")

    if delete_reports:
        runs_dir = Path("data/runs")
        if runs_dir.exists():
            for report_path in runs_dir.glob("*.json"):
                report_path.unlink()

def get_run(run_id: str) -> RunRecord | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return _to_record(row) if row else None

def get_report_json(run_id: str) -> str | None:
    with _conn() as con:
        row = con.execute("SELECT report_json FROM runs WHERE id=?", (run_id,)).fetchone()
    return row["report_json"] if row else None

def _to_record(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        id          = row["id"],
        created_at  = datetime.fromisoformat(row["created_at"]),
        source_file = row["source_file"],
        test_case   = row["test_case"],
        verdict     = Verdict(row["verdict"]),
        status      = RunStatus(row["status"]),
        root_cause  = row["root_cause"],
        severity    = Severity(row["severity"]) if row["severity"] else None,
    )
