"""Allow running the CLI as a module: ``python -m core.cli``."""

import sys

# Force UTF-8 on stdout/stderr so console output (including arrows, emoji,
# accented project names) renders on Windows where the default code page is
# cp1252. Without this, `click.echo("→")` crashes with UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

# Check required Python dependencies before any further imports. A new
# operator running `python -m core.cli preflight` on a fresh venv (or no
# venv) expects preflight to be the first diagnostic — not the first
# crash. Without this check, a missing required dep raises a raw
# ModuleNotFoundError traceback before preflight can even start.
_REQUIRED_DEPS = ("yaml", "httpx", "click")
_missing = []
for _dep in _REQUIRED_DEPS:
    try:
        __import__(_dep)
    except ImportError:
        _missing.append(_dep)
if _missing:
    print(
        "[FAIL] Python dependencies missing: " + ", ".join(_missing) + "\n"
        "       Run: python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass  # truststore optional — falls back to certifi

from core.cli.main import main

if __name__ == "__main__":
    main()
