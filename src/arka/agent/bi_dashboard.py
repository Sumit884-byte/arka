"""Generate local HTML BI dashboards from CSV/JSON/TSV data and natural-language intent."""
from __future__ import annotations

import argparse
import html
import json
import re
import shlex
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arka.charts.tabular import (
    aggregate_rows,
    load_rows,
    resolve_columns,
    suggest_chart_type,
)

_DATA_EXT = r"(?:csv|tsv|json)"
_FILE_RE = re.compile(
    rf"(?i)(?:['\"]([^'\"]+\.(?:{_DATA_EXT}))['\"]"
    rf"|([~./][^\s'\"]+\.(?:{_DATA_EXT}))"
    rf"|([^\s'\"/\\]+\.(?:{_DATA_EXT}))\b)"
)

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"bi[_\s-]?dashboard|business\s+intelligence\s+dashboard|"
    r"(?:generate|create|build|make)\s+(?:a\s+)?(?:bi\s+)?dashboard|"
    r"dashboard\s+(?:from|for|with|using)\s+(?:my\s+)?(?:data|csv|sales|revenue|metrics?)|"
    r"(?:bi\s+)?dashboard\s+from\s+(?:csv|json|tsv|data|file)|"
    r"visuali[sz]e\s+(?:my\s+)?(?:data|sales|metrics?)\s+(?:as\s+)?dashboard"
    r")\b"
)

_EXCLUDE_RE = re.compile(
    r"(?i)\b("
    r"usage\s+dashboard|skill\s+usage|signoz|grafana|metabase|superset|"
    r"streamlit\s+dashboard|stock\s+dashboard|observability\s+dashboard"
    r")\b"
)

_PIE_WORDS = re.compile(r"(?i)\b(pie|donut|breakdown|proportion|share|percentage|percent)\b")
_LINE_WORDS = re.compile(r"(?i)\b(trend|over\s+time|timeseries|time\s+series|monthly|daily|weekly)\b")
_TABLE_WORDS = re.compile(r"(?i)\b(table|rows?|records?|preview|raw\s+data)\b")

_COLORS = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#14b8a6"]

_PANEL_TEMPLATES: dict[str, dict[str, Any]] = {
    "kpi_cards": {
        "type": "kpi",
        "description": "Headline KPI cards: row count, totals, averages, unique categories",
    },
    "bar_chart": {
        "type": "bar",
        "description": "Bar chart for categorical breakdowns",
    },
    "pie_chart": {
        "type": "pie",
        "description": "Pie chart for small categorical shares",
    },
    "line_chart": {
        "type": "line",
        "description": "Line chart for temporal trends",
    },
    "data_table": {
        "type": "table",
        "description": "Sample table preview of source rows",
    },
}


def _default_output(slug: str = "bi-dashboard") -> Path:
    clean = re.sub(r"[^a-z0-9]+", "-", slug.lower())[:48].strip("-") or "bi-dashboard"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path.home() / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{clean}-{ts}.html"


def extract_file_path(text: str) -> str:
    match = _FILE_RE.search(text or "")
    if not match:
        return ""
    return next(g for g in match.groups() if g)


def extract_intent(text: str, *, data_path: str = "") -> str:
    clean = (text or "").strip()
    if data_path:
        clean = clean.replace(data_path, " ")
    clean = re.sub(_FILE_RE, " ", clean)
    clean = re.sub(
        r"(?i)\b(?:generate|create|build|make|show|render)\s+(?:a\s+)?(?:bi\s+)?dashboard\s+(?:from|for|with|using|about)\s*",
        "",
        clean,
    )
    clean = re.sub(r"(?i)\bbi[_\s-]?dashboard\b", "", clean).strip(" ,.-")
    return clean or "overview"


def _match_column_from_intent(intent: str, columns: list[str]) -> str | None:
    if not intent:
        return None
    words = [w for w in re.findall(r"[a-z0-9]+", intent.lower()) if len(w) > 2]
    best: tuple[int, str] | None = None
    for col in columns:
        col_l = col.lower()
        score = sum(1 for w in words if w in col_l)
        if score and (best is None or score > best[0]):
            best = (score, col)
    return best[1] if best else None


def _numeric_columns(rows: list[dict[str, str]], columns: list[str]) -> list[str]:
    from arka.charts.plot import parse_numeric_value

    hits: dict[str, int] = {}
    for col in columns:
        count = 0
        for row in rows[: min(len(rows), 50)]:
            raw = row.get(col, "").strip()
            if not raw:
                continue
            try:
                parse_numeric_value(raw)
                count += 1
            except ValueError:
                count = -999
                break
        if count >= 2:
            hits[col] = count
    return sorted(hits, key=hits.get, reverse=True)


