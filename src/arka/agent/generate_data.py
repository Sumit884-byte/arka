#!/usr/bin/env python3
"""Generate fake or sample datasets, or fetch rows from real-world sources."""

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
import urllib.error
import urllib.request
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

REAL_SOURCES = frozenset({"worldbank", "pubmed", "url", "web"})
MAX_REAL_ROWS = 500
_USER_AGENT = "Mozilla/5.0 (compatible; Arka-GenerateData/1.0)"

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
    r"(?:generate|create|make|mock|fake|sample|fetch|get)\s+(?:\d+\s+)?(?:rows?\s+of\s+)?"
    r"(?:fake\s+|sample\s+|test\s+|mock\s+|real\s+|actual\s+|live\s+)?(?:\w+\s+){0,6}(?:data|dataset|records?|rows?|papers?)|"
    r"(?:generate|create|fetch|get)\s+\d+\s+\w+\s+(?:as|in|to)\s+(?:csv|json|jsonl|tsv|yaml|xml|xlsx|sql|markdown)|"
    r"(?:generate|create|fetch|get)\s+(?:real|actual|live)\s+|"
    r"(?:generate|create|fetch|get)\s+\d+\s+pubmed\b|"
    r"(?:generate|create|fetch|get).*\bworld\s*bank\b|"
    r"(?:generate|create|fetch|get).*\bpubmed\b.*\bpapers?\b|"
    r"(?:generate|create|fetch|get)\s+(?:data\s+)?from\s+https?://|"
    r"data_gen|generate_data|"
    r"fake\s+(?:users?|emails?|customers?|products?|sales|orders?|data|records?)|"
    r"sample\s+(?:csv|json|jsonl|tsv|yaml|xml|xlsx|sql|markdown)\s+data"
    r")\b"
)

