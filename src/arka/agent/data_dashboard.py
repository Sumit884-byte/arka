"""Generate self-contained HTML dashboards from CSV/JSON/JSONL for stocks and data science."""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import shlex
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arka.charts.plot import parse_numeric_value
from arka.charts.tabular import (
    _DATE_LABEL,
    _is_numeric_column,
    aggregate_rows,
    load_rows,
    resolve_columns,
    suggest_chart_type,
)

_DATA_EXT = r"(?:csv|tsv|json|jsonl)"
_FILE_RE = re.compile(
    rf"(?i)(?:['\"]([^'\"]+\.(?:{_DATA_EXT}))['\"]"
    rf"|([~./][^\s'\"]+\.(?:{_DATA_EXT}))"
    rf"|([^\s'\"/\\]+\.(?:{_DATA_EXT}))\b)"
)

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"data[_\s-]?dashboard|data\s+science\s+dashboard|viz[_\s-]?dashboard|"
    r"(?:quick|instant|auto)\s+dashboard|"
    r"(?:build|create|generate|make|render)\s+(?:a\s+)?(?:data|stock|viz|visualization)?\s*dashboard|"
    r"dashboard\s+(?:for|from|with|using)\s+(?:stock|ohlcv|csv|json|data|metrics?)|"
    r"(?:stock|ohlcv|csv|json|metrics?)\s+(?:as\s+)?dashboard|"
    r"visuali[sz]e\s+(?:this\s+)?(?:data|csv|json|metrics?|stock\s+data)\s+(?:as\s+)?dashboard|"
    r"visuali[sz]e\s+(?:my\s+)?(?:data|csv|json|metrics?)\b"
    r")\b"
)

_EXCLUDE_RE = re.compile(
    r"(?i)\b("
    r"usage\s+dashboard|skill\s+usage|signoz|grafana|metabase|superset|"
    r"streamlit\s+dashboard|observability\s+dashboard|bi[_\s-]?dashboard|"
    r"web\s+dashboard|react\s+dashboard"
    r")\b"
)

_OHLCV_ALIASES = {
    "open": {"open", "o"},
    "high": {"high", "h"},
    "low": {"low", "l"},
    "close": {"close", "adj close", "adj_close", "price", "c"},
    "volume": {"volume", "vol", "v"},
}
_STOCK_HINTS = {"ticker", "symbol", "date", "datetime", "timestamp", "open", "high", "low", "close", "volume", "vol"}

_THEME_CSS = {
    "dark": {
        "bg": "#0b0d12",
        "panel": "#11141b",
        "text": "#f4f4f5",
        "muted": "#9ca3af",
        "line": "#2b3140",
        "accent": "#f97316",
        "ok": "#22c55e",
        "danger": "#ef4444",
    },
    "light": {
        "bg": "#f8fafc",
        "panel": "#ffffff",
        "text": "#0f172a",
        "muted": "#64748b",
        "line": "#e2e8f0",
        "accent": "#2563eb",
        "ok": "#16a34a",
        "danger": "#dc2626",
    },
}


def _default_output(slug: str = "data-dashboard") -> Path:
    clean = re.sub(r"[^a-z0-9]+", "-", slug.lower())[:48].strip("-") or "data-dashboard"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path.home() / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{clean}-{ts}.html"


def extract_file_path(text: str) -> str:
    match = _FILE_RE.search(text or "")
    if not match:
        return ""
    return next(g for g in match.groups() if g)


