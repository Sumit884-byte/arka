#!/usr/bin/env python3
"""Generate fake or sample datasets in CSV, JSON, TSV, and other formats."""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import secrets
import shlex
import string
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

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
    "tsv",
    "xml",
    "yaml",
    "sql",
    "markdown",
    "md",
    "xlsx",
)

PRESET_FIELDS: dict[str, list[str]] = {
    "users": ["id", "name", "email", "age", "phone"],
    "user": ["name", "email", "age"],
    "customers": ["id", "name", "email", "address", "phone"],
    "customer": ["name", "email", "phone"],
    "products": ["id", "name", "price", "category"],
    "product": ["id", "name", "price", "category"],
    "sales": ["date", "product", "quantity", "revenue", "region"],
    "orders": ["id", "customer", "product", "quantity", "total", "date"],
    "emails": ["email"],
    "email": ["email"],
    "phones": ["phone"],
    "phone": ["phone"],
    "addresses": ["address", "city", "state", "zip"],
    "employees": ["id", "name", "email", "department", "salary"],
}

_CATEGORIES = ("Electronics", "Books", "Clothing", "Home", "Sports", "Food", "Toys", "Garden")
_REGIONS = ("North", "South", "East", "West", "Central")
_DEPARTMENTS = ("Engineering", "Sales", "Marketing", "Support", "Finance", "HR")

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"(?:generate|create|make|mock|fake|sample)\s+(?:\d+\s+)?(?:rows?\s+of\s+)?"
    r"(?:fake\s+|sample\s+|test\s+|mock\s+)?(?:\w+\s+){0,4}(?:data|dataset|records?|rows?)|"
    r"(?:generate|create)\s+\d+\s+\w+\s+(?:as|in|to)\s+(?:csv|json|jsonl|tsv|yaml|xml|xlsx|sql|markdown)|"
    r"data_gen|generate_data|"
    r"fake\s+(?:users?|emails?|customers?|products?|sales|orders?|data|records?)|"
    r"sample\s+(?:csv|json|jsonl|tsv|yaml|xml|xlsx|sql|markdown)\s+data"
    r")\b"
)

_EXCLUDE_RE = re.compile(
    r"(?i)\b("
    r"password|thumbnail|video|ascii\s+art|figlet|"
    r"image|picture|photo|art|drawing|sketch|painting|illustration|portrait|landscape"
    r")\b"
)

_COUNT_RE = re.compile(
    r"(?i)\b(\d+)\s+(?:rows?|records?|entries?|items?|users?|customers?|products?|orders?|emails?)\b"
    r"|\b(?:rows?|count|records?)\s*[=:]?\s*(\d+)\b"
    r"|\b--rows?\s+(\d+)\b"
)

_FORMAT_RE = re.compile(
    r"(?i)\b(?:as|in|to|format)\s+(csv|json|jsonl|tsv|yaml|yml|xml|xlsx|sql|markdown|md)\b"
    r"|\b(csv|json|jsonl|tsv|yaml|yml|xml|xlsx|sql|markdown|md)\b(?:\s+data|\s+file|\s*$|\s+--)"
)

_FIELDS_RE = re.compile(
    r'--(?:schema|fields)\s+["\']?([^"\']+?)["\']?(?=\s+--|\s*$)'
    r"|(?:with|fields?|columns?|schema)\s+[\"']?([a-z0-9_,\s-]+)[\"']?",
    re.IGNORECASE,
)


def _faker():
    try:
        from faker import Faker

        return Faker()
    except ImportError:
        return None