_FAKE_CUE_RE = re.compile(r"(?i)\b(?:fake|mock|sample|test)\b")
_REAL_CUE_RE = re.compile(
    r"(?i)\b(?:real|actual|live)\b|\bworld\s*bank\b|\bfrom\s+https?://"
    r"|\b(?:generate|create|fetch|get)\s+\d+\s+pubmed\b"
    r"|\b(?:generate|create|fetch|get).*\bpubmed\b.*\bpapers?\b"
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
    source = _detect_source(clean) if _wants_real_source(clean) else None

    parts = ["generate_data"]
    if source:
        parts.extend(["--source", source])
        if source == "worldbank":
            indicator = _extract_indicator(clean)
            country = _extract_country_code(clean)
            y0, y1 = _extract_year_bounds(clean)
            if indicator:
                parts.extend(["--indicator", indicator])
            if country:
                parts.extend(["--country", country])
            if y0 is not None:
                parts.extend(["--year-from", str(y0)])
            if y1 is not None:
                parts.extend(["--year-to", str(y1)])
        elif source == "pubmed":
            query = _extract_pubmed_query(clean)
            if query:
                parts.append("--query")
                parts.append(query)
        elif source == "url":
            url = _extract_url(clean)
            if url:
                parts.extend(["--url", url])
        elif source == "web":
            query = _extract_pubmed_query(clean) or clean
            parts.append("--query")
            parts.append(query)
        if count > MAX_REAL_ROWS:
            count = MAX_REAL_ROWS
    elif preset and preset in PRESET_FIELDS:
        parts.append(preset)

    parts.extend(["--count", str(count), "--format", fmt])
    if fields and not source:
        parts.extend(["--fields", fields])
    return shlex.join(parts)


def nl_to_argv(text: str) -> list[str]:
    route = route_command(text)
    if not route:
        return []
    return shlex.split(route)[1:]  # drop skill name


def _wants_real_source(text: str) -> bool:
    clean = (text or "").strip()
    if not clean or _FAKE_CUE_RE.search(clean):
        return False
    return bool(_REAL_CUE_RE.search(clean))


def _detect_source(text: str) -> str | None:
    clean = (text or "").strip()
    if re.search(r"(?i)\b(?:world\s*bank|worldbank)\b", clean):
        return "worldbank"
    if re.search(r"(?i)\b(?:generate|create|fetch|get).*\bpubmed\b", clean):
        return "pubmed"
    if re.search(r"(?i)https?://", clean):
        return "url"
    if _wants_real_source(clean):
        try:
            from arka.charts.data import detect_topic

            if detect_topic(clean):
                return "worldbank"
        except ImportError:
            pass
        if re.search(r"(?i)\bpapers?\b", clean):
            return "pubmed"
    return None


def _extract_url(text: str) -> str | None:
    m = re.search(r'https?://[^\s"\']+', text or "")
    return m.group(0).rstrip(".,;)]}") if m else None


def _extract_pubmed_query(text: str) -> str | None:
    clean = (text or "").strip()
    for pat in (
        r'(?i)(?:papers?\s+on|about|for|search(?:ing)?)\s+["\']([^"\']+)["\']',
        r'(?i)(?:papers?\s+on|about|for)\s+(.+?)(?:\s+as\s+|\s+in\s+|\s+to\s+|\s+--|\s*$)',
        r'(?i)pubmed\s+(?:papers?\s+)?(?:on|about|for)\s+(.+?)(?:\s+as\s+|\s+in\s+|\s+to\s+|\s+--|\s*$)',
    ):
        m = re.search(pat, clean)
        if m:
            q = m.group(1).strip().strip('"\'')
            if q:
                return q
    m = re.search(r'(?i)["\']([^"\']{3,})["\']', clean)
    if m:
        return m.group(1).strip()
    return None


def _extract_indicator(text: str) -> str | None:
    try:
        from arka.charts.data import INDICATORS, detect_topic

        key = detect_topic(text or "")
        if key and key in INDICATORS:
            return key
    except ImportError:
        pass
    m = re.search(r"(?i)--indicator\s+(\w+)", text or "")
    return m.group(1).lower() if m else None


def _extract_country_code(text: str) -> str | None:
    m = re.search(r"(?i)--country\s+([A-Za-z]{2,3})\b", text or "")
    if m:
        return m.group(1).upper()
    try:
        from arka.charts.data import COUNTRY_CODES, extract_countries

        codes = extract_countries(text or "")
        if codes:
            return codes[0]
        low = (text or "").lower()
        for name, code in COUNTRY_CODES.items():
            if re.search(rf"\b{re.escape(name)}\b", low):
                return code
    except ImportError:
        pass
    return None


def _extract_year_bounds(text: str) -> tuple[int | None, int | None]:
    try:
        from arka.charts.data import extract_year_range

        return extract_year_range(text or "")
    except ImportError:
        return (None, None)


def _infer_real_source(
    *,
    url: str | None = None,
    indicator: str | None = None,
    country: str | None = None,
    query: str | None = None,
    text: str = "",
) -> str:
    if url:
        return "url"
    if indicator or country:
        return "worldbank"
    if query and re.search(r"(?i)\bpubmed\b|\bpapers?\b", text or query):
        return "pubmed"
    if query:
        return "web"
    detected = _detect_source(text)
    if detected:
        return detected
    raise RuntimeError(
        "Real data source required. Use --source (worldbank, pubmed, url, web) "
        "or include hints like GDP, PubMed papers, or a URL."
    )


def fetch_worldbank_rows(
    *,
    indicator: str,
    country: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    text: str = "",
    max_rows: int = MAX_REAL_ROWS,
) -> list[dict[str, Any]]:
    try:
        from arka.charts.data import INDICATORS, fetch_worldbank
    except ImportError as exc:
        raise RuntimeError("World Bank support requires arka.charts.data") from exc

    indicator_key = indicator.lower().strip()
    if indicator_key not in INDICATORS:
        raise RuntimeError(
            f"Unknown indicator '{indicator}'. "
            f"Choose: {', '.join(sorted(INDICATORS))}"
        )
    ind_code, ind_label, _ylabel = INDICATORS[indicator_key]

    codes: list[str]
    if country:
        codes = [country.upper()]
    else:
        from arka.charts.data import extract_countries

        codes = extract_countries(text) or ["IN"]

    y0, y1 = _extract_year_bounds(text)
    if year_from is not None:
        y0 = year_from
    if year_to is not None:
        y1 = year_to
    if y0 is None:
        y0 = 2000
    if y1 is None:
        y1 = date.today().year - 1

    data = fetch_worldbank(codes, ind_code, y0, y1)
    rows: list[dict[str, Any]] = []
    for country_name, years in data.items():
        code = country.upper() if country and len(codes) == 1 else ""
        for year, value in sorted(years.items()):
            row: dict[str, Any] = {
                "country": country_name,
                "indicator": indicator_key,
                "indicator_label": ind_label,
                "year": year,
                "value": value,
            }
            if code:
                row["country_code"] = code
            rows.append(row)
            if len(rows) >= max_rows:
                return rows
    if not rows:
        raise RuntimeError(
            f"No World Bank values for {indicator_key} ({codes}) in {y0}–{y1}."
        )
    return rows


def _load_search_pubmed() -> Callable[..., list[dict[str, str]]]:
    """Import search_pubmed from life_sciences lib (skills/ is not a Python package)."""
    import importlib.util

    lib_path = Path(__file__).resolve().parents[1] / "skills" / "life_sciences" / "lib.py"
    if not lib_path.is_file():
        raise RuntimeError("PubMed support requires life_sciences lib")
    spec = importlib.util.spec_from_file_location("_life_sciences_lib", lib_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("PubMed support requires life_sciences lib")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "search_pubmed", None)
    if not callable(fn):
        raise RuntimeError("PubMed support requires search_pubmed in life_sciences lib")
    return fn


def fetch_pubmed_rows(query: str, *, max_rows: int = MAX_REAL_ROWS) -> list[dict[str, Any]]:
    if not query.strip():
        raise RuntimeError("PubMed search requires a query (--query or NL phrase).")
    search_pubmed = _load_search_pubmed()
    try:
        rows = search_pubmed(query.strip(), retmax=max_rows)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"PubMed search failed: {exc}") from exc
    if not rows:
        raise RuntimeError(f"No PubMed results for: {query.strip()}")
    return rows[:max_rows]