def _text_columns(rows: list[dict[str, str]], columns: list[str]) -> list[str]:
    numeric = set(_numeric_columns(rows, columns))
    return [c for c in columns if c not in numeric]


def _resolve_axes(
    rows: list[dict[str, str]],
    columns: list[str],
    intent: str,
) -> tuple[str, str]:
    by_hint = _match_column_from_intent(intent, _text_columns(rows, columns))
    value_hint = _match_column_from_intent(intent, _numeric_columns(rows, columns))
    return resolve_columns(rows, by=by_hint, value=value_hint)


def _kpi_cards(rows: list[dict[str, str]], columns: list[str], value_col: str) -> list[dict[str, Any]]:
    from arka.charts.plot import parse_numeric_value

    cards: list[dict[str, Any]] = [
        {"label": "Rows", "value": f"{len(rows):,}"},
        {"label": "Columns", "value": str(len(columns))},
    ]
    values: list[float] = []
    for row in rows:
        raw = row.get(value_col, "").strip()
        if not raw:
            continue
        try:
            values.append(parse_numeric_value(raw))
        except ValueError:
            continue
    if values:
        cards.append({"label": f"Total {value_col}", "value": f"{sum(values):,.2f}"})
        cards.append({"label": f"Avg {value_col}", "value": f"{statistics.fmean(values):,.2f}"})
    text_cols = _text_columns(rows, columns)
    if text_cols:
        col = text_cols[0]
        unique = len({row.get(col, "").strip() for row in rows if row.get(col, "").strip()})
        cards.append({"label": f"Unique {col}", "value": str(unique)})
    return cards[:6]


def _choose_chart_type(labels: list[str], values: list[float], intent: str) -> str:
    if _PIE_WORDS.search(intent):
        return "pie"
    if _LINE_WORDS.search(intent):
        return "line"
    suggested = suggest_chart_type(labels, values)
    if suggested == "pie" and len(labels) <= 8:
        return "pie"
    if suggested == "line":
        return "line"
    return "bar"


