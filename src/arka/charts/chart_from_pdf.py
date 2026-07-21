#!/usr/bin/env python3
"""Extract tabular data from PDFs and render bar, line, or pie charts."""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

from arka.charts.plot import BAR_COLOR, default_output, open_image, parse_numeric_value, plot_bar, plot_pie, _require_matplotlib
from arka.charts.tabular import aggregate_rows, resolve_columns, suggest_chart_type

_PDF_RE = re.compile(r"(?i)(?:['\"]?([\w./~-]+\.pdf)['\"]?|\b([\w./~-]+\.pdf)\b)")
_CHART_TYPES = frozenset({"auto", "bar", "line", "pie"})


def _require_pypdf():
    try:
        from pypdf import PdfReader  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "pypdf is required for chart_from_pdf.\n"
            "Install: pip install pypdf  or  pip install 'arka-agent[pdf-tools]'"
        ) from exc


def extract_tables_from_pdf(path: Path) -> list[list[list[str]]]:
    """Return tables as row-major string grids (including header when present)."""
    path = path.expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise SystemExit(f"Expected a PDF file: {path}")

    tables: list[list[list[str]]] = []

    try:
        import fitz

        doc = fitz.open(str(path))
        for page_idx in range(len(doc)):
            page = doc.load_page(page_idx)
            finder = page.find_tables()
            for tab in finder.tables:
                grid = tab.extract()
                cleaned = [[str(cell or "").strip() for cell in row] for row in grid if any(str(c or "").strip() for c in row)]
                if len(cleaned) >= 2 and len(cleaned[0]) >= 2:
                    tables.append(cleaned)
        doc.close()
        if tables:
            return tables
    except ImportError:
        pass

    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    cleaned = [[str(cell or "").strip() for cell in row] for row in table if row and any(str(c or "").strip() for c in row)]
                    if len(cleaned) >= 2 and len(cleaned[0]) >= 2:
                        tables.append(cleaned)
        if tables:
            return tables
    except ImportError:
        pass

    _require_pypdf()
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    for page in reader.pages:
        text = page.extract_text() or ""
        for block in re.split(r"\n\s*\n", text):
            rows: list[list[str]] = []
            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue
                if "\t" in line:
                    cells = [c.strip() for c in line.split("\t") if c.strip()]
                else:
                    cells = re.split(r"\s{2,}", line)
                    cells = [c.strip() for c in cells if c.strip()]
                if len(cells) >= 2:
                    rows.append(cells)
            if len(rows) >= 2 and len(rows[0]) >= 2:
                width = max(len(r) for r in rows)
                norm = [r + [""] * (width - len(r)) for r in rows]
                tables.append(norm)

    return tables


def _score_table(grid: list[list[str]]) -> float:
    if len(grid) < 2:
        return 0.0
    cols = len(grid[0])
    numeric_cells = 0
    total_cells = 0
    for row in grid[1:]:
        for cell in row[1:]:
            total_cells += 1
            try:
                parse_numeric_value(cell)
                numeric_cells += 1
            except ValueError:
                pass
    if total_cells == 0:
        return float(len(grid) * cols)
    return len(grid) * cols + numeric_cells * 2


def table_to_rows(grid: list[list[str]]) -> list[dict[str, str]]:
    header = [h.strip() or f"col{i + 1}" for i, h in enumerate(grid[0])]
    rows: list[dict[str, str]] = []
    for raw in grid[1:]:
        if not any(str(c).strip() for c in raw):
            continue
        row = {}
        for idx, key in enumerate(header):
            row[key] = raw[idx].strip() if idx < len(raw) else ""
        rows.append(row)
    return rows


def _plot_simple_line(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    ylabel: str,
    output: Path,
    source: str = "",
) -> Path:
    plt = _require_matplotlib()
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.9), 5.5))
    ax.plot(range(len(labels)), values, marker="o", linewidth=2, color=BAR_COLOR)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title(title or "Trend")
    ax.set_ylabel(ylabel or "Value")
    ax.grid(True, alpha=0.3)
    if source:
        fig.text(0.01, 0.01, f"Source: {source}", fontsize=8, color="#64748b")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output


def pick_best_table(tables: list[list[list[str]]]) -> list[dict[str, str]]:
    if not tables:
        raise SystemExit("No tables found in PDF — try a PDF with structured tables or export to CSV")
    best = max(tables, key=_score_table)
    rows = table_to_rows(best)
    if len(rows) < 2:
        raise SystemExit("Extracted table has too few data rows")
    return rows