def _normalize_json_to_rows(data: Any, max_rows: int) -> list[dict[str, Any]]:
    if isinstance(data, list):
        dict_rows = [r for r in data if isinstance(r, dict)]
        if dict_rows:
            return dict_rows[:max_rows]
        raise RuntimeError("JSON array contains no objects.")
    if isinstance(data, dict):
        for key in ("results", "data", "items", "records", "rows", "entries"):
            nested = data.get(key)
            if isinstance(nested, list):
                dict_rows = [r for r in nested if isinstance(r, dict)]
                if dict_rows:
                    return dict_rows[:max_rows]
        return [data][:max_rows]
    raise RuntimeError("JSON response is not tabular.")


def fetch_url_rows(url: str, *, max_rows: int = MAX_REAL_ROWS) -> list[dict[str, Any]]:
    if not url.strip():
        raise RuntimeError("URL source requires --url.")
    req = urllib.request.Request(url.strip(), headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            body = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"URL fetch failed: {exc}") from exc

    if "json" in content_type or body[:1] in (b"{", b"["):
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"URL did not return valid JSON: {exc}") from exc
        rows = _normalize_json_to_rows(data, max_rows)
        if not rows:
            raise RuntimeError("URL JSON returned no rows.")
        return rows

    text = body.decode("utf-8", errors="replace")
    if not text.strip():
        raise RuntimeError("URL returned empty body.")
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(r) for r in reader]
    except csv.Error as exc:
        raise RuntimeError(f"URL content is not JSON or CSV: {exc}") from exc
    if not rows:
        raise RuntimeError("URL CSV returned no rows.")
    return rows[:max_rows]


