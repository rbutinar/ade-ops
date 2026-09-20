"""Convert a Databricks ``.py`` notebook source to a Jupyter ``.ipynb`` (v4).

Databricks exports notebooks in a ``.py`` format with structural directives:
- ``# Databricks notebook source`` header (first line)
- ``# COMMAND ----------`` separators between cells
- ``# MAGIC %md`` / ``# MAGIC %sql`` / ``# MAGIC %pip`` / etc. for magics

Microsoft Fabric notebooks are uploaded in ``.ipynb`` format (definition parts
encoded InlineBase64). This module produces the structural translation only:
it converts the cell layout and preserves the magic commands. Semantic
rewrites (``dbutils.fs`` → ``mssparkutils.fs``, Unity Catalog → Lakehouse
paths, etc.) are out of scope - those belong to the migration assessment
flow, where they are surfaced as gap items rather than silently rewritten.

Usage::

    from pathlib import Path
    from core.parsers.databricks_to_ipynb import convert_source, read_and_convert

    # From a string
    nb = convert_source(databricks_py_text)

    # From a file (.py Databricks-style or already-.ipynb pass-through)
    nb = read_and_convert(Path("ingest_sales_raw.py"))
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

DATABRICKS_HEADER = "# Databricks notebook source"
CELL_SEPARATOR = "# COMMAND ----------"
MAGIC_PREFIX = "# MAGIC"
MAGIC_PREFIX_SPACE = "# MAGIC "  # most lines have a trailing space


# Databricks Python sometimes accepts source where string literals contain
# raw newline bytes (0x0A) rather than the `\n` escape - e.g. the API
# returns `print("<LF>X")` for what was authored as `print("\nX")` in the
# Databricks UI. Standard Python (and therefore Fabric Spark) raises a
# SyntaxError on this. We normalise these here, BEFORE cell splitting, so
# the converted ipynb is deploy-ready.
#
# A regex over the full source is fragile: a string close followed by a
# newline looks identical to an in-string newline at the byte level
# (`"x")\nprint(` vs `"a\nb"`). We use a small state machine instead, which
# tracks single- vs triple-quoted contexts and only rewrites the newline
# bytes that appear *inside* a single-line string literal.

def _normalize_string_literals(source: str) -> str:
    '''Escape raw newline bytes that sit inside single-line string literals.

    Triple-quoted strings (the multi-line form with three quote chars in a
    row, either double or single) are pass-through: Python allows literal
    newlines in them by design. Comments are also untouched. Inside a
    single-line "..." or "..."-style literal, a raw 0x0A byte gets
    rewritten as the two-char escape backslash-n.
    '''
    out: list[str] = []
    i = 0
    n = len(source)
    in_sl_quote: str | None = None       # `"` or `'` while inside a single-line string
    in_tq_quote: str | None = None       # `"""` or `'''` while inside a triple-quoted string
    in_comment = False
    while i < n:
        ch = source[i]
        if in_comment:
            out.append(ch)
            if ch == "\n":
                in_comment = False
            i += 1
            continue
        if in_tq_quote is not None:
            # Look for closing triple quote.
            if source.startswith(in_tq_quote, i):
                out.append(in_tq_quote)
                i += 3
                in_tq_quote = None
                continue
            out.append(ch)
            i += 1
            continue
        if in_sl_quote is not None:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(source[i + 1])
                i += 2
                continue
            if ch == in_sl_quote:
                out.append(ch)
                in_sl_quote = None
                i += 1
                continue
            if ch == "\n":
                # Raw newline inside a single-line string → escape it.
                out.append("\\n")
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        # Outside any string/comment.
        if ch == "#":
            in_comment = True
            out.append(ch)
            i += 1
            continue
        if ch in ('"', "'"):
            # Triple-quoted?
            if source.startswith(ch * 3, i):
                in_tq_quote = ch * 3
                out.append(ch * 3)
                i += 3
                continue
            in_sl_quote = ch
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_magic_prefix(line: str) -> str:
    """Remove the ``# MAGIC`` / ``# MAGIC `` prefix from a single line.

    Databricks emits ``# MAGIC <content>`` for non-empty payload and bare
    ``# MAGIC`` for blank lines within a magic block.
    """
    if line.startswith(MAGIC_PREFIX_SPACE):
        return line[len(MAGIC_PREFIX_SPACE):]
    if line.startswith(MAGIC_PREFIX):  # bare "# MAGIC" or "# MAGIC\n"
        return line[len(MAGIC_PREFIX):].lstrip(" ")
    return line


def _source_as_list(lines: Iterable[str]) -> list[str]:
    """Convert lines to ipynb ``source`` format: list of strings with ``\\n``
    at the end of every line except the last.

    ``nbformat`` accepts either a list of lines or a single string; the list
    form is canonical and survives round-trips cleanly.
    """
    items = list(lines)
    if not items:
        return []
    out = [s + "\n" for s in items[:-1]]
    out.append(items[-1])
    return out


def _build_markdown_cell(body_lines: list[str]) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": _source_as_list(body_lines),
    }


def _build_code_cell(body_lines: list[str]) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": _source_as_list(body_lines),
    }


def _classify_and_render(cell_text: str) -> dict | None:
    """Turn the raw text of one Databricks cell into a Jupyter cell dict.

    Returns ``None`` for empty cells so they can be filtered out.
    """
    lines = cell_text.strip("\n").splitlines()
    # Trim leading/trailing blank lines.
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return None

    # Is this a MAGIC block? Check the first non-blank line.
    first = lines[0]
    if first.startswith(MAGIC_PREFIX):
        stripped_first = _strip_magic_prefix(first).rstrip()

        if stripped_first.startswith("%md"):
            # Markdown cell - body is everything AFTER the %md directive.
            body = [_strip_magic_prefix(ln).rstrip() for ln in lines[1:]]
            # The %md line itself may carry inline content after the keyword
            # (rare but possible). Capture it.
            inline = stripped_first[len("%md"):].lstrip()
            if inline:
                body.insert(0, inline)
            return _build_markdown_cell(body)

        if stripped_first.startswith("%sql"):
            body_lines = [_strip_magic_prefix(ln).rstrip() for ln in lines[1:]]
            inline = stripped_first[len("%sql"):].lstrip()
            payload = (["%%sql"] + ([inline] if inline else []) + body_lines)
            return _build_code_cell(payload)

        # Other magics (%pip, %run, %sh, %scala, %r, ...): preserve as-is in
        # a code cell - Fabric and Jupyter both understand line magics with
        # ``%`` and cell magics with ``%%``. We keep the Databricks single-%
        # form (line magic) because the magic directive came alone on its
        # line in the source - converting blindly to ``%%`` would change
        # semantics for short magics like ``%pip``.
        body = [stripped_first] + [_strip_magic_prefix(ln).rstrip() for ln in lines[1:]]
        return _build_code_cell(body)

    # Plain code cell.
    return _build_code_cell(lines)


def convert_source(databricks_py_text: str) -> dict:
    """Convert a Databricks ``.py`` source string to an ipynb v4 dict.

    The returned dict is JSON-serializable and validates against
    ``nbformat.v4`` (verified at test time).
    """
    text = databricks_py_text.replace("\r\n", "\n")
    text = _normalize_string_literals(text)
    # Drop the leading header if present.
    if text.startswith(DATABRICKS_HEADER):
        text = text[len(DATABRICKS_HEADER):].lstrip("\n")

    raw_cells = text.split(CELL_SEPARATOR)
    cells: list[dict] = []
    for raw in raw_cells:
        cell = _classify_and_render(raw)
        if cell is not None:
            cells.append(cell)

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def read_and_convert(path: Path | str) -> dict:
    """Read a notebook file and return its ipynb v4 dict.

    ``.py`` files are converted via ``convert_source``. ``.ipynb`` files are
    parsed and returned as-is (pass-through), so callers can use the same
    entry point regardless of source format.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".ipynb":
        return json.loads(text)
    return convert_source(text)