def wants_generate_data(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if _EXCLUDE_RE.search(clean):
        return False
    return bool(_TRIGGER_RE.search(clean))


def _extract_count(text: str) -> int | None:
    for m in _COUNT_RE.finditer(text):
        for g in m.groups():
            if g:
                return max(1, min(int(g), 100_000))
    m = re.search(r"(?i)\bgenerate\s+(\d+)\b", text)
    if m:
        return max(1, min(int(m.group(1)), 100_000))
    return None


def _extract_format(text: str) -> str | None:
    formats = ("csv", "json", "jsonl", "tsv", "yaml", "yml", "xml", "xlsx", "sql", "markdown", "md")
    m = _FORMAT_RE.search(text)
    if m:
        fmt = next(g for g in m.groups() if g).lower()
        return "yaml" if fmt == "yml" else ("markdown" if fmt == "md" else fmt)
    found = None
    for token in re.findall(rf"(?i)\b({'|'.join(formats)})\b", text):
        found = token.lower()
    if found:
        return "yaml" if found == "yml" else ("markdown" if found == "md" else found)
    return None


def _extract_fields(text: str) -> str | None:
    m = _FIELDS_RE.search(text)
    if not m:
        return None
    raw = (m.group(1) or m.group(2) or "").strip()
    if not raw:
        return None
    return ",".join(part.strip() for part in re.split(r"[,;]", raw) if part.strip())


def _extract_preset(text: str) -> str | None:
    if re.search(r"(?i)--(?:schema|fields)\b", text):
        return None
    clean = text.lower()
    for key in sorted(PRESET_FIELDS, key=len, reverse=True):
        if re.search(rf"(?i)\b{re.escape(key)}\b", clean):
            return key
    m = re.search(r"(?i)\b(?:generate|create|mock|fake|sample)\s+\d+\s+(\w+)\s+(?:as|in|to)\b", text)
    if m:
        return m.group(1).lower()
    m = re.search(r"(?i)\b(?:generate|create|mock|fake|sample)\s+(\w+)\s+data\b", text)
    if m:
        return m.group(1).lower()
    return None


def route_command(text: str) -> str:
    if not wants_generate_data(text):
        return ""
    clean = (text or "").strip()
    count = _extract_count(clean) or 10
    fmt = _extract_format(clean) or "csv"
    fields = _extract_fields(clean)
    preset = _extract_preset(clean)

    parts = ["generate_data"]
    if preset and preset in PRESET_FIELDS:
        parts.append(preset)
    parts.extend(["--count", str(count), "--format", fmt])
    if fields:
        parts.extend(["--fields", fields])
    return " ".join(parts)


def nl_to_argv(text: str) -> list[str]:
    route = route_command(text)
    if not route:
        return []
    return shlex.split(route)[1:]  # drop skill name


def _parse_fields(fields: str | None, preset: str | None) -> list[str]:
    if fields:
        return [f.strip() for f in re.split(r"[,;]", fields) if f.strip()]
    if preset:
        key = preset.lower()
        if key in PRESET_FIELDS:
            return list(PRESET_FIELDS[key])
    return ["id", "name", "email"]


def _rand_word(n: int = 6) -> str:
    return "".join(secrets.choice(string.ascii_lowercase) for _ in range(n))


def _rand_name(fake: Any | None) -> str:
    if fake:
        return fake.name()
    first = secrets.choice(("Alex", "Jordan", "Taylor", "Sam", "Casey", "Riley", "Morgan", "Avery"))
    last = secrets.choice(("Smith", "Johnson", "Lee", "Patel", "Garcia", "Kim", "Brown", "Singh"))
    return f"{first} {last}"


def _rand_email(fake: Any | None) -> str:
    if fake:
        return fake.email()
    return f"{_rand_word(8)}.{_rand_word(5)}@example.com"


def _rand_phone(fake: Any | None) -> str:
    if fake:
        return fake.phone_number()
    return f"+1-{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}"


def _rand_address(fake: Any | None) -> str:
    if fake:
        return fake.address().replace("\n", ", ")
    return f"{random.randint(100, 9999)} {_rand_word(7).title()} St"


def _field_generator(name: str, fake: Any | None) -> Callable[[int], Any]:
    key = name.lower().strip()

    if key in ("id", "user_id", "product_id", "order_id", "customer_id"):
        return lambda i: i
    if key in ("name", "full_name", "customer", "customer_name", "product"):
        return lambda _i: _rand_name(fake)
    if key == "first_name":
        return lambda _i: (_rand_name(fake).split()[0] if fake else secrets.choice(("Alex", "Jordan", "Taylor")))
    if key == "last_name":
        return lambda _i: (_rand_name(fake).split()[-1] if fake else secrets.choice(("Smith", "Lee", "Patel")))
    if "email" in key:
        return lambda _i: _rand_email(fake)
    if "phone" in key or key in ("mobile", "tel"):
        return lambda _i: _rand_phone(fake)
    if "address" in key or key == "street":
        return lambda _i: _rand_address(fake)
    if key in ("city",):
        return lambda _i: fake.city() if fake else secrets.choice(("Austin", "Seattle", "Boston", "Denver"))
    if key in ("state", "province"):
        return lambda _i: fake.state_abbr() if fake else secrets.choice(("CA", "TX", "NY", "WA"))
    if key in ("zip", "zipcode", "postal", "postal_code"):
        return lambda _i: fake.postcode() if fake else f"{random.randint(10000, 99999)}"
    if key in ("country", "region"):
        return lambda _i: secrets.choice(_REGIONS if key == "region" else ("USA", "Canada", "UK", "India"))
    if key in ("age",):
        return lambda _i: random.randint(18, 80)
    if key in ("price", "amount", "revenue", "total", "salary", "cost"):
        return lambda _i: round(random.uniform(5, 5000), 2)
    if key in ("quantity", "qty", "count"):
        return lambda _i: random.randint(1, 50)
    if key in ("category",):
        return lambda _i: secrets.choice(_CATEGORIES)
    if key in ("department", "dept"):
        return lambda _i: secrets.choice(_DEPARTMENTS)
    if key in ("date", "order_date", "created_at"):
        return lambda _i: (date.today() - timedelta(days=random.randint(0, 365))).isoformat()
    if key in ("datetime", "timestamp", "updated_at"):
        return lambda _i: (
            datetime.now() - timedelta(days=random.randint(0, 365), seconds=random.randint(0, 86400))
        ).isoformat(timespec="seconds")
    if key in ("uuid", "guid"):
        return lambda _i: str(uuid.uuid4())
    if key.startswith("is_") or key in ("active", "enabled", "boolean", "bool"):
        return lambda _i: random.choice((True, False))
    if key.endswith("_id"):
        return lambda i: i
    return lambda _i: fake.word() if fake else _rand_word(random.randint(4, 10))


def generate_rows(fields: list[str], count: int, *, seed: int | None = None) -> list[dict[str, Any]]:
    if seed is not None:
        random.seed(seed)
    fake = _faker()
    gens = {f: _field_generator(f, fake) for f in fields}
    rows: list[dict[str, Any]] = []
    for i in range(1, count + 1):
        rows.append({field: gens[field](i) for field in fields})
    return rows


def _llm_generate_rows(fields: list[str], count: int) -> list[dict[str, Any]] | None:
    try:
        from arka.llm.cli import llm_complete
    except ImportError:
        return None
    system = (
        "You generate realistic fake tabular data. Reply with ONLY a JSON array of objects. "
        "Each object must have exactly these keys (same spelling): "
        + ", ".join(fields)
        + ". No markdown fences, no commentary."
    )
    user = f"Generate {count} rows of sample data."
    raw = llm_complete(system, user, temperature=0.7, task="chat", skill="generate_data").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    rows: list[dict[str, Any]] = []
    for item in data[:count]:
        if isinstance(item, dict):
            rows.append({f: item.get(f, "") for f in fields})
    return rows or None


def format_rows(rows: list[dict[str, Any]], fmt: str, *, table: str = "sample_data") -> str:
    fmt = fmt.lower()
    if fmt == "md":
        fmt = "markdown"
    if fmt == "yml":
        fmt = "yaml"

    if fmt == "json":
        return json.dumps(rows, indent=2, default=str)
    if fmt == "jsonl":
        return "\n".join(json.dumps(r, default=str) for r in rows) + ("\n" if rows else "")
    if fmt in ("csv", "tsv"):
        buf = io.StringIO()
        if not rows:
            return ""
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter="\t" if fmt == "tsv" else ",")
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()
    if fmt == "yaml":
        lines: list[str] = []
        for row in rows:
            lines.append("-")
            for k, v in row.items():
                if isinstance(v, bool):
                    lines.append(f"  {k}: {'true' if v else 'false'}")
                elif isinstance(v, str) and re.search(r"[:\n#'\"]", v):
                    lines.append(f"  {k}: {json.dumps(v)}")
                else:
                    lines.append(f"  {k}: {v}")
        return "\n".join(lines) + ("\n" if lines else "")
    if fmt == "xml":
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', f"<{table}>"]
        for i, row in enumerate(rows, 1):
            lines.append(f"  <row id=\"{i}\">")
            for k, v in row.items():
                tag = re.sub(r"[^a-zA-Z0-9_]", "_", k)
                text = str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                lines.append(f"    <{tag}>{text}</{tag}>")
            lines.append("  </row>")
        lines.append(f"</{table}>")
        return "\n".join(lines)
    if fmt == "sql":
        if not rows:
            return ""
        cols = list(rows[0].keys())
        col_sql = ", ".join(cols)
        lines = []
        for row in rows:
            vals = []
            for c in cols:
                v = row[c]
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, bool):
                    vals.append("TRUE" if v else "FALSE")
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
                else:
                    vals.append("'" + str(v).replace("'", "''") + "'")
            lines.append(f"INSERT INTO {table} ({col_sql}) VALUES ({', '.join(vals)});")
        return "\n".join(lines) + "\n"
    if fmt == "markdown":
        if not rows:
            return ""
        cols = list(rows[0].keys())
        header = "| " + " | ".join(cols) + " |"
        sep = "| " + " | ".join("---" for _ in cols) + " |"
        body = ["| " + " | ".join(str(row[c]) for c in cols) + " |" for row in rows]
        return "\n".join([header, sep, *body]) + "\n"
    raise ValueError(f"Unsupported format: {fmt}")