def fetch_web_rows(query: str, *, max_rows: int = MAX_REAL_ROWS) -> list[dict[str, Any]]:
    if not query.strip():
        raise RuntimeError("Web search requires a query (--query).")
    try:
        from arka.agent.chat import duckduckgo_search
    except ImportError as exc:
        raise RuntimeError("Web search requires arka.agent.chat") from exc
    results = duckduckgo_search(query.strip(), max_results=max_rows)
    if not results:
        raise RuntimeError(f"No web search results for: {query.strip()}")
    rows: list[dict[str, Any]] = []
    for item in results[:max_rows]:
        rows.append(
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
        )
    return rows


def fetch_real_rows(
    source: str,
    *,
    count: int,
    url: str | None = None,
    indicator: str | None = None,
    country: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    query: str | None = None,
    text: str = "",
) -> list[dict[str, Any]]:
    source = source.lower().strip()
    max_rows = min(max(1, count), MAX_REAL_ROWS)
    if source == "worldbank":
        if not indicator:
            indicator = _extract_indicator(text) or "gdp"
        return fetch_worldbank_rows(
            indicator=indicator,
            country=country or _extract_country_code(text),
            year_from=year_from,
            year_to=year_to,
            text=text,
            max_rows=max_rows,
        )
    if source == "pubmed":
        q = query or _extract_pubmed_query(text)
        return fetch_pubmed_rows(q or "", max_rows=max_rows)
    if source == "url":
        return fetch_url_rows(url or _extract_url(text) or "", max_rows=max_rows)
    if source == "web":
        return fetch_web_rows(query or text, max_rows=max_rows)
    raise RuntimeError(f"Unsupported real source '{source}'. Choose: {', '.join(sorted(REAL_SOURCES))}")


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

    source = (getattr(args, "source", None) or "").lower().strip()
    if getattr(args, "real", False) and not source:
        try:
            source = _infer_real_source(
                url=getattr(args, "url", None),
                indicator=getattr(args, "indicator", None),
                country=getattr(args, "country", None),
                query=getattr(args, "query", None),
                text=getattr(args, "nl_text", "") or "",
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if source and source in REAL_SOURCES:
        count = min(count, MAX_REAL_ROWS)
        try:
            rows = fetch_real_rows(
                source,
                count=count,
                url=getattr(args, "url", None),
                indicator=getattr(args, "indicator", None),
                country=getattr(args, "country", None),
                year_from=getattr(args, "year_from", None),
                year_to=getattr(args, "year_to", None),
                query=getattr(args, "query", None),
                text=getattr(args, "nl_text", "") or "",
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        count = len(rows)
    else:
        rows = generate_rows(fields, count, seed=args.seed)
        if args.llm:
            llm_rows = _llm_generate_rows(fields, count)
            if llm_rows:
                rows = llm_rows

    table = re.sub(r"[^a-zA-Z0-9_]", "_", (preset or source or "sample_data").lower())
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


def _add_real_source_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--source",
        choices=sorted(REAL_SOURCES),
        default=None,
        help="Real-world data source (default: synthetic fake data)",
    )
    p.add_argument(
        "--real",
        action="store_true",
        help="Fetch real data; infers source from --indicator, --url, --query, etc.",
    )
    p.add_argument("--url", default=None, help="URL for --source url (JSON or CSV)")
    p.add_argument(
        "--indicator",
        default=None,
        help="World Bank indicator (gdp, population, life_expectancy, …)",
    )
    p.add_argument("--country", default=None, help="ISO country code for World Bank (e.g. IN, US)")
    p.add_argument("--year-from", type=int, default=None, dest="year_from")
    p.add_argument("--year-to", type=int, default=None, dest="year_to")
    p.add_argument("--query", default=None, help="Search query for pubmed or web sources")


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
    _add_real_source_args(p_gen)
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
    _add_real_source_args(p)
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
    nl_text = ""
    if argv and not any(a.startswith("-") for a in argv[:1]) and wants_generate_data(" ".join(argv)):
        nl_text = " ".join(argv)
        nl_args = nl_to_argv(nl_text)
        if nl_args:
            argv = nl_args

    args = _parse_generate_argv(argv)
    if args.rows is not None:
        args.count = args.rows
    args.nl_text = nl_text
    return cmd_generate(args)


if __name__ == "__main__":
    raise SystemExit(main())
