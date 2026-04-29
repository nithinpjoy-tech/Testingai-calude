"""
db/store.py — SQLite-backed run history. Zero external deps beyond stdlib.

Schema: one lightweight 'runs' row per pipeline execution.
Full report JSON stored as blob for replay.

TODO (Step 7): Alembic migrations if we graduate to Postgres.
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import datetime
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
            (record.id, record.created_at.isoformat(), record.source_file,
             record.test_case, record.verdict.value, record.status.value,
             record.root_cause, record.severity.value if record.severity else None, report_json),
        )

def list_runs(limit: int = 50) -> list[RunRecord]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_to_record(r) for r in rows]

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
