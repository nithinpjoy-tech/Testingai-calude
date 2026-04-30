#!/usr/bin/env python3
"""
scripts/healthcheck.py
Pre-flight check — runs before demo or deployment.
Verifies: Python version, all imports, API key present, DB writable, sample files exist.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "
errors = 0


def check(label: str, fn) -> None:
    global errors
    try:
        result = fn()
        msg = f" — {result}" if result and result is not True else ""
        print(f"  {PASS}  {label}{msg}")
    except Exception as exc:
        print(f"  {FAIL}  {label} — {exc}")
        errors += 1


print("\nTest Triage Tool — Health Check\n" + "─" * 42)

# ── Python version ────────────────────────────────────────────────────────────
check("Python >= 3.11",
      lambda: (
          sys.version_info >= (3, 11)
          or (_ for _ in ()).throw(RuntimeError(f"Got {sys.version}"))
      ))

# ── Core imports ──────────────────────────────────────────────────────────────
check("anthropic", lambda: __import__("anthropic").__version__)
check("pydantic",  lambda: __import__("pydantic").__version__)
check("streamlit", lambda: __import__("streamlit").__version__)
check("plotly",    lambda: __import__("plotly").__version__)
check("click",     lambda: __import__("click").__version__)

# ── Internal modules ──────────────────────────────────────────────────────────
check("core.models",        lambda: __import__("core.models"))
check("core.ingestor",      lambda: __import__("core.ingestor"))
check("core.triage_engine", lambda: __import__("core.triage_engine"))
check("core.remediation",   lambda: __import__("core.remediation"))
check("core.executor",      lambda: __import__("core.executor"))
check("db.store",           lambda: __import__("db.store"))

# ── API key ───────────────────────────────────────────────────────────────────
def _check_api_key():
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment or .env")
    if not key.startswith("sk-ant-"):
        raise RuntimeError("ANTHROPIC_API_KEY looks malformed (should start with sk-ant-)")
    return f"...{key[-6:]}"
check("ANTHROPIC_API_KEY", _check_api_key)

# ── Database ──────────────────────────────────────────────────────────────────
def _check_db():
    import db.store as store
    store.init_db()
    records = store.list_runs(limit=1)
    return f"OK ({len(records)} existing runs)"
check("SQLite DB init", _check_db)

# ── Sample files ──────────────────────────────────────────────────────────────
check("Sample JSON", lambda: (
    __import__("pathlib").Path("samples/pppoe_vlan_mismatch.json").exists()
    or (_ for _ in ()).throw(FileNotFoundError("samples/pppoe_vlan_mismatch.json"))
))
check("Sample XML", lambda: (
    __import__("pathlib").Path("samples/pppoe_vlan_mismatch.xml").exists()
    or (_ for _ in ()).throw(FileNotFoundError("samples/pppoe_vlan_mismatch.xml"))
))

# ── Ingestor smoke test ───────────────────────────────────────────────────────
def _check_ingest():
    from core.ingestor import ingest
    run = ingest("samples/pppoe_vlan_mismatch.json")
    assert run.verdict.value == "FAIL"
    assert run.dut.model == "NF18ACV"
    return f"run_id={run.run_id[:8]}…"
check("Ingestor (JSON parse)", _check_ingest)

# ── Summary ───────────────────────────────────────────────────────────────────
print("─" * 42)
if errors == 0:
    print(f"  {PASS}  All checks passed — ready to run.\n")
    print("  Start UI:    make run")
    print("  Docker:      make run-docker\n")
    sys.exit(0)
else:
    print(f"\n  {FAIL}  {errors} check(s) failed — fix before running.\n")
    sys.exit(1)
