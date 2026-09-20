"""Atomic, append-only writer for ``ops.log`` — never Edit / match-replace the log.

``ops.log`` is a single per-repo, human-readable audit stream (read at boot, tailed).
It is git-tracked with ``**/ops.log merge=union`` so concurrent *commits* auto-merge.
The remaining friction is *writes*: a match-and-replace edit on a file another live
session is appending **races** ("file modified since read") and can clobber/interleave.

The cure is to **append atomically, never edit**. This helper makes that structural:
one ``O_APPEND`` write syscall per entry => no read-modify-write, no race, correct
6-field format by construction.

It enforces **format + atomicity**, NOT the **role-slug honesty** rule (see
``core/conventions/ops-log.md``): ``role`` is the caller's honest assertion of the
active persona — the helper cannot verify it.

Sibling of ``core/fleet``'s ``write_json_atomic`` — the same "atomic at the write path"
idea in a different shape (single-file text append here, per-file JSON there).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

FIELD_SEP = " | "


def utc_stamp(now: datetime | None = None) -> str:
    """Canonical ops.log timestamp: minute-precision UTC with a ``Z`` suffix."""
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%MZ")


def format_entry(
    role: str, action: str, scope: str, detail: str, outcome: str = "done",
    *, now: datetime | None = None,
) -> str:
    """Build one canonical line: ``ts | role | action | scope | detail | outcome``.

    ``detail`` is whitespace-collapsed so one entry stays one line (the log is
    line-oriented; an embedded newline would split the audit record).
    """
    detail = " ".join(str(detail).split())
    return FIELD_SEP.join([utc_stamp(now), role, action, scope, detail, outcome])


def resolve_log(log_path: str | os.PathLike | None = None, start: str | os.PathLike | None = None) -> Path:
    """The ops.log to write: explicit ``log_path``, else the first ``docs/ops.log`` found
    walking up from ``start`` (or cwd)."""
    if log_path:
        return Path(log_path)
    cur = Path(start or Path.cwd()).resolve()
    for base in [cur, *cur.parents]:
        cand = base / "docs" / "ops.log"
        if cand.exists():
            return cand
    raise FileNotFoundError("docs/ops.log not found from cwd; pass --log / log_path")


def append_line(path: str | os.PathLike, line: str) -> None:
    """Atomic append: a single ``O_APPEND`` write (no read-modify-write, no Edit race)."""
    data = (line.rstrip("\n") + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def append_entry(
    role: str, action: str, scope: str, detail: str, outcome: str = "done",
    *, log_path: str | os.PathLike | None = None, now: datetime | None = None,
) -> str:
    """Format + atomically append one entry; return the line written."""
    line = format_entry(role, action, scope, detail, outcome, now=now)
    append_line(resolve_log(log_path), line)
    return line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="oplog", description="atomic append to ops.log (never Edit the log)")
    ap.add_argument("--role", required=True, help="active persona slug (honest — see ops-log.md)")
    ap.add_argument("--action", required=True, help="operation verb, e.g. ADD/FIX/PUSH")
    ap.add_argument("--scope", required=True, help="engine/connectors/docs/... or env")
    ap.add_argument("--detail", required=True, help="what happened + outcome counts")
    ap.add_argument("--outcome", default="done", help="terminal status (done/ok/fail)")
    ap.add_argument("--log", default=None, help="ops.log path (default: find docs/ops.log upward)")
    args = ap.parse_args(argv)
    try:
        line = append_entry(args.role, args.action, args.scope, args.detail, args.outcome, log_path=args.log)
    except (FileNotFoundError, OSError) as e:
        print(f"[oplog] {e}", file=sys.stderr)
        return 2
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
