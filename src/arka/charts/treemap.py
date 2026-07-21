#!/usr/bin/env python3
"""Render treemap visualizations from CSV, JSON, or tabular data."""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

from arka.charts.plot import PIE_COLORS, default_output, open_image, _require_matplotlib
from arka.charts.tabular import aggregate_rows, load_rows, resolve_columns

_DATA_RE = re.compile(
    r"(?i)(?:['\"]?([\w./~-]+\.(?:csv|tsv|json))['\"]?|\b([\w./~-]+\.(?:csv|tsv|json))\b)"
)


def _layout_treemap(
    sizes: list[float],
    x: float,
    y: float,
    dx: float,
    dy: float,
    *,
    horizontal: bool = True,
) -> list[tuple[float, float, float, float]]:
    if not sizes:
        return []
    if len(sizes) == 1:
        return [(x, y, dx, dy)]
    total = sum(sizes)
    if total <= 0:
        return []
    first = sizes[0]
    if horizontal:
        w = dx * first / total
        return [(x, y, w, dy), *_layout_treemap(sizes[1:], x + w, y, dx - w, dy, horizontal=False)]
    h = dy * first / total
    return [(x, y, dx, h), *_layout_treemap(sizes[1:], x, y + h, dx, dy - h, horizontal=True)]


def plot_treemap(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    output: Path,
    source: str = "",
) -> Path:
    plt = _require_matplotlib()
    import matplotlib.patches as mpatches

    pairs = [(lbl, val) for lbl, val in zip(labels, values) if val > 0]
    if len(pairs) < 2:
        raise SystemExit("Treemap needs at least two positive values")
    pairs.sort(key=lambda item: item[1], reverse=True)
    labels = [p[0] for p in pairs]
    values = [p[1] for p in pairs]

    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title(title or "Treemap", pad=12)

    rects = _layout_treemap(values, 0.0, 0.0, 1.0, 1.0)
    total = sum(values)
    for idx, ((rx, ry, rw, rh), label, val) in enumerate(zip(rects, labels, values)):
        color = PIE_COLORS[idx % len(PIE_COLORS)]
        patch = mpatches.Rectangle((rx, ry), rw, rh, facecolor=color, edgecolor="white", linewidth=1.5)
        ax.add_patch(patch)
        pct = 100.0 * val / total if total else 0.0
        if rw * rh >= 0.015:
            ax.text(
                rx + rw / 2,
                ry + rh / 2,
                f"{label}\n{val:g} ({pct:.1f}%)",
                ha="center",
                va="center",
                fontsize=8 if rw * rh < 0.05 else 9,
                color="#0f172a",
                wrap=True,
            )

    if source:
        fig.text(0.01, 0.01, f"Source: {source}", fontsize=8, color="#64748b")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output


def treemap_from_file(
    data_path: Path,
    *,
    output: Path | None = None,
    by: str | None = None,
    value: str | None = None,
    title: str | None = None,
) -> Path:
    rows = load_rows(data_path)
    label_col, value_col = resolve_columns(rows, by=by, value=value)
    labels, values = aggregate_rows(rows, label_col, value_col)
    chart_title = title or f"{data_path.stem} treemap"
    slug = re.sub(r"[^a-z0-9]+", "-", chart_title.lower())[:40] or "treemap"
    out = output.expanduser().resolve() if output else default_output(slug)
    return plot_treemap(labels, values, title=chart_title, output=out, source=data_path.name)


def nl_to_argv(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    if not re.search(
        r"(?i)\b(?:treemap|tree\s*map|nested\s+(?:chart|rectangles?)|hierarchical\s+(?:chart|view))\b",
        t,
    ):
        return []

    m = _DATA_RE.search(t)
    if not m:
        return []
    data = m.group(1) or m.group(2)
    argv = [data]

    out = re.search(r"(?i)(?:to|as|into|save(?:\s+as)?)\s+(\S+\.(?:png|jpe?g|webp))\b", t)
    if out:
        argv.extend(["-o", out.group(1)])

    by = re.search(r"(?i)\b(?:by|group(?:ed)?\s+by)\s+(\w+)", t)
    if by:
        argv.extend(["--by", by.group(1)])
    val = re.search(r"(?i)\b(?:value|amount|metric|size|column)\s+(\w+)", t)
    if val:
        argv.extend(["--value", val.group(1)])

    title = re.search(r"(?i)\btitle\s+['\"]([^'\"]+)['\"]", t)
    if title:
        argv.extend(["--title", title.group(1).strip()])

    return argv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arka treemap",
        description="Create a treemap PNG from CSV, TSV, or JSON data.",
    )
    p.add_argument("data", help="CSV, TSV, or JSON file")
    p.add_argument("-o", "--output", help="Output image path (.png)")
    p.add_argument("--by", help="Label/category column name")
    p.add_argument("--value", help="Numeric value column name")
    p.add_argument("--title", help="Chart title")
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
    saved = treemap_from_file(
        Path(args.data).expanduser(),
        output=Path(args.output).expanduser() if args.output else None,
        by=args.by,
        value=args.value,
        title=args.title,
    )
    print(f"Saved treemap: {saved}")
    open_image(saved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