def _column_names(rows: list[dict[str, str]]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def _norm_col(name: str) -> str:
    return re.sub(r"[\s_]+", " ", name.strip().lower())


def _find_column(columns: list[str], aliases: set[str]) -> str | None:
    for col in columns:
        if _norm_col(col) in aliases:
            return col
    for col in columns:
        norm = _norm_col(col)
        if any(alias in norm for alias in aliases):
            return col
    return None


def _load_jsonl(path: Path, *, max_rows: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for idx, line in enumerate(fh):
            if idx >= max_rows:
                break
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                continue
            cleaned = {str(k).strip(): "" if v is None else str(v).strip() for k, v in item.items()}
            if any(cleaned.values()):
                rows.append(cleaned)
    if not rows:
        raise ValueError(f"No usable rows in {path.name}")
    return rows


def _load_inline(text: str, *, max_rows: int) -> list[dict[str, str]]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("inline data is empty")
    if raw.startswith("[") or raw.startswith("{"):
        payload = json.loads(raw)
        if isinstance(payload, dict):
            for key in ("rows", "data", "records", "items"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        if not isinstance(payload, list):
            raise ValueError("inline JSON must be an array of objects or {rows:[...]}")
        rows: list[dict[str, str]] = []
        for idx, item in enumerate(payload):
            if idx >= max_rows:
                break
            if isinstance(item, dict):
                cleaned = {str(k).strip(): "" if v is None else str(v).strip() for k, v in item.items()}
                if any(cleaned.values()):
                    rows.append(cleaned)
        if not rows:
            raise ValueError("inline JSON has no usable rows")
        return rows
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
    rows = []
    for idx, row in enumerate(reader):
        if idx >= max_rows:
            break
        cleaned = {str(k).strip(): str(v or "").strip() for k, v in row.items() if k}
        if any(cleaned.values()):
            rows.append(cleaned)
    if not rows:
        raise ValueError("inline CSV has no usable rows")
    return rows


def load_data(
    source: str | Path | None = None,
    *,
    inline: str | None = None,
    max_rows: int = 5000,
) -> tuple[list[dict[str, str]], str]:
    if inline:
        return _load_inline(inline, max_rows=max_rows), "inline"
    if source is None or str(source).strip() in {"", "-"}:
        if sys.stdin.isatty():
            raise ValueError("data path, inline payload, or stdin is required")
        text = sys.stdin.read()
        return _load_inline(text, max_rows=max_rows), "stdin"
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return _load_jsonl(path, max_rows=max_rows), str(path)
    rows = load_rows(path, max_rows=max_rows)
    return rows, str(path)


def detect_schema(rows: list[dict[str, str]]) -> dict[str, Any]:
    columns = _column_names(rows)
    numeric = [c for c in columns if _is_numeric_column(rows, c)]
    text = [c for c in columns if c not in numeric]
    date_cols = [c for c in text if labels_look_temporal([row.get(c, "") for row in rows[:20]])]
    category_cols = [c for c in text if c not in date_cols]
    return {
        "columns": columns,
        "numeric": numeric,
        "text": text,
        "date_columns": date_cols,
        "category_columns": category_cols,
        "row_count": len(rows),
    }


def labels_look_temporal(labels: list[str]) -> bool:
    hits = sum(1 for lbl in labels if lbl.strip() and _DATE_LABEL.match(lbl.strip()))
    return hits >= max(2, len([lbl for lbl in labels if lbl.strip()]) // 2)


def detect_mode(rows: list[dict[str, str]], schema: dict[str, Any] | None = None) -> str:
    schema = schema or detect_schema(rows)
    columns = schema["columns"]
    lowered = {_norm_col(c) for c in columns}
    ohlcv_hits = sum(1 for aliases in _OHLCV_ALIASES.values() if _find_column(columns, aliases))
    stock_hints = len(lowered & _STOCK_HINTS)
    has_close = _find_column(columns, _OHLCV_ALIASES["close"]) is not None
    has_date = bool(schema.get("date_columns")) or any(k in lowered for k in {"date", "datetime", "timestamp"})
    if ohlcv_hits >= 3 or (has_close and has_date and stock_hints >= 2):
        return "stock"
    return "datascience"


def _numeric_series(rows: list[dict[str, str]], column: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw = row.get(column, "").strip()
        if not raw:
            continue
        try:
            values.append(parse_numeric_value(raw))
        except ValueError:
            continue
    return values


def _stock_columns(columns: list[str]) -> dict[str, str | None]:
    return {key: _find_column(columns, aliases) for key, aliases in _OHLCV_ALIASES.items()}


def _stock_stats(rows: list[dict[str, str]], cols: dict[str, str | None]) -> list[dict[str, Any]]:
    close_col = cols.get("close")
    vol_col = cols.get("volume")
    cards: list[dict[str, Any]] = [{"label": "Rows", "value": f"{len(rows):,}"}]
    if close_col:
        closes = _numeric_series(rows, close_col)
        if closes:
            first, last = closes[0], closes[-1]
            change = ((last / first) - 1) * 100 if first else 0.0
            cards.extend(
                [
                    {"label": f"Latest {close_col}", "value": f"{last:,.2f}"},
                    {"label": "Return", "value": f"{change:+.2f}%", "tone": "ok" if change >= 0 else "danger"},
                    {"label": "High", "value": f"{max(closes):,.2f}"},
                    {"label": "Low", "value": f"{min(closes):,.2f}"},
                ]
            )
    if vol_col:
        vols = _numeric_series(rows, vol_col)
        if vols:
            cards.append({"label": f"Avg {vol_col}", "value": f"{statistics.fmean(vols):,.0f}"})
    ticker_col = _find_column(_column_names(rows), {"ticker", "symbol"})
    if ticker_col:
        tickers = sorted({row.get(ticker_col, "").strip() for row in rows if row.get(ticker_col, "").strip()})
        if tickers:
            cards.append({"label": "Ticker", "value": ", ".join(tickers[:3])})
    return cards[:6]


def _summary_stats(rows: list[dict[str, str]], numeric_cols: list[str]) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    for col in numeric_cols[:8]:
        vals = _numeric_series(rows, col)
        if len(vals) < 2:
            continue
        stats.append(
            {
                "column": col,
                "count": len(vals),
                "mean": round(statistics.fmean(vals), 4),
                "min": round(min(vals), 4),
                "max": round(max(vals), 4),
                "stdev": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
            }
        )
    return stats


def _correlation_matrix(rows: list[dict[str, str]], numeric_cols: list[str]) -> dict[str, Any] | None:
    cols = numeric_cols[:8]
    if len(cols) < 2:
        return None
    series: dict[str, list[float]] = {}
    for col in cols:
        vals = _numeric_series(rows, col)
        if len(vals) >= 3:
            series[col] = vals
    usable = [c for c in cols if c in series and len(series[c]) >= 3]
    if len(usable) < 2:
        return None
    n = min(len(series[c]) for c in usable)
    trimmed = {c: series[c][:n] for c in usable}

    def pearson(a: list[float], b: list[float]) -> float:
        if len(a) != len(b) or len(a) < 2:
            return 0.0
        mean_a = statistics.fmean(a)
        mean_b = statistics.fmean(b)
        num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        den_a = sum((x - mean_a) ** 2 for x in a) ** 0.5
        den_b = sum((y - mean_b) ** 2 for y in b) ** 0.5
        if not den_a or not den_b:
            return 0.0
        return num / (den_a * den_b)

    z: list[list[float]] = []
    for row_col in usable:
        z.append([round(pearson(trimmed[row_col], trimmed[col_col]), 3) for col_col in usable])
    return {"columns": usable, "values": z}


def _time_labels(rows: list[dict[str, str]], schema: dict[str, Any]) -> tuple[str, list[str]]:
    date_cols = schema.get("date_columns") or []
    if date_cols:
        col = date_cols[0]
        labels = [row.get(col, "").strip() for row in rows if row.get(col, "").strip()]
        return col, labels[:500]
    label_col, value_col = resolve_columns(rows, by=None, value=None)
    labels, _ = aggregate_rows(rows, label_col, value_col)
    return label_col, labels[:500]


def infer_panels(
    rows: list[dict[str, str]],
    *,
    mode: str | None = None,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema = schema or detect_schema(rows)
    mode = mode or detect_mode(rows, schema)
    columns = schema["columns"]
    panels: list[dict[str, Any]] = []

    if mode == "stock":
        stock_cols = _stock_columns(columns)
        panels.append({"type": "kpi", "title": "Market snapshot", "metrics": _stock_stats(rows, stock_cols)})
        date_col, labels = _time_labels(rows, schema)
        if stock_cols.get("open") and stock_cols.get("high") and stock_cols.get("low") and stock_cols.get("close"):
            o, h, low, c = stock_cols["open"], stock_cols["high"], stock_cols["low"], stock_cols["close"]
            candle_rows = []
            for row in rows[:500]:
                try:
                    candle_rows.append(
                        {
                            "x": row.get(date_col, "").strip(),
                            "open": parse_numeric_value(row.get(o, "")),
                            "high": parse_numeric_value(row.get(h, "")),
                            "low": parse_numeric_value(row.get(low, "")),
                            "close": parse_numeric_value(row.get(c, "")),
                        }
                    )
                except ValueError:
                    continue
            if len(candle_rows) >= 2:
                panels.append({"type": "candlestick", "title": "Price action", "data": candle_rows})
        close_col = stock_cols.get("close")
        if close_col:
            closes = _numeric_series(rows, close_col)
            x_labels = [row.get(date_col, "").strip() for row in rows[: len(closes)]]
            if len(closes) >= 2:
                panels.append(
                    {
                        "type": "line",
                        "title": f"{close_col} trend",
                        "x": x_labels[: len(closes)],
                        "y": closes,
                        "name": close_col,
                    }
                )
        vol_col = stock_cols.get("volume")
        if vol_col:
            vols = _numeric_series(rows, vol_col)
            x_labels = [row.get(date_col, "").strip() for row in rows[: len(vols)]]
            if len(vols) >= 2:
                panels.append(
                    {
                        "type": "bar",
                        "title": f"{vol_col}",
                        "x": x_labels[: len(vols)],
                        "y": vols,
                        "name": vol_col,
                    }
                )
    else:
        numeric = schema["numeric"]
        label_col, value_col = resolve_columns(rows, by=None, value=None)
        labels, values = aggregate_rows(rows, label_col, value_col)
        chart_type = suggest_chart_type(labels, values)
        panels.append(
            {
                "type": "kpi",
                "title": "Dataset overview",
                "metrics": [
                    {"label": "Rows", "value": f"{len(rows):,}"},
                    {"label": "Columns", "value": str(len(columns))},
                    {"label": "Numeric", "value": str(len(numeric))},
                    {"label": "Primary metric", "value": value_col},
                ],
            }
        )
        panels.append(
            {
                "type": chart_type,
                "title": f"{value_col} by {label_col}",
                "x": labels[:40],
                "y": values[:40],
                "name": value_col,
            }
        )
        if numeric:
            hist_col = numeric[0]
            hist_vals = _numeric_series(rows, hist_col)
            if len(hist_vals) >= 3:
                panels.append({"type": "histogram", "title": f"{hist_col} distribution", "values": hist_vals, "name": hist_col})
        if len(numeric) >= 2:
            x_col, y_col = numeric[0], numeric[1]
            xs, ys = [], []
            for row in rows:
                try:
                    xs.append(parse_numeric_value(row.get(x_col, "")))
                    ys.append(parse_numeric_value(row.get(y_col, "")))
                except ValueError:
                    continue
            if len(xs) >= 3:
                panels.append(
                    {
                        "type": "scatter",
                        "title": f"{y_col} vs {x_col}",
                        "x": xs[:400],
                        "y": ys[:400],
                        "x_name": x_col,
                        "y_name": y_col,
                    }
                )
        corr = _correlation_matrix(rows, numeric)
        if corr:
            panels.append({"type": "heatmap", "title": "Correlation matrix", **corr})
        summary = _summary_stats(rows, numeric)
        if summary:
            panels.append({"type": "stats_table", "title": "Summary statistics", "rows": summary})

    preview_cols = columns[:8]
    preview_rows = [{c: row.get(c, "") for c in preview_cols} for row in rows[:12]]
    panels.append({"type": "table", "title": "Sample rows", "columns": preview_cols, "rows": preview_rows})
    return {"mode": mode, "schema": schema, "panels": panels}


def _plotly_script(panels: list[dict[str, Any]]) -> str:
    plots: list[dict[str, Any]] = []
    for idx, panel in enumerate(panels):
        ptype = panel.get("type")
        div_id = f"plot-{idx}"
        if ptype == "candlestick":
            plots.append(
                {
                    "id": div_id,
                    "data": [
                        {
                            "type": "candlestick",
                            "x": [d["x"] for d in panel["data"]],
                            "open": [d["open"] for d in panel["data"]],
                            "high": [d["high"] for d in panel["data"]],
                            "low": [d["low"] for d in panel["data"]],
                            "close": [d["close"] for d in panel["data"]],
                            "name": panel.get("title", "Price"),
                        }
                    ],
                    "layout": {"title": panel.get("title", ""), "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)"},
                }
            )
        elif ptype == "line":
            plots.append(
                {
                    "id": div_id,
                    "data": [{"type": "scatter", "mode": "lines", "x": panel["x"], "y": panel["y"], "name": panel.get("name", "")}],
                    "layout": {"title": panel.get("title", ""), "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)"},
                }
            )
        elif ptype == "bar":
            plots.append(
                {
                    "id": div_id,
                    "data": [{"type": "bar", "x": panel["x"], "y": panel["y"], "name": panel.get("name", "")}],
                    "layout": {"title": panel.get("title", ""), "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)"},
                }
            )
        elif ptype == "pie":
            plots.append(
                {
                    "id": div_id,
                    "data": [{"type": "pie", "labels": panel["x"], "values": panel["y"], "hole": 0.35}],
                    "layout": {"title": panel.get("title", ""), "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)"},
                }
            )
        elif ptype == "scatter":
            plots.append(
                {
                    "id": div_id,
                    "data": [
                        {
                            "type": "scatter",
                            "mode": "markers",
                            "x": panel["x"],
                            "y": panel["y"],
                            "name": panel.get("y_name", ""),
                        }
                    ],
                    "layout": {
                        "title": panel.get("title", ""),
                        "xaxis": {"title": panel.get("x_name", "")},
                        "yaxis": {"title": panel.get("y_name", "")},
                        "paper_bgcolor": "rgba(0,0,0,0)",
                        "plot_bgcolor": "rgba(0,0,0,0)",
                    },
                }
            )
        elif ptype == "histogram":
            plots.append(
                {
                    "id": div_id,
                    "data": [{"type": "histogram", "x": panel["values"], "name": panel.get("name", "")}],
                    "layout": {"title": panel.get("title", ""), "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)"},
                }
            )
        elif ptype == "heatmap":
            plots.append(
                {
                    "id": div_id,
                    "data": [
                        {
                            "type": "heatmap",
                            "z": panel["values"],
                            "x": panel["columns"],
                            "y": panel["columns"],
                            "colorscale": "RdBu",
                            "zmid": 0,
                        }
                    ],
                    "layout": {"title": panel.get("title", ""), "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)"},
                }
            )
    return json.dumps(plots)


def _render_panel_html(panel: dict[str, Any], *, plot_idx: int) -> str:
    ptype = panel.get("type", "")
    title = html.escape(str(panel.get("title", "Panel")))
    if ptype == "kpi":
        cards = []
        for metric in panel.get("metrics", []):
            tone = metric.get("tone", "")
            tone_class = f" tone-{tone}" if tone else ""
            cards.append(
                f"<article class='card stat{tone_class}'>"
                f"<div class='label'>{html.escape(str(metric.get('label', '')))}</div>"
                f"<div class='value'>{html.escape(str(metric.get('value', '')))}</div>"
                f"</article>"
            )
        return f"<section><h2>{title}</h2><div class='stats'>{''.join(cards)}</div></section>"
    if ptype in {"candlestick", "line", "bar", "pie", "scatter", "histogram", "heatmap"}:
        return f"<section class='panel-wrap'><div id='plot-{plot_idx}' class='plot'></div></section>"
    if ptype == "stats_table":
        head = "".join(f"<th>{html.escape(str(h))}</th>" for h in ("column", "count", "mean", "min", "max", "stdev"))
        body = []
        for row in panel.get("rows") or []:
            cells = "".join(f"<td>{html.escape(str(row.get(k, '')))}</td>" for k in ("column", "count", "mean", "min", "max", "stdev"))
            body.append(f"<tr>{cells}</tr>")
        return f"<section><h2>{title}</h2><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></section>"
    if ptype == "table":
        cols = panel.get("columns") or []
        head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
        body = []
        for row in panel.get("rows") or []:
            cells = "".join(f"<td>{html.escape(str(row.get(c, '')))}</td>" for c in cols)
            body.append(f"<tr>{cells}</tr>")
        return f"<section><h2>{title}</h2><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></section>"
    return ""


def build_html(
    *,
    title: str,
    panels: list[dict[str, Any]],
    source: str,
    mode: str,
    theme: str = "dark",
) -> str:
    tokens = _THEME_CSS.get(theme, _THEME_CSS["dark"])
    plot_idx = 0
    body_parts: list[str] = []
    plot_panels: list[dict[str, Any]] = []
    for panel in panels:
        if panel.get("type") in {"candlestick", "line", "bar", "pie", "scatter", "histogram", "heatmap"}:
            plot_panels.append(panel)
            body_parts.append(_render_panel_html(panel, plot_idx=plot_idx))
            plot_idx += 1
        else:
            body_parts.append(_render_panel_html(panel, plot_idx=-1))
    plots_json = _plotly_script(plot_panels)
    mode_badge = "Stock" if mode == "stock" else "Data science"
    return f"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(title)}</title>
<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>
<style>
:root {{
  color-scheme: {"dark" if theme == "dark" else "light"};
  --bg: {tokens["bg"]};
  --panel: {tokens["panel"]};
  --text: {tokens["text"]};
  --muted: {tokens["muted"]};
  --line: {tokens["line"]};
  --accent: {tokens["accent"]};
  --ok: {tokens["ok"]};
  --danger: {tokens["danger"]};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font: 16px/1.55 Inter, ui-sans-serif, system-ui, sans-serif;
  background:
    radial-gradient(circle at 62% -12%, color-mix(in srgb, var(--accent) 12%, transparent), transparent 34rem),
    var(--bg);
  color: var(--text);
}}
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 48px; }}
.hero {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 24px; }}
.hero h1 {{ margin: 0; font-size: clamp(1.6rem, 2vw, 2.2rem); letter-spacing: -0.03em; }}
.muted {{ color: var(--muted); font-size: 0.92rem; }}
.badge {{
  display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.25rem 0.65rem;
  border-radius: 999px; border: 1px solid var(--line); background: color-mix(in srgb, var(--panel) 88%, white 12%);
  font-size: 0.78rem; font-weight: 700; color: var(--accent);
}}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 12px 0 8px; }}
.card {{
  background: var(--panel); border: 1px solid var(--line); border-radius: 16px;
  box-shadow: 0 28px 90px rgba(0,0,0,0.18); padding: 16px 18px;
}}
.stat .label {{ color: var(--muted); font-size: 0.82rem; font-weight: 600; }}
.stat .value {{ font-size: 1.55rem; font-weight: 800; letter-spacing: -0.03em; margin-top: 0.2rem; }}
.stat.tone-ok .value {{ color: var(--ok); }}
.stat.tone-danger .value {{ color: var(--danger); }}
section {{ margin: 24px 0; }}
section h2 {{ margin: 0 0 12px; font-size: 1rem; }}
.panel-wrap {{ background: var(--panel); border: 1px solid var(--line); border-radius: 16px; padding: 8px; }}
.plot {{ width: 100%; min-height: 360px; }}
table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }}
th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; font-size: 0.92rem; }}
th {{ color: var(--muted); font-weight: 700; }}
tr:last-child td {{ border-bottom: 0; }}
footer {{ margin-top: 28px; }}
@media (max-width: 720px) {{ .hero {{ flex-direction: column; }} }}
</style>
</head>
<body>
<div class='wrap'>
  <header class='hero'>
    <div>
      <h1>{html.escape(title)}</h1>
      <p class='muted'>Source: {html.escape(source)} · Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
    </div>
    <span class='badge'>{html.escape(mode_badge)} dashboard</span>
  </header>
  {''.join(body_parts)}
  <footer class='muted'>Generated by Arka data dashboard · open this file in any browser</footer>