def format_rows_xlsx(rows: list[dict[str, Any]], *, table: str = "sample_data") -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("xlsx output requires openpyxl (pip install openpyxl)") from exc
    wb = Workbook()
    ws = wb.active
    ws.title = table[:31]
    cols = list(rows[0].keys()) if rows else []
    if cols:
        ws.append(cols)
        for row in rows:
            ws.append([row[c] for c in cols])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _infer_output_path(arg: str | None, fmt: str) -> Path | None:
    if not arg:
        return None
    p = Path(arg)
    if p.suffix:
        return p
    return None


def cmd_generate(args: argparse.Namespace) -> int:
    preset = args.preset
    fields = _parse_fields(args.fields or args.schema, preset)
    count = max(1, min(int(args.count), 100_000))
    fmt = (args.format or "csv").lower()
    if fmt == "md":
        fmt = "markdown"
    if fmt == "yml":
        fmt = "yaml"
    if fmt not in SUPPORTED_FORMATS:
        print(f"Unsupported format '{fmt}'. Choose: {', '.join(SUPPORTED_FORMATS)}", file=sys.stderr)
        return 1

    rows = generate_rows(fields, count, seed=args.seed)
    if args.llm:
        llm_rows = _llm_generate_rows(fields, count)
        if llm_rows:
            rows = llm_rows

    table = re.sub(r"[^a-zA-Z0-9_]", "_", (preset or "sample_data").lower())
    out_path = args.output or _infer_output_path(getattr(args, "output_file", None), fmt)
    try:
        if fmt == "xlsx":
            payload = format_rows_xlsx(rows, table=table)
            if out_path:
                Path(out_path).write_bytes(payload)
                print(f"Wrote {count} rows to {out_path}")
            else:
                sys.stdout.buffer.write(payload)
            return 0
        text = format_rows(rows, fmt, table=table)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
        print(f"Wrote {count} rows to {out_path}")
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate sample data in CSV, JSON, TSV, and more")
    sub = p.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to generate_data command")
    p_route.add_argument("text", nargs="+")
    p_route.set_defaults(func=lambda a: _cmd_route(a))

    p_parse = sub.add_parser("parse", help="Map NL to CLI args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=lambda a: _cmd_parse(a))

    p_gen = sub.add_parser("generate", help="Generate dataset")
    p_gen.add_argument("preset", nargs="?", default=None, help="Preset name (users, sales, products, …)")
    p_gen.add_argument("name", nargs="?", default=None, help="Optional output filename hint")
    p_gen.add_argument("--count", "-n", type=int, default=10)
    p_gen.add_argument("--rows", type=int, dest="count")
    p_gen.add_argument("--format", "-f", default="csv")
    p_gen.add_argument("--fields", default=None)
    p_gen.add_argument("--schema", default=None)
    p_gen.add_argument("-o", "--output", default=None)
    p_gen.add_argument("--seed", type=int, default=None)
    p_gen.add_argument("--llm", action="store_true", help="Use LLM for complex custom schemas")
    p_gen.set_defaults(func=cmd_generate)

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


def _build_generate_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate sample data")
    p.add_argument("preset", nargs="?", default=None, help="Preset name (users, sales, products, …)")
    p.add_argument("output_file", nargs="?", default=None, help="Optional output filename")
    p.add_argument("--count", "-n", type=int, default=10)
    p.add_argument("--rows", type=int, default=None)
    p.add_argument("--format", "-f", default="csv")
    p.add_argument("--fields", default=None)
    p.add_argument("--schema", default=None)
    p.add_argument("-o", "--output", default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--llm", action="store_true", help="Use LLM for complex custom schemas")
    return p


def _parse_generate_argv(argv: list[str]) -> argparse.Namespace:
    parser = _build_generate_parser()
    if argv and Path(argv[0]).suffix.lower().lstrip(".") in (*SUPPORTED_FORMATS, "md", "yml"):
        out_file = argv.pop(0)
        args = parser.parse_args(argv)
        args.output = args.output or out_file
        if args.format == "csv":
            ext = Path(out_file).suffix.lower().lstrip(".")
            args.format = "yaml" if ext == "yml" else ("markdown" if ext == "md" else ext)
        return args
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] in ("route", "parse"):
        args = build_parser().parse_args(argv)
        return int(args.func(args))

    if argv and argv[0] == "--":
        argv = argv[1:]

    if argv and argv[0] == "generate":
        argv = argv[1:]

    # NL passthrough: "generate 100 users as csv"
    if argv and not any(a.startswith("-") for a in argv[:1]) and wants_generate_data(" ".join(argv)):
        nl_args = nl_to_argv(" ".join(argv))
        if nl_args:
            argv = nl_args

    args = _parse_generate_argv(argv)
    if args.rows is not None:
        args.count = args.rows
    return cmd_generate(args)


if __name__ == "__main__":
    raise SystemExit(main())
