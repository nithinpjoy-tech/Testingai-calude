"""Fix SyntaxError in ui/pages/p02_triage.py line 121.
Python < 3.12 doesn't allow same quote char inside f-string expressions.
Replace inner double-quotes with curly/typographic single-quotes.
"""
from pathlib import Path

target = Path(__file__).parent.parent / "ui" / "pages" / "p02_triage.py"
content = target.read_text(encoding="utf-8")

# The bad line uses nested " inside an f"..." — replace the filename quotes
# with typographic single quotes (U+2018 / U+2019) which look nice and parse fine.
bad  = '    label    = f"\u25b6  Run AI Triage on  "{filename}"" if not result else f"\u21ba  Re-run AI Triage on  "{filename}""\n'
good = '    label    = (f"\u25b6  Run AI Triage on  \u2018{filename}\u2019" if not result\n              else f"\u21ba  Re-run AI Triage on  \u2018{filename}\u2019")\n'

if bad not in content:
    print("Pattern NOT found — checking current line 121:")
    lines = content.splitlines()
    print(repr(lines[120]))
    raise SystemExit(1)

fixed = content.replace(bad, good)
target.write_text(fixed, encoding="utf-8")
print("Done — p02_triage.py patched successfully.")

# Quick syntax check
import py_compile, tempfile, shutil
tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
tmp.close()
shutil.copy(target, tmp.name)
try:
    py_compile.compile(tmp.name, doraise=True)
    print("Syntax check: OK")
except py_compile.PyCompileError as e:
    print(f"Syntax check FAILED: {e}")
finally:
    Path(tmp.name).unlink(missing_ok=True)