</div>
<script>
const plots = {plots_json};
const layoutBase = {{
  font: {{ color: getComputedStyle(document.body).color }},
  xaxis: {{ gridcolor: 'rgba(148,163,184,0.15)', zerolinecolor: 'rgba(148,163,184,0.15)' }},
  yaxis: {{ gridcolor: 'rgba(148,163,184,0.15)', zerolinecolor: 'rgba(148,163,184,0.15)' }},
  margin: {{ t: 48, r: 24, b: 48, l: 56 }}
}};
plots.forEach((spec) => {{
  const layout = Object.assign({{}}, layoutBase, spec.layout || {{}});
  Plotly.newPlot(spec.id, spec.data, layout, {{responsive: true, displayModeBar: false}});
}});
</script>
</body>
</html>
"""


def export_json_spec(
    *,
    title: str,
    source: str,
    spec: dict[str, Any],
    html_path: str,
    theme: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "source": source,
        "mode": spec.get("mode"),
        "schema": spec.get("schema"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_html": html_path,
        "theme": theme,
        "panels": spec.get("panels", []),
    }


def build(
    data: str | Path | None = None,
    *,
    inline: str | None = None,
    output: str | Path | None = None,
    title: str | None = None,
    theme: str = "dark",
    mode: str | None = None,
    max_rows: int = 5000,
    dry_run: bool = False,
) -> dict[str, Any]:
    rows, source = load_data(data, inline=inline, max_rows=max_rows)
    schema = detect_schema(rows)
    detected_mode = mode or detect_mode(rows, schema)
    spec = infer_panels(rows, mode=detected_mode, schema=schema)
    stem = Path(source).stem if source not in {"inline", "stdin"} else "data-dashboard"
    dashboard_title = title or f"{'Stock' if detected_mode == 'stock' else 'Data'} dashboard — {stem.replace('_', ' ').replace('-', ' ').title()}"
    out_path = Path(output).expanduser() if output else _default_output(stem)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = export_json_spec(
        title=dashboard_title,
        source=source,
        spec=spec,
        html_path=str(out_path),
        theme=theme,
    )
    if dry_run:
        return {
            "dry_run": True,
            "output": str(out_path),
            "title": dashboard_title,
            "mode": detected_mode,
            "panels": len(spec["panels"]),
            "rows": len(rows),
            "schema": schema,
        }
    document = build_html(
        title=dashboard_title,
        panels=spec["panels"],
        source=source,
        mode=detected_mode,
        theme=theme,
    )
    out_path.write_text(document, encoding="utf-8")
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "output": str(out_path),
        "json": str(json_path),
        "title": dashboard_title,
        "mode": detected_mode,
        "panels": len(spec["panels"]),
        "rows": len(rows),
        "schema": schema,
    }


def wants_data_dashboard(text: str) -> bool:
    clean = (text or "").strip()
    if not clean or _EXCLUDE_RE.search(clean):
        return False
    if re.search(r"(?i)\bdashboard\s+build\b", clean):
        return bool(extract_file_path(clean) or re.search(r"(?i)\b(?:csv|json|data|metrics?|stock)\b", clean))
    if re.search(r"(?i)\bviz\s+dashboard\b", clean):
        return bool(extract_file_path(clean) or re.search(r"(?i)\b(?:csv|json|data|metrics?)\b", clean))
    if not _TRIGGER_RE.search(clean):
        return False
    return bool(extract_file_path(clean) or re.search(r"(?i)\b(?:csv|json|data|metrics?|stock|ohlcv)\b", clean) or not sys.stdin.isatty())


def route_command(text: str) -> str:
    if not wants_data_dashboard(text):
        return ""
    data_path = extract_file_path(text)
    parts = ["data_dashboard", "build"]
    if data_path:
        parts.append(shlex.quote(data_path))
    title_match = re.search(r"(?i)\btitle\s+['\"]?([^'\"]+?)['\"]?(?:\s|$)", text)
    if title_match:
        parts.extend(["--title", shlex.quote(title_match.group(1).strip())])
    if re.search(r"(?i)\blight\s+theme\b", text):
        parts.extend(["--theme", "light"])
    return " ".join(parts)


def nl_to_argv(text: str) -> list[str]:
    route = route_command(text)
    if not route:
        return []
    return shlex.split(route)[1:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka data_dashboard", description="Build self-contained HTML dashboards from data")
    sub = parser.add_subparsers(dest="cmd")

    p_build = sub.add_parser("build", help="Build dashboard HTML from data")
    p_build.add_argument("data", nargs="?", help="CSV, TSV, JSON, or JSONL file (or stdin)")
    p_build.add_argument("--inline", help="Inline CSV/JSON payload")
    p_build.add_argument("--title", help="Dashboard title")
    p_build.add_argument("--theme", choices=["dark", "light"], default="dark")
    p_build.add_argument("--mode", choices=["stock", "datascience"], help="Force dashboard mode")
    p_build.add_argument("--output", "-o", help="Output HTML path")
    p_build.add_argument("--max-rows", type=int, default=5000)
    p_build.add_argument("--json", action="store_true", help="Print result JSON")
    p_build.add_argument("--dry-run", action="store_true", help="Infer panels without writing HTML")

    p_schema = sub.add_parser("schema", help="Detect schema and dashboard mode")
    p_schema.add_argument("data", nargs="?", help="Data file")
    p_schema.add_argument("--inline", help="Inline CSV/JSON payload")
    p_schema.add_argument("--max-rows", type=int, default=5000)

    argv_list = list(argv if argv is not None else sys.argv[1:])
    if argv_list and argv_list[0] not in {"build", "schema", "-h", "--help"}:
        nl_args = nl_to_argv(" ".join(argv_list))
        if nl_args:
            argv_list = ["build", *nl_args]
        else:
            argv_list = ["build", *argv_list]
    args = parser.parse_args(argv_list)
    cmd = args.cmd or "build"
    if cmd == "schema":
        rows, source = load_data(args.data, inline=args.inline, max_rows=args.max_rows)
        schema = detect_schema(rows)
        payload = {
            "source": source,
            "mode": detect_mode(rows, schema),
            "schema": schema,
        }
        print(json.dumps(payload, indent=2))
        return 0

    if cmd == "build":
        result = build(
            args.data,
            inline=args.inline,
            output=args.output,
            title=args.title,
            theme=args.theme,
            mode=args.mode,
            max_rows=args.max_rows,
            dry_run=args.dry_run,
        )
        if args.json or args.dry_run:
            print(json.dumps(result, indent=2))
        else:
            print(f"Data dashboard: {result['output']}")
            if not args.dry_run:
                print(f"Spec JSON: {result['json']}")
            print(f"Mode: {result['mode']} · Panels: {result['panels']} · Rows: {result['rows']}")
        return 0

    parser.error(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