def infer_panels(
    rows: list[dict[str, str]],
    *,
    intent: str,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    cols = columns or list(dict.fromkeys(k for row in rows for k in row))
    label_col, value_col = _resolve_axes(rows, cols, intent)
    labels, values = aggregate_rows(rows, label_col, value_col)
    chart_type = _choose_chart_type(labels, values, intent)
    panels: list[dict[str, Any]] = [
        {"template": "kpi_cards", "type": "kpi", "title": "Overview", "metrics": _kpi_cards(rows, cols, value_col)},
        {
            "template": f"{chart_type}_chart",
            "type": chart_type,
            "title": f"{value_col} by {label_col}",
            "label_column": label_col,
            "value_column": value_col,
            "labels": labels[:24],
            "values": values[:24],
        },
    ]
    if _TABLE_WORDS.search(intent) or len(rows) <= 200:
        preview_cols = cols[:8]
        preview_rows = [
            {c: row.get(c, "") for c in preview_cols}
            for row in rows[:15]
        ]
        panels.append(
            {
                "template": "data_table",
                "type": "table",
                "title": "Sample rows",
                "columns": preview_cols,
                "rows": preview_rows,
            }
        )
    return {
        "label_column": label_col,
        "value_column": value_col,
        "panels": panels,
    }


def _svg_bar(labels: list[str], values: list[float], *, title: str) -> str:
    if not labels:
        return "<p class='muted'>No data for bar chart.</p>"
    width, height, pad = 640, 280, 48
    max_val = max(values) or 1.0
    bar_w = (width - pad * 2) / max(len(labels), 1) * 0.7
    parts = [
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{html.escape(title)}'>",
        f"<text x='{pad}' y='24' fill='#cbd5e1' font-size='14'>{html.escape(title)}</text>",
    ]
    for idx, (label, val) in enumerate(zip(labels, values)):
        x = pad + idx * (width - pad * 2) / len(labels) + bar_w * 0.15
        h = (height - pad * 2) * (val / max_val)
        y = height - pad - h
        color = _COLORS[idx % len(_COLORS)]
        parts.append(
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{h:.1f}' fill='{color}' rx='4'/>"
        )
        parts.append(
            f"<text x='{x + bar_w / 2:.1f}' y='{height - 16}' fill='#94a3b8' font-size='10' "
            f"text-anchor='middle'>{html.escape(str(label)[:14])}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _svg_pie(labels: list[str], values: list[float], *, title: str) -> str:
    import math

    positives = [(lbl, val) for lbl, val in zip(labels, values) if val > 0]
    if not positives:
        return "<p class='muted'>No data for pie chart.</p>"
    total = sum(val for _, val in positives)
    cx, cy, r = 180, 150, 110
    parts = [
        "<svg viewBox='0 0 420 300' role='img'>",
        f"<text x='16' y='24' fill='#cbd5e1' font-size='14'>{html.escape(title)}</text>",
    ]
    start = -math.pi / 2
    for idx, (label, val) in enumerate(positives[:8]):
        angle = (val / total) * math.pi * 2
        end = start + angle
        x1 = cx + r * math.cos(start)
        y1 = cy + r * math.sin(start)
        x2 = cx + r * math.cos(end)
        y2 = cy + r * math.sin(end)
        large = 1 if angle > math.pi else 0
        color = _COLORS[idx % len(_COLORS)]
        parts.append(
            f"<path d='M{cx},{cy} L{x1:.2f},{y1:.2f} A{r},{r} 0 {large},1 {x2:.2f},{y2:.2f} Z' "
            f"fill='{color}' stroke='#0b1020' stroke-width='1'/>"
        )
        pct = 100.0 * val / total
        mid = start + angle / 2
        lx = cx + (r * 0.65) * math.cos(mid)
        ly = cy + (r * 0.65) * math.sin(mid)
        parts.append(
            f"<text x='{lx:.1f}' y='{ly:.1f}' fill='#0f172a' font-size='10' text-anchor='middle'>"
            f"{html.escape(str(label)[:10])}</text>"
        )
        parts.append(
            f"<text x='300' y='{48 + idx * 22}' fill='#94a3b8' font-size='11'>"
            f"<tspan fill='{color}'>■</tspan> {html.escape(str(label)[:18])} ({pct:.1f}%)</text>"
        )
        start = end
    parts.append("</svg>")
    return "".join(parts)


def _svg_line(labels: list[str], values: list[float], *, title: str) -> str:
    if len(labels) < 2:
        return _svg_bar(labels, values, title=title)
    width, height, pad = 640, 280, 48
    max_val = max(values) or 1.0
    min_val = min(values)
    span = max(max_val - min_val, 1e-9)
    points: list[str] = []
    for idx, val in enumerate(values):
        x = pad + idx * (width - pad * 2) / max(len(values) - 1, 1)
        y = height - pad - ((val - min_val) / span) * (height - pad * 2)
        points.append(f"{x:.1f},{y:.1f}")
    parts = [
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{html.escape(title)}'>",
        f"<text x='{pad}' y='24' fill='#cbd5e1' font-size='14'>{html.escape(title)}</text>",
        f"<polyline fill='none' stroke='#38bdf8' stroke-width='3' points='{' '.join(points)}'/>",
    ]
    for idx, label in enumerate(labels):
        x = pad + idx * (width - pad * 2) / max(len(labels) - 1, 1)
        parts.append(
            f"<text x='{x:.1f}' y='{height - 16}' fill='#94a3b8' font-size='10' "
            f"text-anchor='middle'>{html.escape(str(label)[:12])}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _render_panel(panel: dict[str, Any]) -> str:
    ptype = panel.get("type", "bar")
    title = str(panel.get("title", "Panel"))
    if ptype == "kpi":
        cards = "".join(
            f"<div class='card'><div class='muted'>{html.escape(str(c['label']))}</div>"
            f"<h2>{html.escape(str(c['value']))}</h2></div>"
            for c in panel.get("metrics", [])
        )
        return f"<section><h2>{html.escape(title)}</h2><div class='cards'>{cards}</div></section>"
    if ptype in {"bar", "pie", "line"}:
        labels = panel.get("labels") or []
        values = panel.get("values") or []
        if ptype == "pie":
            chart = _svg_pie(labels, values, title=title)
        elif ptype == "line":
            chart = _svg_line(labels, values, title=title)
        else:
            chart = _svg_bar(labels, values, title=title)
        return f"<section><div class='panel'>{chart}</div></section>"
    if ptype == "table":
        cols = panel.get("columns") or []
        head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
        body_rows = []
        for row in panel.get("rows") or []:
            cells = "".join(f"<td>{html.escape(str(row.get(c, '')))}</td>" for c in cols)
            body_rows.append(f"<tr>{cells}</tr>")
        table = (
            f"<table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body_rows) or '<tr><td colspan=99>No rows</td></tr>'}</tbody></table>"
        )
        return f"<section><h2>{html.escape(title)}</h2>{table}</section>"
    return ""


def build_html(
    *,
    title: str,
    panels: list[dict[str, Any]],
    source: str,
    intent: str,
) -> str:
    body = "".join(_render_panel(panel) for panel in panels)
    return f"""<!doctype html>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(title)}</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#0b1020;color:#edf2ff}}
h1{{margin-bottom:4px}} .muted{{color:#9eacce;font-size:14px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0 24px}}
.card{{background:#17213c;padding:16px 18px;border-radius:12px;min-width:140px}}
.card h2{{margin:6px 0 0;font-size:1.5rem}}
section{{margin:28px 0}}
.panel{{background:#111827;border:1px solid #24304f;border-radius:12px;padding:12px;overflow:auto}}
table{{width:100%;border-collapse:collapse;margin-top:8px;font-size:14px}}
th,td{{padding:10px;border-bottom:1px solid #2b385d;text-align:left}}
th{{color:#cbd5e1}}
</style>
<h1>{html.escape(title)}</h1>
<p class='muted'>Intent: {html.escape(intent)} · Source: {html.escape(source)}</p>
{body}
<p class='muted'>Generated by Arka BI dashboard · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
"""


def export_json_spec(
    *,
    title: str,
    source: str,
    intent: str,
    spec: dict[str, Any],
    html_path: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "source": source,
        "intent": intent,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_html": html_path,
        "templates": _PANEL_TEMPLATES,
        "label_column": spec.get("label_column"),
        "value_column": spec.get("value_column"),
        "panels": spec.get("panels", []),
    }


def build(
    data_path: str | Path,
    *,
    intent: str = "overview",
    output: str | Path | None = None,
    title: str | None = None,
    max_rows: int = 5000,
) -> dict[str, Any]:
    path = Path(data_path).expanduser().resolve()
    rows = load_rows(path, max_rows=max_rows)
    columns = list(dict.fromkeys(k for row in rows for k in row))
    spec = infer_panels(rows, intent=intent, columns=columns)
    dashboard_title = title or f"BI dashboard — {path.stem.replace('_', ' ').replace('-', ' ').title()}"
    out_path = Path(output).expanduser() if output else _default_output(path.stem)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    document = build_html(
        title=dashboard_title,
        panels=spec["panels"],
        source=str(path),
        intent=intent,
    )
    out_path.write_text(document, encoding="utf-8")
    json_path = out_path.with_suffix(".json")
    payload = export_json_spec(
        title=dashboard_title,
        source=str(path),
        intent=intent,
        spec=spec,
        html_path=str(out_path),
    )
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "output": str(out_path),
        "json": str(json_path),
        "title": dashboard_title,
        "panels": len(spec["panels"]),
        "rows": len(rows),
        "label_column": spec["label_column"],
        "value_column": spec["value_column"],
    }


def wants_bi_dashboard(text: str) -> bool:
    clean = (text or "").strip()
    if not clean or _EXCLUDE_RE.search(clean):
        return False
    if not _TRIGGER_RE.search(clean):
        return False
    return bool(extract_file_path(clean) or re.search(r"(?i)\b(?:sales|revenue|metrics?|data|csv|json)\b", clean))


def route_command(text: str) -> str:
    if not wants_bi_dashboard(text):
        return ""
    data_path = extract_file_path(text)
    if not data_path:
        return ""
    intent = extract_intent(text, data_path=data_path)
    parts = ["bi_dashboard", shlex.quote(data_path)]
    if intent and intent != "overview":
        parts.extend(["--intent", shlex.quote(intent)])
    return " ".join(parts)


def nl_to_argv(text: str) -> list[str]:
    route = route_command(text)
    if not route:
        return []
    return shlex.split(route)[1:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka bi_dashboard", description="Generate a local HTML BI dashboard from data")
    parser.add_argument("data", nargs="?", help="CSV, TSV, or JSON data file")
    parser.add_argument("--intent", default="overview", help="Natural-language dashboard intent (e.g. 'sales by region')")
    parser.add_argument("--title", help="Dashboard title")
    parser.add_argument("--output", "-o", help="Output HTML path")
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--json", action="store_true", help="Print result JSON")
    parser.add_argument("--templates", action="store_true", help="List bundled panel templates and exit")
    args = parser.parse_args(argv)
    if args.templates:
        print(json.dumps(_PANEL_TEMPLATES, indent=2))
        return 0
    if not args.data:
        parser.error("data file is required")
    result = build(
        args.data,
        intent=args.intent,
        output=args.output,
        title=args.title,
        max_rows=args.max_rows,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"BI dashboard: {result['output']}")
        print(f"Spec JSON: {result['json']}")
        print(f"Panels: {result['panels']} · Rows: {result['rows']} · {result['label_column']} → {result['value_column']}")
    return 0
