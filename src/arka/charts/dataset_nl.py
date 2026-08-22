"""Flexible natural-language parsing for dataset → chart axis columns."""

from __future__ import annotations

import re
from dataclasses import dataclass

_DATA_EXT = r"(?:csv|tsv|json)"
_DATA_FILE_RE = re.compile(
    rf"(?i)(?:['\"]([^'\"]+\.(?:{_DATA_EXT}))['\"]"
    rf"|((?:[\w.-]+/)+[\w.-]+\.(?:{_DATA_EXT}))"
    rf"|([~./][^\s'\"]+\.(?:{_DATA_EXT}))"
    rf"|([^\s'\"/\\]+\.(?:{_DATA_EXT}))\b)"
)

# Hints that a token names a time-like axis (not a fixed column list).
_TEMPORAL = re.compile(
    r"(?i)\b(?:time|times?|date|dates?|month|months?|year|years?|day|days?|week|weeks?|"
    r"period|periods?|quarter|quarters?|timestamp|datetime|epoch|epochs?|step|steps?)\b"
)

_CHART_CUE = re.compile(
    r"(?i)\b(?:chart|graph|plot|visuali[sz]e|diagram|present|show|display|render|compare)\b"
)

_TABLE_CUE = re.compile(
    r"(?i)\b(?:table|tabular|grid|spreadsheet)\b.*\b(?:image|png|picture|photo)\b"
    r"|\bchart\s+table\b|\btable\s+(?:from|of)\b"
)

# Trailing noise after a captured column phrase.
_TRAIL_NOISE = re.compile(
    r"(?i)\s+(?:from|in|on|with|using|as|to|into|for|the|a|an|my|this|that|dataset|"
    r"file|data|csv|tsv|json|please|thanks)\s*$"
)

# Greedy token — cleaned after capture (non-greedy caused single-letter columns).
_COL = r"(['\"][^'\"]+['\"]|[A-Za-z_][\w\s_-]*)"

_LEADING_CUE = re.compile(
    r"(?i)^(?:present|show|display|plot|chart|graph|visualize|visualise|render|compare|make|create)\s+"
)
_LEADING_KIND = re.compile(
    r"(?i)^(?:scatter|line|bar|pie|histogram|pareto|treemap|table)\s+"
)


@dataclass(frozen=True)
class DatasetAxes:
    by: str | None = None
    value: str | None = None
    chart_type: str | None = None


def extract_data_file_path(text: str) -> str | None:
    matches: list[str] = []
    for m in _DATA_FILE_RE.finditer(text or ""):
        path = next(g for g in m.groups() if g)
        matches.append(path)
    if not matches:
        return None
    return max(matches, key=len)


