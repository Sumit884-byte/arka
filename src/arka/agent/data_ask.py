#!/usr/bin/env python3
"""Ask natural-language questions about CSV, JSON, TSV, and other data files."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shlex
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass


SUPPORTED_FORMATS = (
    "csv",
    "json",
    "jsonl",
    "ndjson",
    "tsv",
    "yaml",
    "yml",
    "xml",
    "parquet",
    "xlsx",
    "xls",
    "sql",
)

_EXT_ALIASES = {"yml": "yaml", "ndjson": "jsonl", "xls": "xlsx"}

_DATA_EXT = "|".join(re.escape(ext) for ext in sorted(set(SUPPORTED_FORMATS) | set(_EXT_ALIASES), key=len, reverse=True))

_FILE_RE = re.compile(
    rf"(?i)(?:['\"]([^'\"]+\.(?:{_DATA_EXT}))['\"]"
    rf"|([~./][^\s'\"]+\.(?:{_DATA_EXT}))"
    rf"|([^\s'\"/\\]+\.(?:{_DATA_EXT}))\b)"
)

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"data_ask|ask_data|query_data|analyze_data|"
    r"(?:ask|query|analyze|analyse|summarize|summary\s+of|inspect|explore|describe)\s+(?:this\s+)?"
    r"(?:csv|json|jsonl|tsv|yaml|xml|parquet|xlsx|spreadsheet|data\s+file|dataset|table)|"
    r"(?:how\s+many|count|total|average|sum|max|min|top|who|what|which)\b.*\b(?:rows?|records?|entries?|columns?|salary|revenue|category)\b|"
    r"(?:rows?|records?|columns?)\s+(?:in|of|from)\s+[^\s]+\.(?:csv|json|jsonl|tsv|yaml|xml|parquet|xlsx)"
    r")\b"
)

_EXCLUDE_RE = re.compile(
    r"(?i)\b("
    r"(?:generate|create|make|mock|fake|sample|random|synthetic)\s+(?:\d+\s+)?(?:rows?\s+of\s+)?"
    r"(?:fake\s+|sample\s+|test\s+|mock\s+)?(?:\w+\s+){0,4}(?:data|dataset|records?|rows?)|"
    r"data_gen|generate_data|"
    r"fake\s+(?:users?|emails?|customers?|products?|sales|orders?|data|records?)|"
    r"sample\s+(?:csv|json|jsonl|tsv|yaml|xml|xlsx|sql|markdown)\s+data"
    r")\b"
)

_DEFAULT_QUESTION = (
    "Summarize this dataset: row count, columns, data types, key statistics, "
    "and any notable patterns or outliers."
)

_MAX_FULL_ROWS = 500
_SAMPLE_ROWS = 20
_MAX_CELL = 200
_MAX_CONTEXT_CHARS = 48_000


@dataclass
class LoadedData:
    path: Path
    fmt: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    notes: list[str] = field(default_factory=list)
    raw_preview: str | None = None


def _pandas():
    try:
        import pandas as pd  # noqa: F401

        return pd
    except ImportError:
        return None


def _detect_format(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    return _EXT_ALIASES.get(ext, ext)


def _truncate(value: Any, limit: int = _MAX_CELL) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    text = str(value)
    if len(text) <= limit:
        return value if not isinstance(value, str) else text
    return text[: limit - 3] + "..."


def _normalize_rows(raw_rows: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    if not raw_rows:
        return [], []
    if all(isinstance(row, dict) for row in raw_rows):
        columns: list[str] = []
        seen: set[str] = set()
        for row in raw_rows:
            for key in row:
                key_str = str(key)
                if key_str not in seen:
                    seen.add(key_str)
                    columns.append(key_str)
        normalized = [{str(k): _truncate(v) for k, v in row.items()} for row in raw_rows]
        return normalized, columns
    if all(isinstance(row, (list, tuple)) for row in raw_rows):
        width = max(len(row) for row in raw_rows)
        columns = [f"col_{i + 1}" for i in range(width)]
        normalized = []
        for row in raw_rows:
            item = {columns[i]: _truncate(row[i] if i < len(row) else None) for i in range(width)}
            normalized.append(item)
        return normalized, columns
    return [{"value": _truncate(raw_rows[0])}], ["value"]


def _load_with_pandas(path: Path, fmt: str) -> LoadedData | None:
    pd = _pandas()
    if pd is None:
        return None
    try:
        if fmt == "csv":
            df = pd.read_csv(path)
        elif fmt == "tsv":
            df = pd.read_csv(path, sep="\t")
        elif fmt == "json":
            df = pd.read_json(path)
        elif fmt == "jsonl":
            df = pd.read_json(path, lines=True)
        elif fmt == "parquet":
            df = pd.read_parquet(path)
        elif fmt in {"xlsx", "xls"}:
            df = pd.read_excel(path)
        else:
            return None
    except Exception:
        return None

    row_count = int(len(df))
    truncated = row_count > _MAX_FULL_ROWS
    sample_df = df.head(_SAMPLE_ROWS if truncated else row_count)
    rows = json.loads(sample_df.to_json(orient="records"))
    columns = [str(c) for c in df.columns.tolist()]
    notes = [f"Loaded with pandas ({row_count} rows)."]
    if truncated:
        notes.append(f"Showing first {_SAMPLE_ROWS} rows of {row_count}.")
    return LoadedData(path=path, fmt=fmt, rows=rows, columns=columns, row_count=row_count, truncated=truncated, notes=notes)


def _load_csv(path: Path, *, delimiter: str) -> LoadedData:
    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        columns = list(reader.fieldnames or [])
        for idx, row in enumerate(reader):
            if idx >= _MAX_FULL_ROWS:
                break
            rows.append({k: _truncate(v) for k, v in row.items()})
    truncated = False
    row_count = len(rows)
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        total = sum(1 for _ in csv.DictReader(handle, delimiter=delimiter))
    truncated = total > _MAX_FULL_ROWS
    row_count = total
    sample = rows[: _SAMPLE_ROWS] if truncated else rows
    notes = [f"Loaded {row_count} rows via csv module."]
    if truncated:
        notes.append(f"Showing first {len(sample)} rows.")
    return LoadedData(
        path=path,
        fmt="tsv" if delimiter == "\t" else "csv",
        rows=sample,
        columns=columns,
        row_count=row_count,
        truncated=truncated,
        notes=notes,
    )


def _load_json(path: Path) -> LoadedData:
    text = path.read_text(encoding="utf-8", errors="replace")
    payload = json.loads(text)
    if isinstance(payload, list):
        rows, columns = _normalize_rows(payload)
    elif isinstance(payload, dict):
        if payload and all(isinstance(v, (list, tuple)) for v in payload.values()):
            columns = [str(k) for k in payload]
            length = max(len(v) for v in payload.values())
            rows = []
            for i in range(min(length, _MAX_FULL_ROWS)):
                rows.append({col: _truncate(payload[col][i] if i < len(payload[col]) else None) for col in columns})
        else:
            rows, columns = _normalize_rows([payload])
    else:
        rows, columns = _normalize_rows([{"value": payload}])
    row_count = len(rows)
    truncated = row_count > _MAX_FULL_ROWS
    sample = rows[: _SAMPLE_ROWS] if truncated else rows
    notes = [f"Loaded JSON with {row_count} records."]
    if truncated:
        notes.append(f"Showing first {len(sample)} records.")
    return LoadedData(path=path, fmt="json", rows=sample, columns=columns, row_count=row_count, truncated=truncated, notes=notes)


def _load_jsonl(path: Path) -> LoadedData:
    rows: list[dict[str, Any]] = []
    row_count = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row_count += 1
            if len(rows) < _MAX_FULL_ROWS:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append({str(k): _truncate(v) for k, v in item.items()})
                else:
                    rows.append({"value": _truncate(item)})
    rows, columns = _normalize_rows(rows)
    truncated = row_count > _MAX_FULL_ROWS
    sample = rows[: _SAMPLE_ROWS] if truncated else rows
    notes = [f"Loaded JSONL with {row_count} lines."]
    if truncated:
        notes.append(f"Showing first {len(sample)} lines.")
    return LoadedData(path=path, fmt="jsonl", rows=sample, columns=columns, row_count=row_count, truncated=truncated, notes=notes)


def _load_yaml(path: Path) -> LoadedData:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("YAML files require PyYAML (pip install pyyaml)") from exc
    payload = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(payload, list):
        rows, columns = _normalize_rows(payload)
        row_count = len(rows)
    elif isinstance(payload, dict):
        rows, columns = _normalize_rows([payload])
        row_count = 1
    else:
        rows, columns = _normalize_rows([{"value": payload}])
        row_count = 1
    truncated = row_count > _MAX_FULL_ROWS
    sample = rows[: _SAMPLE_ROWS] if truncated else rows
    return LoadedData(
        path=path,
        fmt="yaml",
        rows=sample,
        columns=columns,
        row_count=row_count,
        truncated=truncated,
        notes=[f"Loaded YAML with {row_count} top-level records."],
    )


def _load_xml(path: Path) -> LoadedData:
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    rows: list[dict[str, Any]] = []
    if len(root):
        for child in list(root)[:_MAX_FULL_ROWS]:
            row = dict(child.attrib)
            if child.text and child.text.strip():
                row["_text"] = child.text.strip()
            for sub in child:
                tag = sub.tag.split("}")[-1]
                row[tag] = (sub.text or "").strip()
            rows.append({k: _truncate(v) for k, v in row.items()})
        columns = sorted({key for row in rows for key in row})
        row_count = len(root)
    else:
        rows = [{"tag": root.tag.split("}")[-1], "text": _truncate((root.text or "").strip())}]
        columns = list(rows[0])
        row_count = 1
    truncated = row_count > _MAX_FULL_ROWS
    sample = rows[: _SAMPLE_ROWS] if truncated else rows
    return LoadedData(
        path=path,
        fmt="xml",
        rows=sample,
        columns=columns,
        row_count=row_count,
        truncated=truncated,
        notes=[f"Parsed XML root <{root.tag.split('}')[-1]}> with {row_count} child records."],
    )


def _load_sql(path: Path) -> LoadedData:
    text = path.read_text(encoding="utf-8", errors="replace")
    preview = text[:8000]
    if len(text) > 8000:
        preview += "\n... [truncated]"
    insert_re = re.compile(
        r"(?is)insert\s+into\s+[`\"']?(\w+)[`\"']?\s*\(([^)]+)\)\s*values\s*(.+?);"
    )
    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    for match in insert_re.finditer(text):
        table = match.group(1)
        columns = [c.strip(" `\"'") for c in match.group(2).split(",")]
        values_blob = match.group(3)
        tuple_re = re.compile(r"\(([^)]*)\)")
        for tuple_match in tuple_re.finditer(values_blob):
            if len(rows) >= _MAX_FULL_ROWS:
                break
            parts = [p.strip().strip("'\"") for p in re.split(r",(?=(?:[^']*'[^']*')*[^']*$)", tuple_match.group(1))]
            row = {columns[i]: _truncate(parts[i] if i < len(parts) else None) for i in range(len(columns))}
            row["_table"] = table
            rows.append(row)
        if rows:
            break
    if rows:
        if "_table" not in columns:
            columns = ["_table", *columns]
        notes = [f"Parsed {len(rows)} INSERT rows from SQL dump."]
        row_count = len(rows)
    else:
        notes = ["SQL dump loaded as text preview (no INSERT rows parsed)."]
        row_count = 0
        columns = []
    return LoadedData(
        path=path,
        fmt="sql",
        rows=rows[: _SAMPLE_ROWS],
        columns=columns,
        row_count=row_count,
        truncated=len(rows) > _SAMPLE_ROWS,
        notes=notes,
        raw_preview=preview if not rows else None,
    )


def load_data(path: str | Path) -> LoadedData:
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise FileNotFoundError(f"Data file not found: {file_path}")

    fmt = _detect_format(file_path)
    if fmt not in SUPPORTED_FORMATS and fmt not in _EXT_ALIASES:
        raise ValueError(f"Unsupported data format: .{fmt}")

    tabular = {"csv", "tsv", "json", "jsonl", "parquet", "xlsx", "xls"}
    if fmt in tabular:
        loaded = _load_with_pandas(file_path, fmt)
        if loaded is not None:
            return loaded

    if fmt == "csv":
        return _load_csv(file_path, delimiter=",")
    if fmt == "tsv":
        return _load_csv(file_path, delimiter="\t")
    if fmt == "json":
        return _load_json(file_path)
    if fmt == "jsonl":
        return _load_jsonl(file_path)
    if fmt in {"yaml", "yml"}:
        return _load_yaml(file_path)
    if fmt == "xml":
        return _load_xml(file_path)
    if fmt == "parquet":
        raise RuntimeError("Parquet requires pyarrow or pandas (pip install pyarrow pandas)")
    if fmt in {"xlsx", "xls"}:
        raise RuntimeError("Excel files require openpyxl or pandas (pip install openpyxl pandas)")
    if fmt == "sql":
        return _load_sql(file_path)
    raise ValueError(f"Unsupported data format: .{fmt}")


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if value is None:
        return False
    text = str(value).strip().replace(",", "")
    if not text:
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False


def _to_float(value: Any) -> float | None:
    if not _is_number(value):
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except ValueError:
        return None


def column_stats(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for col in columns:
        values = [row.get(col) for row in rows if col in row]
        non_null = [v for v in values if v not in (None, "")]
        info: dict[str, Any] = {
            "non_null": len(non_null),
            "null_or_empty": len(values) - len(non_null),
        }
        nums = [n for n in (_to_float(v) for v in non_null) if n is not None]
        if nums and len(nums) >= max(1, len(non_null) // 2):
            info["type"] = "numeric"
            info["min"] = min(nums)
            info["max"] = max(nums)
            info["mean"] = round(statistics.fmean(nums), 4)
            if len(nums) > 1:
                info["stdev"] = round(statistics.pstdev(nums), 4)
        else:
            info["type"] = "categorical"
            counter = Counter(str(v) for v in non_null)
            info["unique"] = len(counter)
            info["top_values"] = counter.most_common(5)
        stats[col] = info
    return stats


def build_context(data: LoadedData) -> str:
    parts = [
        f"File: {data.path.name}",
        f"Format: {data.fmt}",
        f"Rows: {data.row_count}",
        f"Columns ({len(data.columns)}): {', '.join(data.columns) if data.columns else '(none)'}",
    ]
    for note in data.notes:
        parts.append(f"Note: {note}")
    if data.truncated:
        parts.append("Sample-only mode: full file is larger than inline context limit.")

    if data.columns and data.rows:
        stats = column_stats(data.rows, data.columns)
        parts.append("\nColumn statistics (from sample/full load):")
        for col, info in stats.items():
            if info.get("type") == "numeric":
                parts.append(
                    f"- {col}: numeric, min={info['min']}, max={info['max']}, mean={info['mean']}, "
                    f"non_null={info['non_null']}"
                )
            else:
                tops = ", ".join(f"{name}({count})" for name, count in info.get("top_values", [])[:3])
                parts.append(
                    f"- {col}: categorical, unique={info.get('unique', 0)}, non_null={info['non_null']}"
                    + (f", top={tops}" if tops else "")
                )

    if data.rows:
        parts.append("\nSample rows:")
        parts.append(json.dumps(data.rows[: _SAMPLE_ROWS], indent=2, ensure_ascii=False))
    elif data.raw_preview:
        parts.append("\nFile preview:")
        parts.append(data.raw_preview)

    context = "\n".join(parts)
    if len(context) > _MAX_CONTEXT_CHARS:
        context = context[: _MAX_CONTEXT_CHARS - 20] + "\n... [context truncated]"
    return context


def extract_file_path(text: str) -> str | None:
    for match in _FILE_RE.finditer(text or ""):
        for group in match.groups():
            if group:
                return group.strip()
    return None


def _strip_route_prefix(text: str) -> str:
    clean = (text or "").strip()
    clean = re.sub(r"(?i)^(?:arka\s+)?(?:data_ask|ask_data|query_data|analyze_data)\b\s*", "", clean)
    clean = re.sub(r"(?i)^(?:ask|query|analyze|analyse)\s+data\b\s*", "", clean)
    return clean.strip()


def parse_request(text: str) -> tuple[str | None, str]:
    clean = _strip_route_prefix(text)
    file_path = extract_file_path(clean)
    question = clean
    if file_path:
        question = question.replace(file_path, " ")
        question = re.sub(r"(?i)['\"]" + re.escape(file_path) + r"['\"]", " ", question)
    question = re.sub(
        r"(?i)\b(?:ask|query|analyze|analyse|summarize|summary\s+of|inspect|explore|describe)\s+"
        r"(?:this\s+)?(?:csv|json|jsonl|tsv|yaml|xml|parquet|xlsx|spreadsheet|data\s+file|dataset|table)\b",
        " ",
        question,
    )
    question = re.sub(r"(?i)\babout\s+", "", question)
    question = re.sub(r"(?i)\b(?:in|from|on)\s+this\s+(?:csv|json|jsonl|tsv|yaml|xml|parquet|xlsx|file|dataset)\b", " ", question)
    question = re.sub(r"\s+", " ", question).strip(" ,;:-")
    if not question:
        question = _DEFAULT_QUESTION
    return file_path, question


def wants_data_ask(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if _EXCLUDE_RE.search(clean):
        return False
    try:
        from arka.agent.generate_data import wants_generate_data

        if wants_generate_data(clean):
            return False
    except ImportError:
        pass
    if re.search(r"(?i)\b(data_ask|ask_data|query_data|analyze_data)\b", clean):
        return bool(extract_file_path(clean) or _FILE_RE.search(clean))
    if extract_file_path(clean) and _TRIGGER_RE.search(clean):
        return True
    if extract_file_path(clean) and re.search(
        r"(?i)\b(how many|count|total|average|sum|max|min|top|who|what|which|summarize|summary|analyze|analyse|query|ask)\b",
        clean,
    ):
        return True
    return False


def route_command(text: str) -> str:
    if not wants_data_ask(text):
        return ""
    file_path, question = parse_request(text)
    if not file_path:
        return ""
    parts = ["data_ask", shlex.quote(file_path)]
    if question and question != _DEFAULT_QUESTION:
        parts.append(shlex.quote(question))
    return " ".join(parts)


def nl_to_argv(text: str) -> list[str]:
    route = route_command(text)
    if not route:
        return []
    return shlex.split(route)[1:]


def answer_question(path: str | Path, question: str) -> str:
    data = load_data(path)
    context = build_context(data)
    system = (
        "You answer questions about structured data files using only the provided context. "
        "Be concise and specific. If the sample is truncated, say when an answer is approximate. "
        "Use numbers, lists, or short paragraphs as appropriate. If the data is insufficient, say so."
    )
    user = f"Question: {question}\n\nData context:\n{context}"
    try:
        from arka.llm.cli import llm_complete
    except ImportError as exc:
        raise RuntimeError("LLM support is unavailable") from exc
    return llm_complete(system, user, temperature=0.2, task="chat", skill="data_ask").strip()


def cmd_ask(args: argparse.Namespace) -> int:
    file_path = args.file
    question = " ".join(args.question).strip() if args.question else _DEFAULT_QUESTION
    if not question:
        question = _DEFAULT_QUESTION
    try:
        answer = answer_question(file_path, question)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not answer:
        print("No answer returned (check LLM configuration).", file=sys.stderr)
        return 1
    print(answer)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ask questions about CSV, JSON, TSV, and other data files")
    sub = p.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to data_ask command")
    p_route.add_argument("text", nargs="+")
    p_route.set_defaults(func=lambda a: _cmd_route(a))

    p_parse = sub.add_parser("parse", help="Map NL to CLI args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=lambda a: _cmd_parse(a))

    p_parse_ask = sub.add_parser("parse-ask", help="Parse NL ask request (file\\tquestion)")
    p_parse_ask.add_argument("text", nargs="+")
    p_parse_ask.set_defaults(func=lambda a: _cmd_parse_ask(a))

    p_ask = sub.add_parser("ask", help="Ask a question about a data file")
    p_ask.add_argument("file")
    p_ask.add_argument("question", nargs="*")
    p_ask.set_defaults(func=cmd_ask)
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


def _cmd_parse_ask(args: argparse.Namespace) -> int:
    file_path, question = parse_request(" ".join(args.text))
    if not file_path:
        return 1
    print(f"{file_path}\t{question}")
    return 0


def _build_ask_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ask questions about data files")
    p.add_argument("file", nargs="?", default=None)
    p.add_argument("question", nargs="*")
    return p


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] in ("route", "parse", "parse-ask", "ask"):
        args = build_parser().parse_args(argv)
        return int(args.func(args))

    if argv and argv[0] == "--":
        argv = argv[1:]

    if argv and not any(a.startswith("-") for a in argv[:1]) and wants_data_ask(" ".join(argv)):
        nl_args = nl_to_argv(" ".join(argv))
        if nl_args:
            argv = nl_args

    parser = _build_ask_parser()
    args = parser.parse_args(argv)
    if not args.file:
        parser.print_help()
        return 1
    return cmd_ask(args)


if __name__ == "__main__":
    raise SystemExit(main())
