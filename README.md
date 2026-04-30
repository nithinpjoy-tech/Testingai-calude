# Test Triage Tool — Milestone 1 Framework

AI-powered test failure troubleshooter for access network testing.
Root cause analysis via Claude, approval-gated fix scripts, step-by-step execution.

## Architecture

```
samples/          ← Sample test result files (JSON, XML, LOG)
core/
  models.py       ← Pydantic domain models (single source of truth)
  config.py       ← YAML + env var config loader
  logger.py       ← Structured JSON logger + audit trail
  ingestor.py     ← Format normaliser: JSON / XML / raw log → TestRun
  triage_engine.py← Claude call: TestRun → TriageResult
  remediation.py  ← Claude call: TriageResult → FixScript
  executor.py     ← Step-by-step runner (dry / simulated / live)
  reporter.py     ← Assembles RunReport, saves JSON
db/
  store.py        ← SQLite run history
ui/
  app.py          ← Streamlit entry point (routing + theme + severity banner)
  components/     ← Reusable UI widgets
  pages/          ← p01 Dashboard | p02 Triage | p03 Remediation | p04 Compare | p05 Replay
cli/
  main.py         ← Click CLI: analyse | history | compare | replay
notifications/
  webhook.py      ← Slack / Teams stub
config/
  settings.yaml   ← All tunable parameters
tests/
  test_models.py  ← Smoke tests (no LLM calls)
```

## Pipeline Flow

```
Input file → ingestor → TestRun
                           │
                           ▼
                    triage_engine (Claude) → TriageResult
                           │
                           ▼
                    remediation (Claude) → FixScript
                           │
                           ▼
                    [Operator Approval Gate]
                           │
                           ▼
                    executor → ExecutionResult
                           │
                           ▼
                    reporter → RunReport (JSON) → DB
                           │
                           ▼
                    notifications (Slack / Teams stub)
```

## Features in this milestone

| # | Feature | Status |
|---|---------|--------|
| 1–12 | Must-have UI (dashboard, triage, remediation, comparison, replay) | Framework |
| 15 | Severity notification banner | ✅ Done |
| 16 | Run comparison (diff two runs) | Framework |
| 18 | Slack/Teams webhook | Stub |
| 19 | CLI mode | Framework |
| 20 | Replay mode | Framework |

## Setup

```bash
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env

pip install -r requirements.txt
streamlit run ui/app.py
```

## CLI

```bash
python -m cli.main analyse samples/pppoe_vlan_mismatch.json
python -m cli.main history
python -m cli.main compare <run-id-a> <run-id-b>
python -m cli.main replay <run-id>
```

## Tests

```bash
pytest tests/
```

## Demo issue — PPPoE VLAN mismatch on FTTP

- NTD configured: VLAN 10
- OLT service profile expects: VLAN 2
- Result: all PADI frames silently dropped at S-VLAN translation
- Fix: update NTD wan0 VLAN from 10 → 2, verify PPPoE reaches lcp-up
