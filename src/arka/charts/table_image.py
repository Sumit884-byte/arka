"""Render tabular data (CSV/TSV/JSON) as a PNG table image."""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path

from arka.charts.tabular import _column_names, load_rows

_TABLE_NL = re.compile(
    r"(?i)"
    r"\b(?:table|tabular|grid|spreadsheet)\b.*\b(?:as\s+)?(?:an?\s+)?(?:image|png|picture|photo|snapshot)\b"
    r"|\b(?:render|export|save|generate|make|create|turn|convert)\b.*\btable\b.*\b(?:to|as|into)\b.*\b(?:image|png)\b"
    r"|\btable\s+(?:image|png|snapshot)\b"
    r"|\b(?:image|png)\b.*\b(?:of|from)\b.*\btable\b"
    r"|\bchart\s+table\b|\btable\s+chart\b"
)

_MAX_CELL_LEN = 48
_HEADER_BG = "#2563eb"
_HEADER_FG = "#ffffff"
_ROW_ALT = "#f1f5f9"
_ROW_BASE = "#ffffff"
_GRID = "#cbd5e1"


def wants_table_image(text: str) -> bool:
    from arka.charts.dataset_nl import _nl_work_text

    work = _nl_work_text(text or "")
    return bool(_TABLE_NL.search(work))


def _truncate(value: str, *, limit: int = _MAX_CELL_LEN) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def rows_to_grid(
    rows: list[dict[str, str]],
    *,
    columns: list[str] | None = None,
) -> tuple[list[str], list[list[str]]]:
    cols = [c for c in (columns or _column_names(rows)) if c]
    if not cols:
        raise SystemExit("No columns found in data")
    grid = [[_truncate(row.get(col, "")) for col in cols] for row in rows]
    return cols, grid


def _load_inline_csv(data: str) -> tuple[list[str], list[list[str]]]:
    raw = data.strip()
    if not raw:
        raise SystemExit("--data is empty")
    sample = raw.splitlines()[0]
    delimiter = "\t" if "\t" in sample and sample.count("\t") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(raw), delimiter=delimiter)
    rows_iter = list(reader)
    if not rows_iter:
        raise SystemExit("No rows in --data")
    header = [str(c).strip() for c in rows_iter[0]]
    if not any(header):
        raise SystemExit("Inline data needs a header row")
    body: list[list[str]] = []
    for row in rows_iter[1:]:
        if not any(str(c or "").strip() for c in row):
            continue
        padded = list(row) + [""] * (len(header) - len(row))
        body.append([_truncate(str(padded[i] if i < len(padded) else "")) for i in range(len(header))])
    if not body:
        raise SystemExit("Inline data needs at least one data row")
    return header, body


def plot_table(
    columns: list[str],
    rows: list[list[str]],
    *,
    title: str = "",
    output: Path,
    source: str = "",
    max_rows: int = 50,
) -> Path:
    from arka.charts.plot import _require_matplotlib

    plt = _require_matplotlib()
    shown = rows[: max(1, max_rows)]
    ncols = max(1, len(columns))
    nrows = len(shown)

    fig_w = max(6.0, min(28.0, 0.75 * ncols + 2.5))
    fig_h = max(2.5, min(36.0, 0.38 * (nrows + 1) + 1.8))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")

    if title:
        ax.set_title(title, fontsize=14, fontweight="bold", pad=14, color="#0f172a")

    table = ax.table(
        cellText=shown,
        colLabels=[_truncate(c, limit=32) for c in columns],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.35)

    for (row_idx, col_idx), cell in table.get_celld().items():
        cell.set_edgecolor(_GRID)
        cell.set_linewidth(0.6)
        if row_idx == 0:
            cell.set_facecolor(_HEADER_BG)
            cell.set_text_props(color=_HEADER_FG, fontweight="bold")
        else:
            cell.set_facecolor(_ROW_ALT if row_idx % 2 == 0 else _ROW_BASE)
            cell.set_text_props(color="#0f172a")

    footer_parts: list[str] = []
    if source:
        footer_parts.append(f"Source: {source}")
    if len(rows) > len(shown):
        footer_parts.append(f"Showing {len(shown)} of {len(rows)} rows")
    if footer_parts:
        fig.text(0.01, 0.012, " · ".join(footer_parts), fontsize=7, color="#64748b")

    out = output.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def table_from_file(
    data_path: Path,
    *,
    output: Path | None = None,
    title: str | None = None,
    columns: list[str] | None = None,
    max_rows: int = 50,
) -> Path:
    from arka.charts.plot import default_output
    import re as _re

    path = data_path.expanduser().resolve()
    rows = load_rows(path)
    cols, grid = rows_to_grid(rows, columns=columns)
    chart_title = title or path.stem.replace("_", " ").replace("-", " ").title()
    slug = _re.sub(r"[^a-z0-9]+", "-", chart_title.lower())[:40] or "table"
    out = output.expanduser().resolve() if output else default_output(slug)
    return plot_table(
        cols,
        grid,
        title=chart_title,
        output=out,
        source=path.name,
        max_rows=max_rows,
    )


