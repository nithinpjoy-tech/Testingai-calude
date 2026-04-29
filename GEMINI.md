# GEMINI.md — Antigravity-specific rules
# These override AGENTS.md for Antigravity agents only.

## Preferred model assignment
- **Complex tasks** (new features, refactoring, debugging): Claude Sonnet 4.6
- **Boilerplate / formatting / docs**: Gemini 3 Flash
- **Architecture decisions**: Claude Opus 4.6 or Gemini 3.1 Pro

## Agent behaviour in this project

### Always use Planning mode for:
- Any change to core/models.py (cascades everywhere)
- Any change to Claude prompts (triage_engine.py or remediation.py system prompts)
- New test files
- Docker/deployment changes

### Fast mode is fine for:
- Adding a new CLI command (follow existing patterns in cli/main.py)
- Fixing a single test
- Updating requirements.txt
- UI copy/label changes

## Manager view — suggested parallel agents
When working on the CLI wiring task, you can dispatch:
- Agent A: wire `analyse` command end-to-end
- Agent B: write `tests/test_cli.py` covering the new commands
These two are independent and can run in parallel.

## Artifact expectations
For any task in this project, generate:
1. **Implementation plan** listing files to change and why
2. **Code diff** or new file content
3. **Test verification** — run `pytest tests/ -q` and include the pass/fail count

## Verification step (always run after any change)
```bash
python3 -m pytest tests/ -q --tb=short
python3 scripts/healthcheck.py
```
Both must pass before marking a task complete.

## What NOT to do
- Do not change the Claude model string — it must stay `claude-sonnet-4-20250514`
- Do not add new Pydantic models outside `core/models.py`
- Do not add `import openai` — this project uses Anthropic only
- Do not mock the simulated NTD in tests — use `reset_simulated_ntd()` instead
- Do not run the Streamlit UI in headless check — use the healthcheck script
