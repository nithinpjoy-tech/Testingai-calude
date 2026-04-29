# Opening this project in Google Antigravity

## 1. Install Antigravity (if you haven't)
Download from: https://antigravity.google/download
Sign in with your personal Gmail account.

## 2. Open the project
File → Open Folder → select the `nbn-test-tool` folder.
Antigravity will auto-detect `AGENTS.md` and `GEMINI.md` and load them as workspace rules.

## 3. Set your API key
```bash
cp .env.example .env
# Open .env and paste your ANTHROPIC_API_KEY
```

## 4. Install dependencies
Open the **Terminal** panel (Ctrl+`) and run:
```bash
make setup
```

## 5. Verify everything is working
```bash
python3 scripts/healthcheck.py
```
Expect 15/16 green (API key check needs your real key).

## 6. Run the UI locally
```bash
make run
# → http://localhost:8501
```

## 7. Run with Docker (recommended for demo)
```bash
make run-docker
# → http://localhost:8501
```

---

## Picking up development in Antigravity

### Current state
Milestone 1 is complete. 62 tests passing. Full pipeline wired.
The only remaining item is **wiring the CLI** (`cli/main.py`).

### Recommended first task in Manager view
Open **Agent Manager** → New Task → paste this:

```
Wire the CLI analyse command in cli/main.py end-to-end.
The command should:
1. Call core.ingestor.ingest(file) to get a TestRun
2. Call core.triage_engine.analyse(run) to get a TriageResult
3. Print root cause + recommendations to the terminal using Rich
4. If --no-exec flag is not set, call core.remediation.generate_fix_script()
5. Show the fix script steps and prompt for approval (unless --approve flag)
6. Execute via core.executor.execute(script) streaming step results
7. Call core.reporter.build_report() + save() + db.store.upsert_run()
8. Print a final summary

Use Planning mode. Reference AGENTS.md for the exact function signatures.
Write tests in tests/test_cli.py using Click's CliRunner and mocked Claude calls.
Verify with: pytest tests/ -q
```

### Autonomy preset recommendation
Use **Review-driven development** — the agent checks in before writing to files.
This project has live Claude API calls — you want to review the plan before it runs.

---

## Project cheat sheet

| Task | Command |
|---|---|
| Run tests | `make test` |
| Start UI | `make run` |
| Start Docker | `make run-docker` |
| Health check | `python3 scripts/healthcheck.py` |
| Demo (no API) | Load XML sample → Triage → note: needs ANTHROPIC_API_KEY |
| Lint | `make lint` |

## Key files for the agent to read first
- `AGENTS.md` — full project context (auto-loaded)
- `core/models.py` — all data models
- `core/triage_engine.py` — how Claude is called
- `cli/main.py` — what needs to be wired
