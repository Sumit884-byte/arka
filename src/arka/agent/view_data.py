#!/usr/bin/env python3
"""Pretty-print CSV/TSV in the terminal with per-column ANSI colors and save exports."""

from __future__ import annotations

import argparse
import csv
import io
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from arka.agent.generate_data import SUPPORTED_FORMATS, format_rows, format_rows_xlsx
from arka.paths import generated_data_dir

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"view_data|view_csv|show_csv|pretty_csv|display_csv|"
    r"(?:view|show|display|print|pretty\s+print|open)\s+(?:me\s+)?(?:the\s+)?"
    r"(?:colou?red\s+)?(?:csv|tsv|table)(?:\s+file)?|"
    r"(?:colou?red|color)\s+(?:csv|tsv|table)\b|"
    r"(?:export|save)\s+(?:the\s+)?(?:csv|tsv)\b|"
    r"show\s+(?:me\s+)?[\w./~-]+\.(?:csv|tsv)\b"
    r")\b"
)

_EXCLUDE_RE = re.compile(
    r"(?i)\b("
    r"data_ask|ask_data|query_data|analyze_data|"
    r"how many|count|total|average|sum|max|min|top|who|what|which|"
    r"summarize|summary|analyze|analyse|query|ask|explain|inspect|explore|describe"
    r")\b"
)

_FILE_RE = re.compile(
    r"(?i)(?:['\"]([^'\"]+\.(?:csv|tsv))['\"]"
    r"|((?:[\w.-]+/)+[\w.-]+\.(?:csv|tsv))"
    r"|([~./][^\s'\"]+\.(?:csv|tsv))"
    r"|([^\s'\"/\\]+\.(?:csv|tsv))\b)"
)

_FORMAT_RE = re.compile(
    r"(?i)\b(?:as|in|to|format|save\s+as)\s+"
    r"(csv|json|jsonl|tsv|yaml|yml|xml|xlsx|sql|markdown|md)\b"
)

_FORMATS_RE = re.compile(
    r"(?i)\b(?:formats?|export)\s+([a-z0-9_,\s-]+)"
)

_RESET = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"

_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_RED = "\033[31m"
_WHITE = "\033[37m"

_COLUMN_STYLES: dict[str, str] = {
    "pmid": _YELLOW,
    "pmcid": _YELLOW,
    "doi": _YELLOW,
    "id": _YELLOW,
    "title": _GREEN,
    "name": _GREEN,
    "journal": _BLUE,
    "source": _BLUE,
    "publication": _BLUE,
    "year": _MAGENTA,
    "date": _MAGENTA,
    "url": _CYAN,
    "link": _CYAN,
    "authors": _RED,
    "author": _RED,
    "abstract": _WHITE,
}

_FALLBACK_COLORS = (_YELLOW, _GREEN, _BLUE, _MAGENTA, _CYAN, _RED, _WHITE)


def _normalize(text: str) -> str:
    return text.replace("\n", " ").replace("\r", " ").strip()


def _style_for_column(name: str, *, index: int = 0) -> str:
    key = name.strip().lower().replace(" ", "_")
    return _COLUMN_STYLES.get(key, _FALLBACK_COLORS[index % len(_FALLBACK_COLORS)])


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return ","


def _read_rows(source: io.TextIOBase, delimiter: str | None) -> tuple[list[str], list[list[str]]]:
    text = source.read()
    if not text.strip():
        return [], []
    delim = delimiter or _detect_delimiter(text[:4096])
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows:
        return [], []
    header = [_normalize(cell) for cell in rows[0]]
    body = [[_normalize(cell) for cell in row] for row in rows[1:] if any(cell.strip() for cell in row)]
    return header, body


