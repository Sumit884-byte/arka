#!/usr/bin/env python3
"""Shared terminal layout — sections, status lines, tables, result boxes."""

from __future__ import annotations

import os
import sys
from io import StringIO
from typing import Sequence, TextIO

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_CYAN = "\033[36m"

_SECTION_BAR = "━━━"


def output_style() -> str:
    raw = os.environ.get("ARKA_OUTPUT_STYLE", "auto").strip().lower()
    if raw in {"plain", "rich", "auto"}:
        return raw
    return "auto"


def emoji_enabled() -> bool:
    raw = os.environ.get("ARKA_OUTPUT_EMOJI", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def color_enabled(*, stream: TextIO | None = None) -> bool:
    if output_style() == "plain":
        return False
    if os.environ.get("NO_COLOR", "").strip():
        return False
    stream = stream or sys.stdout
    if output_style() == "rich":
        return True
    if not getattr(stream, "isatty", lambda: False)():
        return False
    if os.environ.get("TERM", "").strip().lower() == "dumb":
        return False
    return True


def _styled(text: str, *codes: str) -> str:
    if not codes:
        return text
    return "".join(codes) + text + _RESET


def _status_prefix(kind: str) -> str:
    if kind == "success":
        return ("✓ " if emoji_enabled() else "[ok] ")
    if kind == "error":
        return ("✗ " if emoji_enabled() else "[error] ")
    if kind == "warn":
        return ("⚠ " if emoji_enabled() else "[warn] ")
    return ("→ " if emoji_enabled() else "  ")


def _terminal_width(default: int = 100) -> int:
    try:
        if sys.stdout.isatty():
            return max(40, min(os.get_terminal_size().columns, 120))
    except OSError:
        pass
    return default


def section(title: str, *, stream: TextIO | None = None) -> None:
    """Print a section header (━━━ title ━━━)."""
    out = stream or sys.stdout
    title = (title or "Arka").strip()
    line = f"{_SECTION_BAR} {title} {_SECTION_BAR}"
    if color_enabled(stream=out):
        line = _styled(line, _BOLD, _CYAN)
    print(line, file=out)
    print(file=out)


def success(msg: str, *, stream: TextIO | None = None) -> None:
    out = stream or sys.stdout
    line = f"{_status_prefix('success')}{msg}"
    if color_enabled(stream=out):
        line = _styled(line, _GREEN)
    print(line, file=out)


def error(msg: str, *, stream: TextIO | None = None) -> None:
    out = stream or sys.stderr
    line = f"{_status_prefix('error')}{msg}"
    if color_enabled(stream=out):
        line = _styled(line, _RED)
    print(line, file=out)


def warn(msg: str, *, stream: TextIO | None = None) -> None:
    out = stream or sys.stderr
    line = f"{_status_prefix('warn')}{msg}"
    if color_enabled(stream=out):
        line = _styled(line, _YELLOW)
    print(line, file=out)


def info(msg: str, *, stream: TextIO | None = None) -> None:
    out = stream or sys.stderr
    line = f"{_status_prefix('info')}{msg}"
    if color_enabled(stream=out):
        line = _styled(line, _BLUE)
    print(line, file=out)


def _indent_body(text: str, *, indent: str = "  ") -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.rstrip()
        lines.append(f"{indent}{stripped}" if stripped else "")
    return "\n".join(lines)


def result_box(title: str, body: str, *, stream: TextIO | None = None, open_ui: bool = False) -> None:
    """Section header plus indented body (markdown-aware when styled)."""
    out = stream or sys.stdout
    section(title, stream=out)
    text = (body or "").strip()
    if not text:
        return
    plain = not color_enabled(stream=out)
    try:
        from arka.core.markdown_style import maybe_style_markdown

        styled = maybe_style_markdown(text, plain=plain)
        if styled != text and not plain:
            print(styled, file=out)
        else:
            print(_indent_body(text), file=out)
    except ImportError:
        print(_indent_body(text), file=out)

    if open_ui or os.environ.get("ARKA_OPEN_UI", "").strip().lower() in {"1", "true", "yes", "on"}:
        push_to_viewer(text, title=title)


def push_to_viewer(content: str, *, format_hint: str | None = None, title: str = "Output") -> dict[str, str] | None:
    """Open content in the local Arka Output Viewer."""
    try:
        from arka.web.output_viewer.cli import open_content_in_viewer

        result = open_content_in_viewer(content, fmt=format_hint, title=title)
        info(f"Opened output viewer: {result.get('output')}", stream=sys.stderr)
        return result
    except Exception as exc:
        warn(f"Could not open output viewer: {exc}")
        return None


def _plain_table(headers: Sequence[str], rows: Sequence[Sequence[str]], *, stream: TextIO) -> None:
    print("\t".join(headers), file=stream)
    for row in rows:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        print("\t".join(padded[: len(headers)]), file=stream)


def _rich_table(headers: Sequence[str], rows: Sequence[Sequence[str]], *, stream: TextIO) -> bool:
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        return False

    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=_terminal_width(), highlight=False)
    table_obj = Table(show_header=True, header_style="bold cyan", show_edge=False, pad_edge=False)
    for header in headers:
        table_obj.add_column(str(header), overflow="fold")
    for row in rows:
        cells = [str(cell) for cell in row]
        cells += [""] * max(0, len(headers) - len(cells))
        table_obj.add_row(*cells[: len(headers)])
    console.print(table_obj)
    rendered = buf.getvalue().rstrip("\n")
    if rendered:
        print(rendered, file=stream)
    return True


def _ansi_table(headers: Sequence[str], rows: Sequence[Sequence[str]], *, stream: TextIO) -> None:
    str_rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(str(h)) for h in headers]
    for row in str_rows:
        for idx, cell in enumerate(row[: len(headers)]):
            widths[idx] = max(widths[idx], len(cell))

    header_cells = []
    for idx, header in enumerate(headers):
        cell = str(header).ljust(widths[idx])
        header_cells.append(_styled(cell, _BOLD, _CYAN) if color_enabled(stream=stream) else cell)
    print("  ".join(header_cells), file=stream)

    rule = "  ".join("-" * widths[idx] for idx in range(len(headers)))
    print(_styled(rule, _DIM) if color_enabled(stream=stream) else rule, file=stream)

    for row in str_rows:
        cells = []
        for idx in range(len(headers)):
            value = row[idx] if idx < len(row) else ""
            cells.append(value.ljust(widths[idx]))
        print("  ".join(cells), file=stream)


def table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    stream: TextIO | None = None,
) -> None:
    """Aligned table on TTY; tab-separated when piped or plain."""
    out = stream or sys.stdout
    headers = [str(h) for h in headers]
    if not headers:
        return
    if not color_enabled(stream=out):
        _plain_table(headers, rows, stream=out)
        return
    if output_style() in {"auto", "rich"} and _rich_table(headers, rows, stream=out):
        return
    _ansi_table(headers, rows, stream=out)


def list_items(items: Sequence[str], *, bullet: str = "•", stream: TextIO | None = None) -> None:
    """Indented bullet list."""
    out = stream or sys.stdout
    marker = bullet if emoji_enabled() or bullet != "•" else "-"
    for item in items:
        line = f"  {marker} {item}"
        if color_enabled(stream=out):
            line = f"  {_styled(marker, _GREEN)} {item}"
        print(line, file=out)