def _clean_token(raw: str) -> str:
    s = (raw or "").strip().strip("'\"")
    s = _LEADING_CUE.sub("", s).strip()
    s = _LEADING_KIND.sub("", s).strip()
    s = _TRAIL_NOISE.sub("", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,.")


def _nl_work_text(text: str) -> str:
    work = text or ""
    path = extract_data_file_path(work)
    if path:
        work = re.sub(re.escape(path), " ", work, flags=re.I)
    work = re.sub(rf"(?i)\bfrom\s+\S+\.(?:{_DATA_EXT})\b", " ", work)
    work = re.sub(r"(?i)\s+-o\s+\S+\.(?:png|jpe?g|webp)\b", " ", work)
    work = re.sub(r"(?i)\s+--output\s+\S+\.(?:png|jpe?g|webp)\b", " ", work)
    return work


def _temporal_side(a: str, b: str) -> tuple[str, str] | None:
    """Return (by/x, value/y) when one side looks time-like."""
    a_t, b_t = bool(_TEMPORAL.search(a)), bool(_TEMPORAL.search(b))
    if b_t and not a_t:
        return b, a
    if a_t and not b_t:
        return a, b
    return None


def _infer_chart_type(text: str, *, by: str | None, value: str | None) -> str | None:
    low = (text or "").lower()
    if re.search(r"(?i)\b(?:scatter|correlation|correlate|relationship)\b", low):
        return "scatter"
    if re.search(r"(?i)\b(?:line|trend|over\s+time|timeline)\b", low):
        return "line"
    if re.search(r"(?i)\b(?:bar|column|histogram|pareto|pie)\b", low):
        m = re.search(r"(?i)\b(pie|bar|line|scatter|histogram|pareto)\b", low)
        return m.group(1).lower() if m else None
    if by and _TEMPORAL.search(by):
        return "line"
    if re.search(r"(?i)\b(?:over|against|on)\b", low):
        return "line"
    if re.search(r"(?i)\b(?:vs\.?|versus)\b", low):
        return "scatter"
    return None


def parse_dataset_axes(text: str) -> DatasetAxes | None:
    """
    Extract X/Y column hints from NL (any column names — not hardcoded).

    Examples:
      time vs income from data.csv        → by=time, value=income
      plot income over time from data.csv → by=time, value=income
      by region value revenue             → by=region, value=revenue
    """
    raw = (text or "").strip()
    if not raw:
        return None

    extract_data_file_path(raw)
    work = _nl_work_text(raw)

    chart_type = _infer_chart_type(raw, by=None, value=None)

    # Y over X / Y against X / Y on X
    over = re.search(
        rf"(?i){_COL}\s+(?:over|against|on)\s+{_COL}",
        work,
    )
    if over:
        y_col = _clean_token(over.group(1))
        x_col = _clean_token(over.group(2))
        if y_col and x_col:
            ct = chart_type or "line"
            return DatasetAxes(by=x_col, value=y_col, chart_type=ct)

    # X vs Y
    versus = re.search(rf"(?i){_COL}\s+(?:vs\.?|versus)\s+{_COL}", work)
    if versus:
        a = _clean_token(versus.group(1))
        b = _clean_token(versus.group(2))
        if a and b:
            ordered = _temporal_side(a, b)
            if ordered:
                x_col, y_col = ordered
                ct = "line"
            else:
                x_col, y_col = a, b
                ct = chart_type or "scatter"
            return DatasetAxes(by=x_col, value=y_col, chart_type=ct)

    # by X value Y / grouped by X value Y
    by_val = re.search(
        rf"(?i)(?:grouped\s+by|group\s+by|by)\s+{_COL}\s+"
        rf"(?:value|values|metric|metrics|amount|amounts|column|columns|measure|and)\s+{_COL}",
        work,
    )
    if by_val:
        x_col = _clean_token(by_val.group(1))
        y_col = _clean_token(by_val.group(2))
        if x_col and y_col:
            ct = chart_type or ("line" if _TEMPORAL.search(x_col) else None)
            return DatasetAxes(by=x_col, value=y_col, chart_type=ct)

    # x-axis X y-axis Y
    axes = re.search(
        r"(?i)\bx[- ]?axis\s+(['\"][^'\"]+['\"]|\S+)\s+y[- ]?axis\s+(['\"][^'\"]+['\"]|\S+)",
        work,
    )
    if axes:
        x_col = _clean_token(axes.group(1))
        y_col = _clean_token(axes.group(2))
        if x_col and y_col:
            ct = chart_type or ("line" if _TEMPORAL.search(x_col) else None)
            return DatasetAxes(by=x_col, value=y_col, chart_type=ct)

    # columns X and Y / with X and Y / using X and Y
    pair = re.search(
        rf"(?i)\b(?:columns?|fields?|using|with)\s+{_COL}\s+and\s+{_COL}",
        work,
    )
    if pair:
        x_col = _clean_token(pair.group(1))
        y_col = _clean_token(pair.group(2))
        if x_col and y_col:
            ordered = _temporal_side(x_col, y_col)
            if ordered:
                x_col, y_col = ordered
            ct = chart_type or ("line" if _TEMPORAL.search(x_col) else None)
            return DatasetAxes(by=x_col, value=y_col, chart_type=ct)

    return None


def wants_dataset_file_chart(text: str) -> bool:
    """True when NL names a data file and requests a chart/table view."""
    if not extract_data_file_path(text):
        return False
    axes = parse_dataset_axes(text)
    if axes and (axes.by or axes.value):
        return True
    if _TABLE_CUE.search(text):
        return True
    if _CHART_CUE.search(text):
        return True
    if re.search(
        rf"(?i)\b(?:from|using|with)\b.*\.(?:{_DATA_EXT})\b|\b(?:csv|tsv|json|file|dataset)\b",
        text,
    ):
        return bool(re.search(r"(?i)\b(?:chart|graph|plot|visuali[sz]e|diagram|table)\b", text))
    return False
