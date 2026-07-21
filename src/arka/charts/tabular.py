"""Load tabular data and pick label/value columns for charts."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from arka.charts.plot import parse_numeric_value

_DATE_LABEL = re.compile(
    r"(?i)^(?:\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}|\d{4}|q[1-4]\s*\d{4})$"
)


def load_rows(path: Path, *, max_rows: int = 5000) -> list[dict[str, str]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _load_csv(path, delimiter=",", max_rows=max_rows)
    if suffix == ".tsv":
        return _load_csv(path, delimiter="\t", max_rows=max_rows)
    if suffix == ".json":
        return _load_json(path, max_rows=max_rows)
    raise SystemExit(f"Unsupported data file: {suffix} (use CSV, TSV, or JSON)")


def _load_csv(path: Path, *, delimiter: str, max_rows: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        if not reader.fieldnames:
            raise SystemExit(f"No header row in {path.name}")
        for idx, row in enumerate(reader):
            if idx >= max_rows:
                break
            cleaned = {str(k).strip(): str(v or "").strip() for k, v in row.items() if k}
            if any(cleaned.values()):
                rows.append(cleaned)
    if not rows:
        raise SystemExit(f"No data rows in {path.name}")
    return rows


def _load_json(path: Path, *, max_rows: int) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        for key in ("rows", "data", "records", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise SystemExit("JSON must be an array of objects or {rows:[...]}")
    rows: list[dict[str, str]] = []
    for idx, item in enumerate(payload):
        if idx >= max_rows:
            break
        if not isinstance(item, dict):
            continue
        cleaned = {str(k).strip(): _stringify(v) for k, v in item.items()}
        if any(cleaned.values()):
            rows.append(cleaned)
    if not rows:
        raise SystemExit(f"No usable rows in {path.name}")
    return rows


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _column_names(rows: list[dict[str, str]]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def _match_column(name: str, columns: list[str]) -> str | None:
    target = name.strip().lower()
    for col in columns:
        if col.lower() == target:
            return col
    for col in columns:
        if target in col.lower() or col.lower() in target:
            return col
    return None


def _is_numeric_column(rows: list[dict[str, str]], column: str) -> bool:
    hits = 0
    for row in rows[: min(len(rows), 40)]:
        raw = row.get(column, "").strip()
        if not raw:
            continue
        try:
            parse_numeric_value(raw)
            hits += 1
        except ValueError:
            return False
    return hits >= 2


def resolve_columns(
    rows: list[dict[str, str]],
    *,
    by: str | None = None,
    value: str | None = None,
) -> tuple[str, str]:
    columns = _column_names(rows)
    if not columns:
        raise SystemExit("No columns found in data")

    label_col = _match_column(by, columns) if by else None
    value_col = _match_column(value, columns) if value else None

    if label_col and value_col:
        return label_col, value_col

    numeric_cols = [c for c in columns if _is_numeric_column(rows, c)]
    text_cols = [c for c in columns if c not in numeric_cols]

    if not value_col:
        value_col = numeric_cols[0] if numeric_cols else None
    if not label_col:
        label_col = text_cols[0] if text_cols else None
        if not label_col and len(columns) >= 2:
            label_col = columns[0]
            if value_col is None:
                value_col = columns[1]

    if not label_col or not value_col:
        raise SystemExit("Could not detect label/value columns — use --by and --value")
    if label_col == value_col:
        raise SystemExit("Label and value columns must differ")
    return label_col, value_col


def aggregate_rows(
    rows: list[dict[str, str]],
    label_col: str,
    value_col: str,
) -> tuple[list[str], list[float]]:
    totals: dict[str, float] = {}
    for row in rows:
        label = row.get(label_col, "").strip()
        raw = row.get(value_col, "").strip()
        if not label or not raw:
            continue
        try:
            val = parse_numeric_value(raw)
        except ValueError:
            continue
        totals[label] = totals.get(label, 0.0) + val
    if len(totals) < 2:
        raise SystemExit("Need at least two label:value pairs after aggregation")
    labels = list(totals.keys())
    values = [totals[lbl] for lbl in labels]
    return labels, values


def labels_look_temporal(labels: list[str]) -> bool:
    hits = sum(1 for lbl in labels if _DATE_LABEL.match(lbl.strip()))
    return hits >= max(2, len(labels) // 2)


def suggest_chart_type(labels: list[str], values: list[float]) -> str:
    if not labels or not values:
        return "bar"
    if labels_look_temporal(labels):
        return "line"
    positives = [v for v in values if v > 0]
    if 2 <= len(positives) <= 6:
        total = sum(positives)
        if 90 <= total <= 110:
            return "pie"
    return "bar"