def chart_from_pdf(
    pdf_path: Path,
    *,
    output: Path | None = None,
    chart_type: str = "auto",
    by: str | None = None,
    value: str | None = None,
    title: str | None = None,
    table_index: int = 0,
) -> Path:
    tables = extract_tables_from_pdf(pdf_path)
    if table_index > 0:
        if table_index >= len(tables):
            raise SystemExit(f"PDF has {len(tables)} table(s); --table {table_index} is out of range")
        rows = table_to_rows(tables[table_index])
    else:
        rows = pick_best_table(tables)

    label_col, value_col = resolve_columns(rows, by=by, value=value)
    labels, values = aggregate_rows(rows, label_col, value_col)
    kind = chart_type.lower().strip() if chart_type else "auto"
    if kind == "auto":
        kind = suggest_chart_type(labels, values)
    if kind not in {"bar", "line", "pie"}:
        raise SystemExit(f"Unsupported chart type: {kind}")

    chart_title = title or f"{pdf_path.stem} — {value_col}"
    slug = re.sub(r"[^a-z0-9]+", "-", chart_title.lower())[:40] or "pdf-chart"
    out = output.expanduser().resolve() if output else default_output(slug)

    if kind == "pie":
        saved = plot_pie(labels, values, title=chart_title, output=out, source=str(pdf_path.name))
    elif kind == "line":
        saved = _plot_simple_line(
            labels,
            values,
            title=chart_title,
            ylabel=value_col,
            output=out,
            source=str(pdf_path.name),
        )
    else:
        saved = plot_bar(labels, values, title=chart_title, ylabel=value_col, output=out, source=str(pdf_path.name))

    return saved


def nl_to_argv(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    if not re.search(r"(?i)\b(?:chart|graph|plot|visuali[sz]e)\b.*\bpdf\b|\bpdf\b.*\b(?:chart|graph|plot|table)\b", t):
        return []

    m = _PDF_RE.search(t)
    if not m:
        return []
    pdf = m.group(1) or m.group(2)
    argv = [pdf]

    out = re.search(r"(?i)(?:to|as|into|save(?:\s+as)?)\s+(\S+\.(?:png|jpe?g|webp))\b", t)
    if out:
        argv.extend(["-o", out.group(1)])

    if re.search(r"(?i)\bpie\b", t):
        argv.extend(["--type", "pie"])
    elif re.search(r"(?i)\bline\b", t):
        argv.extend(["--type", "line"])
    elif re.search(r"(?i)\bbar\b", t):
        argv.extend(["--type", "bar"])

    by = re.search(r"(?i)\b(?:by|group(?:ed)?\s+by)\s+(\w+)", t)
    if by:
        argv.extend(["--by", by.group(1)])
    val = re.search(r"(?i)\b(?:value|amount|metric|column)\s+(\w+)", t)
    if val:
        argv.extend(["--value", val.group(1)])

    title = re.search(r"(?i)\btitle\s+['\"]([^'\"]+)['\"]", t)
    if title:
        argv.extend(["--title", title.group(1).strip()])

    return argv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arka chart_from_pdf",
        description="Extract tables from a PDF and render a chart (bar, line, or pie).",
    )
    p.add_argument("pdf", help="Input PDF with tabular data")
    p.add_argument("-o", "--output", help="Output image path (.png)")
    p.add_argument(
        "--type",
        choices=sorted(_CHART_TYPES),
        default="auto",
        help="Chart type (default: auto)",
    )
    p.add_argument("--by", help="Label/category column name")
    p.add_argument("--value", help="Numeric value column name")
    p.add_argument("--title", help="Chart title")
    p.add_argument("--table", type=int, default=0, help="Table index when PDF has multiple tables")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv[:1] == ["parse"]:
        parsed = nl_to_argv(" ".join(argv[1:]))
        if not parsed:
            return 1
        print(" ".join(shlex.quote(a) for a in parsed))
        return 0

    if not argv:
        build_parser().print_help()
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)
    pdf = Path(args.pdf).expanduser()
    saved = chart_from_pdf(
        pdf,
        output=Path(args.output).expanduser() if args.output else None,
        chart_type=args.type,
        by=args.by,
        value=args.value,
        title=args.title,
        table_index=args.table,
    )
    print(f"Saved chart: {saved}")
    open_image(saved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