def table_from_inline(
    data: str,
    *,
    output: Path | None = None,
    title: str | None = None,
    max_rows: int = 50,
) -> Path:
    from arka.charts.plot import default_output
    import re as _re

    cols, grid = _load_inline_csv(data)
    chart_title = title or "Table"
    slug = _re.sub(r"[^a-z0-9]+", "-", chart_title.lower())[:40] or "table"
    out = output.expanduser().resolve() if output else default_output(slug)
    return plot_table(
        cols,
        grid,
        title=chart_title,
        output=out,
        source="inline data",
        max_rows=max_rows,
    )


def nl_to_table_argv(text: str) -> list[str] | None:
    from arka.charts.dataset_nl import extract_data_file_path, parse_dataset_axes

    t = (text or "").strip()
    if not t:
        return None
    from arka.charts.dataset_nl import _nl_work_text

    work_stripped = _nl_work_text(t)
    table_cue = bool(
        _TABLE_NL.search(work_stripped)
        or re.search(r"(?i)\bchart\s+table\b|\btable\s+(?:from|of)\b", work_stripped)
    )
    if not table_cue:
        return None
    axes = parse_dataset_axes(t)
    if axes and (axes.by or axes.value):
        return None
    path = extract_data_file_path(t)
    if not path:
        return ["table"]
    argv: list[str] = ["table", path]
    title = re.search(r"(?i)\btitle\s+['\"]([^'\"]+)['\"]", t)
    if title:
        argv.extend(["--title", title.group(1).strip()])
    out = re.search(r"(?i)(?:-o|--output|(?:to|as|into|save(?:\s+as)?)\s+)(\S+\.(?:png|jpe?g|webp))\b", t)
    if out:
        argv.extend(["-o", out.group(1)])
    max_rows = re.search(r"(?i)\b(?:max|limit)\s+(\d+)\s+rows?\b", t)
    if max_rows:
        argv.extend(["--max-rows", max_rows.group(1)])
    return argv


def cmd_table(args: argparse.Namespace) -> int:
    from arka.charts.plot import open_image

    try:
        if getattr(args, "data", ""):
            saved = table_from_inline(
                args.data,
                output=Path(args.output).expanduser() if args.output else None,
                title=args.title or None,
                max_rows=args.max_rows,
            )
        elif getattr(args, "file", ""):
            columns = [c.strip() for c in (args.columns or "").split(",") if c.strip()] or None
            saved = table_from_file(
                Path(args.file).expanduser(),
                output=Path(args.output).expanduser() if args.output else None,
                title=args.title or None,
                columns=columns,
                max_rows=args.max_rows,
            )
        else:
            print("Usage: arka chart table FILE.csv [--title …] [-o out.png]", file=sys.stderr)
            return 1
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Saved table image: {saved}")
    open_image(saved)
    return 0


def add_table_subparser(sub) -> None:
    p = sub.add_parser("table", help="Render CSV/TSV/JSON as a PNG table image")
    p.add_argument("file", nargs="?", default="", help="CSV, TSV, or JSON file")
    p.add_argument(
        "--data",
        default="",
        help='Inline CSV/TSV text with header row (alternative to FILE)',
    )
    p.add_argument("--columns", default="", help="Comma-separated column subset")
    p.add_argument("--title", default="", help="Table title")
    p.add_argument("--max-rows", type=int, default=50, help="Max data rows to render (default 50)")
    p.add_argument("-o", "--output", help="Output PNG path")
    p.set_defaults(func=cmd_table)
