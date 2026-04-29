# AGENTS.md — NBN Test Triage Tool
# Read by Antigravity, Cursor, Claude Code, and all compatible AI agents.
# Last updated: Milestone 1 complete.

## Project purpose
AI-powered test failure triage and remediation tool for NBN (National Broadband Network)
access network testing. Ingests test result files (JSON/XML), calls Claude to identify
root cause, generates an ordered fix script, executes it step-by-step against a device
(simulated or live), and saves a structured RunReport.

## Tech stack
- Python 3.11+
- Pydantic v2 (models), Streamlit 1.56 (UI), Click (CLI)
- Anthropic SDK — model: `claude-sonnet-4-20250514` (never change without updating all files)
- SQLite via stdlib sqlite3 (no ORM — db/store.py is raw SQL)
- pytest for all tests — zero real API calls in tests (mock with pytest-mock)

## Directory structure
```
core/
  models.py         — ALL Pydantic models (single source of truth — never duplicate)
  config.py         — YAML + env loader
  logger.py         — JSON structured logger + audit trail
  ingestor.py       — JSON/XML → TestRun (DONE)
  triage_engine.py  — Claude call → TriageResult (DONE)
  remediation.py    — Claude call → FixScript (DONE)
  executor.py       — Step-by-step runner + simulated NTD state machine (DONE)
  reporter.py       — Assembles RunReport, saves JSON (DONE)
db/
  store.py          — SQLite CRUD for RunRecord (DONE)
ui/
  app.py            — Streamlit entry point (DONE)
  components/       — sidebar.py, severity_banner.py (DONE)
  pages/            — p01_dashboard through p05_replay (DONE)
cli/
  main.py           — Click CLI: analyse, history, compare, replay (STUBS — next task)
notifications/
  webhook.py        — Slack/Teams stub (DONE — POST not yet implemented)
samples/
  pppoe_vlan_mismatch.json  — Primary demo file (PPPoE VLAN 10 vs 2)
  pppoe_vlan_mismatch.xml   — Same scenario, XML format
  pppoe_vlan_mismatch.log   — Same scenario, raw log format
tests/
  test_models.py        — DONE
  test_ingestor.py      — DONE
  test_triage_engine.py — DONE (16 tests, all mocked)
  test_remediation.py   — DONE (16 tests, all mocked)
  test_executor.py      — DONE (16 tests, simulated NTD)
config/
  settings.yaml     — All tunable parameters
scripts/
  healthcheck.py    — Pre-flight check (run before demo)
```

## Pipeline flow
```
ingest(file) → TestRun
    ↓
triage_engine.analyse(run) → TriageResult          [Claude API]
    ↓
remediation.generate_fix_script(run, triage) → FixScript  [Claude API]
    ↓
[Operator Approval Gate — approved_by must be set]
    ↓
executor.execute(script) → yields StepResult × N   [Simulated NTD]
    ↓
reporter.build_report(...) → RunReport → db.store
    ↓
notifications.webhook.notify(report)               [Slack/Teams stub]
```

## Completed features (Milestone 1)
- [x] Ingestor: JSON + XML (log ingestion raises NotImplementedError — future)
- [x] Triage engine: full system prompt, prompt builder, XML response parser, retry
- [x] Remediation engine: device-specific system prompt, prompt builder, XML parser
- [x] Executor: dry-run + simulated NTD (PPPoE VLAN scenario state machine)
- [x] Executor: rollback() generator for reverse undo
- [x] Reporter: build_report(), save(), to_run_record()
- [x] SQLite: init_db(), upsert_run(), list_runs(), get_run(), get_report_json()
- [x] UI: all 5 pages wired (dashboard, triage, remediation, comparison, replay)
- [x] Severity banner (#15), Run comparison (#16), Slack/Teams stub (#18), Replay (#20)
- [x] Docker: multi-stage Dockerfile, docker-compose.yml, .dockerignore
- [x] 62 tests, all passing, zero real API calls

## Next task — wire the CLI (cli/main.py)
The CLI commands exist as stubs. Wire each one:

### `analyse` command — full pipeline end-to-end
```python
# Pattern to follow:
run    = ingest(file)
result = triage_engine.analyse(run)
script = remediation.generate_fix_script(run, result)
# prompt operator for approval (if not --approve flag)
# execute via executor.execute(script)
# build_report + save + upsert_run
```

### `history` command — already reads DB, just fix RunRecord.id field (it's a str, not UUID)

### `compare` — load two get_report_json() → diff metrics + triage side by side

### `replay` — load get_report_json() → iterate steps with time.sleep(speed)

## Critical rules — never violate

1. **Model name**: always `claude-sonnet-4-20250514` — set via `CLAUDE_MODEL` env var
2. **Approval gate**: `executor.execute()` raises `PermissionError` if `script.approved_by is None`
3. **Single model source**: `core/models.py` only — never define models elsewhere
4. **No real API calls in tests**: mock with `@patch("core.triage_engine.anthropic.Anthropic")`
5. **Simulated NTD state**: call `executor.reset_simulated_ntd()` between test runs
6. **DB path**: `data/triage.db` — overridable via monkeypatch in tests
7. **Audit trail**: `core.logger.audit()` must be called for every LLM call + every step executed
8. **XML output contract**: both Claude prompts return a single XML block — triage returns
   `<triage>`, remediation returns `<fix_script>` — parsers use regex + ElementTree

## Code conventions
- `from __future__ import annotations` at top of every core module
- Type hints everywhere — Pydantic v2 style (`str | None` not `Optional[str]`)
- Logger: `logger = logging.getLogger(__name__)` — never print() in core modules
- No f-strings in format calls where .format() is clearer for long strings
- File-level docstrings on every module explaining purpose and TODOs
- Tests: fixtures in conftest.py for shared objects, `setup_function()` to reset NTD state

## Running the project
```bash
# Local
make setup          # install deps + copy .env.example
make run            # streamlit run ui/app.py
make test           # pytest tests/ -v

# Docker
make run-docker     # docker compose up -d
# → http://localhost:8501

# Health check
python3 scripts/healthcheck.py

# Demo path (no API key needed — but simulated exec only)
# Dashboard → "XML sample" → Triage page → "Analyse with Claude" → Remediation → Execute
```

## Environment variables
```
ANTHROPIC_API_KEY   — required
CLAUDE_MODEL        — optional override (default: claude-sonnet-4-20250514)
TRIAGE_MAX_TOKENS   — default 4096
REMEDIATION_MAX_TOKENS — default 4096
SLACK_WEBHOOK_URL   — optional, activates Slack notifications
TEAMS_WEBHOOK_URL   — optional, activates Teams notifications
APP_ENV             — demo | staging | production
```

## Demo scenario — PPPoE VLAN mismatch on FTTP
- NTD (NetComm NF18ACV, FW 3.7.2-r4) configured with VLAN 10 on wan0
- OLT (Nokia 7360) service profile NBN-RES-100-40 expects VLAN 2
- All PPPoE PADI frames silently dropped at S-VLAN translation
- Fix: `set interface wan0 vlan-id 2 ; commit`
- Post-fix: PPPoE reaches lcp-up, DHCP bound, IP assigned
- The simulated NTD state machine in executor.py models this end-to-end