def _rows_as_dicts(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        out.append({name: (row[idx] if idx < len(row) else "") for idx, name in enumerate(header)})
    return out


def _normalize_format(fmt: str | None) -> str:
    if not fmt:
        return ""
    fmt = fmt.lower().strip()
    if fmt == "md":
        return "markdown"
    if fmt == "yml":
        return "yaml"
    return fmt


def _parse_formats(text: str, *, explicit: str | None = None, formats: str | None = None) -> list[str]:
    found: list[str] = []
    if formats:
        for part in re.split(r"[,;\s]+", formats):
            part = _normalize_format(part)
            if part in SUPPORTED_FORMATS and part not in found:
                found.append(part)
    if explicit:
        fmt = _normalize_format(explicit)
        if fmt in SUPPORTED_FORMATS and fmt not in found:
            found.insert(0, fmt)
    if not found:
        for match in _FORMAT_RE.finditer(text):
            fmt = _normalize_format(match.group(1))
            if fmt and fmt in SUPPORTED_FORMATS and fmt not in found:
                found.append(fmt)
        m_multi = _FORMATS_RE.search(text)
        if m_multi:
            for part in re.split(r"[,;\s]+", m_multi.group(1)):
                fmt = _normalize_format(part)
                if fmt in SUPPORTED_FORMATS and fmt not in found:
                    found.append(fmt)
    return found or ["csv"]


def _output_stem(source_path: Path | None) -> str:
    if source_path and source_path.suffix:
        return source_path.stem
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"table-{stamp}"


def save_table_exports(
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    out_dir: Path | None = None,
    stem: str,
    formats: Sequence[str],
    table: str = "exported_data",
) -> list[Path]:
    target = (out_dir or generated_data_dir()).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    dict_rows = _rows_as_dicts(header, rows)
    saved: list[Path] = []

    for fmt in formats:
        fmt = _normalize_format(fmt)
        if fmt not in SUPPORTED_FORMATS:
            continue
        path = target / f"{stem}.{fmt if fmt != 'markdown' else 'md'}"
        if fmt == "xlsx":
            path.write_bytes(format_rows_xlsx(dict_rows, table=table))
        else:
            path.write_text(format_rows(dict_rows, fmt, table=table), encoding="utf-8")
        saved.append(path.resolve())
    return saved


def format_save_message(paths: Sequence[Path], *, plain: bool = False) -> str:
    if not paths:
        return ""
    folder = paths[0].parent
    lines = [f"Saved to {folder}:"]
    for path in paths:
        lines.append(f"  {path.name}")
    body = "\n".join(lines)
    if plain:
        return body
    return f"{_CYAN}{body}{_RESET}"


def format_colored_table(
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    plain: bool = False,
    max_rows: int | None = 50,
    separator: str = ", ",
) -> str:
    if not header:
        return "(empty table)"

    shown = list(rows if max_rows is None else rows[:max_rows])
    lines: list[str] = []

    def paint(text: str, style: str, *, bold: bool = False) -> str:
        if plain or not style:
            return text
        prefix = f"{_BOLD}{style}" if bold else style
        return f"{prefix}{text}{_RESET}"

    header_cells = [
        paint(name, _style_for_column(name, index=idx), bold=True)
        for idx, name in enumerate(header)
    ]
    lines.append(separator.join(header_cells))

    for row in shown:
        cells = []
        for idx, name in enumerate(header):
            value = row[idx] if idx < len(row) else ""
            cells.append(paint(value, _style_for_column(name, index=idx)))
        lines.append(separator.join(cells))

    if max_rows is not None and len(rows) > max_rows:
        more = len(rows) - max_rows
        lines.append(f"... {more} more row(s) in source (all rows saved to file)")

    return "\n".join(lines)


def render_csv(
    source: io.TextIOBase,
    *,
    plain: bool = False,
    max_rows: int | None = 50,
    delimiter: str | None = None,
) -> tuple[str, list[str], list[list[str]]]:
    header, rows = _read_rows(source, delimiter)
    text = format_colored_table(header, rows, plain=plain, max_rows=max_rows)
    return text, header, rows


def preview_file(
    path: str | Path,
    *,
    max_rows: int = 50,
    plain: bool = True,
    delimiter: str | None = None,
) -> dict[str, object]:
    """Load a CSV/TSV file and return a structured preview (MCP-friendly)."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise FileNotFoundError(f"file not found: {file_path}")
    limit = max(1, min(int(max_rows or 50), 500))
    with file_path.open(encoding="utf-8", errors="replace", newline="") as fh:
        text, header, rows = render_csv(
            fh,
            plain=plain,
            max_rows=limit,
            delimiter=delimiter,
        )
    shown = rows if limit is None else rows[:limit]
    return {
        "path": str(file_path.resolve()),
        "columns": header,
        "row_count": len(rows),
        "shown_rows": len(shown),
        "table": text,
    }


def _extract_path(text: str) -> str | None:
    matches = []
    for m in _FILE_RE.finditer(text):
        path = next(g for g in m.groups() if g)
        matches.append(path)
    if not matches:
        return None
    return max(matches, key=len)


def wants_view_data(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if _EXCLUDE_RE.search(clean):
        return False
    try:
        from arka.agent.data_ask import wants_data_ask

        if wants_data_ask(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.agent.generate_data import wants_generate_data

        if wants_generate_data(clean):
            return False
    except ImportError:
        pass
    if re.search(r"(?i)\b(?:view_data|view_csv|show_csv|pretty_csv|display_csv)\b", clean):
        return bool(_extract_path(clean) or not sys.stdin.isatty())
    if not _TRIGGER_RE.search(clean):
        return False
    return bool(_extract_path(clean))


def route_command(text: str) -> str:
    if not wants_view_data(text):
        return ""
    argv = nl_to_argv(text)
    if not argv and not sys.stdin.isatty():
        return "view_data"
    if not argv:
        return ""
    return "view_data " + " ".join(shlex.quote(a) for a in argv)


def nl_to_argv(text: str) -> list[str]:
    clean = text.strip()
    if not clean:
        return []

    plain = bool(re.search(r"(?i)\b(?:no[- ]?color|plain|monochrome)\b", clean))
    no_save = bool(re.search(r"(?i)\b(?:no[- ]?save|stdout[- ]?only|display[- ]?only)\b", clean))
    max_rows = 50
    m_rows = re.search(r"(?i)\b(?:top|first|max)\s+(\d+)\s+rows?\b", clean)
    if m_rows:
        max_rows = max(1, int(m_rows.group(1)))

    path = _extract_path(clean)
    formats = _parse_formats(clean)

    argv: list[str] = []
    if plain:
        argv.append("--plain")
    if no_save:
        argv.append("--no-save")
    if max_rows != 50:
        argv.extend(["--max-rows", str(max_rows)])
    if len(formats) == 1:
        argv.extend(["--format", formats[0]])
    elif len(formats) > 1:
        argv.extend(["--formats", ",".join(formats)])
    if path:
        argv.append(path)
    return argv


def _process_table(
    source: io.TextIOBase,
    *,
    source_path: Path | None,
    plain: bool,
    max_rows: int | None,
    delimiter: str | None,
    save: bool,
    formats: Sequence[str],
    out_dir: Path | None,
) -> int:
    display, header, rows = render_csv(
        source,
        plain=plain,
        max_rows=max_rows,
        delimiter=delimiter,
    )
    print(display)
    if not save or not header:
        return 0

    stem = _output_stem(source_path)
    table = re.sub(r"[^a-zA-Z0-9_]", "_", stem.lower()) or "exported_data"
    try:
        saved = save_table_exports(
            header,
            rows,
            out_dir=out_dir,
            stem=stem,
            formats=formats,
            table=table,
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    msg = format_save_message(saved, plain=plain)
    if msg:
        print()
        print(msg)
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    formats = _parse_formats("", explicit=args.format, formats=args.formats)
    out_dir = Path(args.output_dir).expanduser() if args.output_dir else None
    save = not args.no_save

    if args.file:
        path = Path(args.file).expanduser()
        if not path.is_file():
            print(f"view_data: file not found: {path}", file=sys.stderr)
            return 1
        with path.open(newline="") as fh:
            return _process_table(
                fh,
                source_path=path,
                plain=args.plain,
                max_rows=args.max_rows,
                delimiter=args.delimiter,
                save=save,
                formats=formats,
                out_dir=out_dir,
            )

    if not sys.stdin.isatty():
        return _process_table(
            sys.stdin,
            source_path=None,
            plain=args.plain,
            max_rows=args.max_rows,
            delimiter=args.delimiter,
            save=save,
            formats=formats,
            out_dir=out_dir,
        )

    print("Usage: view_data <file.csv> [--format json] [--formats csv,json,yaml]", file=sys.stderr)
    print("       cat data.csv | view_data", file=sys.stderr)
    print(f"       Saves to {generated_data_dir()}/ by default", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pretty-print CSV/TSV with colored columns and save exports")
    sub = p.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to view_data command")
    p_route.add_argument("text", nargs="+")
    p_route.set_defaults(func=_cmd_route)

    p_parse = sub.add_parser("parse", help="Map NL to CLI args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=_cmd_parse)

    p_view = sub.add_parser("view", help="View a CSV/TSV file")
    p_view.add_argument("file", nargs="?", help="CSV/TSV file (or pipe via stdin)")
    p_view.add_argument("--max-rows", "-n", type=int, default=50, help="Rows to show in terminal (all rows still saved)")
    p_view.add_argument("--plain", action="store_true", help="Disable ANSI colors")
    p_view.add_argument("--no-save", action="store_true", help="Terminal display only; do not write files")
    p_view.add_argument("--format", "-f", default=None, help=f"Save format (default: csv). One of: {', '.join(SUPPORTED_FORMATS)}")
    p_view.add_argument("--formats", default=None, help="Comma-separated save formats, e.g. csv,json,yaml")
    p_view.add_argument("--output-dir", "-o", default=None, help=f"Output folder (default: {generated_data_dir()})")
    p_view.add_argument("--delimiter", "-d", default=None, help="Field delimiter (auto-detect by default)")
    p_view.set_defaults(func=cmd_view)

    return p


def _build_view_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pretty-print CSV/TSV with colored columns and save exports")
    p.add_argument("file", nargs="?", help="CSV/TSV file (or pipe via stdin)")
    p.add_argument("--max-rows", "-n", type=int, default=50, help="Rows to show in terminal (all rows still saved)")
    p.add_argument("--plain", action="store_true", help="Disable ANSI colors")
    p.add_argument("--no-save", action="store_true", help="Terminal display only; do not write files")
    p.add_argument("--format", "-f", default=None, help=f"Save format (default: csv). One of: {', '.join(SUPPORTED_FORMATS)}")
    p.add_argument("--formats", default=None, help="Comma-separated save formats, e.g. csv,json,yaml")
    p.add_argument("--output-dir", "-o", default=None, help=f"Output folder (default: {generated_data_dir()})")
    p.add_argument("--delimiter", "-d", default=None, help="Field delimiter (auto-detect by default)")
    return p


def _cmd_route(args: argparse.Namespace) -> int:
    route = route_command(" ".join(args.text))
    if route:
        print(route)
        return 0
    return 1


def _cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv if argv is not None else sys.argv[1:])
    if argv_list and argv_list[0] in ("route", "parse", "view"):
        args = build_parser().parse_args(argv_list)
        return int(args.func(args))

    if argv_list and wants_view_data(" ".join(argv_list)):
        nl_args = nl_to_argv(" ".join(argv_list))
        if nl_args or not sys.stdin.isatty():
            parser = _build_view_parser()
            if nl_args:
                args = parser.parse_args(nl_args)
            else:
                args = parser.parse_args([])
            return cmd_view(args)

    parser = _build_view_parser()
    args = parser.parse_args(argv_list)
    return cmd_view(args)


if __name__ == "__main__":
    raise SystemExit(main())
