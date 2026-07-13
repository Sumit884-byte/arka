"""Reliable external data for charts (World Bank indicators) + chart-type suitability."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (compatible; Arka-Chart/1.0; +https://github.com/arka-agent)"
SEC_USER_AGENT = "Arka-Chart arka@example.com"
WORLDBANK_TIMEOUT = float(os.environ.get("ARKA_WORLDBANK_TIMEOUT", "45") or "45")
WORLDBANK_RETRIES = max(1, int(os.environ.get("ARKA_WORLDBANK_RETRIES", "3") or "3"))
WORLDBANK_CACHE_TTL = max(0, int(os.environ.get("ARKA_WORLDBANK_CACHE_TTL", "86400") or "86400"))

# ISO-3166 alpha-2 used by World Bank country API.
COUNTRY_CODES: dict[str, str] = {
    "india": "IN",
    "china": "CN",
    "united states": "US",
    "usa": "US",
    "us": "US",
    "america": "US",
    "indonesia": "ID",
    "pakistan": "PK",
    "nigeria": "NG",
    "brazil": "BR",
    "bangladesh": "BD",
    "russia": "RU",
    "mexico": "MX",
    "japan": "JP",
    "ethiopia": "ET",
    "philippines": "PH",
    "egypt": "EG",
    "vietnam": "VN",
    "dr congo": "CD",
    "congo": "CD",
    "turkey": "TR",
    "iran": "IR",
    "germany": "DE",
    "thailand": "TH",
    "united kingdom": "GB",
    "uk": "GB",
    "britain": "GB",
    "france": "FR",
    "italy": "IT",
    "south africa": "ZA",
    "south korea": "KR",
    "korea": "KR",
    "spain": "ES",
    "argentina": "AR",
    "canada": "CA",
    "australia": "AU",
    "saudi arabia": "SA",
    "malaysia": "MY",
    "singapore": "SG",
    "uae": "AE",
    "united arab emirates": "AE",
    "nepal": "NP",
    "sri lanka": "LK",
    "world": "WLD",
}

# Fallback when locale / timezone / IP cannot resolve a country.
DEFAULT_LOCAL_COUNTRY = "IN"

# Common IANA timezones → ISO2 (used when no country is named in the request).
TIMEZONE_COUNTRY: dict[str, str] = {
    "asia/kolkata": "IN",
    "asia/calcutta": "IN",
    "asia/shanghai": "CN",
    "asia/hong_kong": "CN",
    "america/new_york": "US",
    "america/chicago": "US",
    "america/denver": "US",
    "america/los_angeles": "US",
    "america/phoenix": "US",
    "america/toronto": "CA",
    "america/vancouver": "CA",
    "america/sao_paulo": "BR",
    "america/mexico_city": "MX",
    "europe/london": "GB",
    "europe/paris": "FR",
    "europe/berlin": "DE",
    "europe/rome": "IT",
    "europe/madrid": "ES",
    "europe/moscow": "RU",
    "asia/tokyo": "JP",
    "asia/seoul": "KR",
    "asia/singapore": "SG",
    "asia/dubai": "AE",
    "asia/bangkok": "TH",
    "asia/jakarta": "ID",
    "asia/karachi": "PK",
    "asia/dhaka": "BD",
    "asia/manila": "PH",
    "asia/ho_chi_minh": "VN",
    "asia/saigon": "VN",
    "asia/kathmandu": "NP",
    "asia/colombo": "LK",
    "australia/sydney": "AU",
    "australia/melbourne": "AU",
    "africa/lagos": "NG",
    "africa/cairo": "EG",
    "africa/johannesburg": "ZA",
}

INDICATORS: dict[str, tuple[str, str, str]] = {
    # topic_key → (worldbank_code, short_title, ylabel)
    "population": ("SP.POP.TOTL", "Population", "People"),
    "gdp": ("NY.GDP.MKTP.CD", "GDP (current US$)", "US$"),
    "gdp_per_capita": ("NY.GDP.PCAP.CD", "GDP per capita (current US$)", "US$"),
    "life_expectancy": ("SP.DYN.LE00.IN", "Life expectancy at birth", "Years"),
    "co2": ("EN.ATM.CO2E.KT", "CO₂ emissions", "kt"),
    "unemployment": ("SL.UEM.TOTL.ZS", "Unemployment rate", "% of labor force"),
    "internet": ("IT.NET.USER.ZS", "Internet users", "% of population"),
}

TOPIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("gdp_per_capita", re.compile(r"(?i)\bgdp\s+per\s+capita\b|\bper[- ]capita\s+gdp\b")),
    ("gdp", re.compile(r"(?i)\bgdp\b|\bgross\s+domestic\s+product\b|\beconomy\s+size\b")),
    ("life_expectancy", re.compile(r"(?i)\blife\s+expectanc")),
    ("co2", re.compile(r"(?i)\bco2\b|\bcarbon\s+dioxide\b|\bemissions?\b")),
    ("unemployment", re.compile(r"(?i)\bunemployment\b")),
    ("internet", re.compile(r"(?i)\binternet\s+users?\b|\bonline\s+penetration\b")),
    ("population", re.compile(r"(?i)\bpopulation\b|\bpopulace\b|\bdemograph")),
)

# Market-share / distribution topics (web-sourced percentages → pie/bar).
# Each entry: (topic_key, title, subject_pattern). Matched when subject + chart/share cue.
SHARE_SUBJECTS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "mobile_os_share",
        "Mobile OS market share",
        re.compile(r"(?i)\b(?:mobile\s+os|smartphone\s+os|android\b.*\bios\b|\bios\b.*\bandroid\b)\b"),
    ),
    (
        "os_share",
        "Desktop OS market share",
        re.compile(
            r"(?i)\b(?:operating\s+systems?|desktop\s+os|various\s+os|"
            r"os(?:es)?|windows|macos|mac\s*os|chrome\s*os|chromeos)\b"
        ),
    ),
    (
        "browser_share",
        "Browser market share",
        re.compile(r"(?i)\b(?:web\s+)?browsers?\b"),
    ),
    (
        "search_share",
        "Search engine market share",
        re.compile(r"(?i)\b(?:search\s+engines?)\b"),
    ),
    (
        "device_share",
        "Device traffic share",
        re.compile(
            r"(?i)\b(?:device(?:s| types?)?|platform(?:s)?(?:\s+traffic)?|"
            r"user\s+base|(?:mobile|desktop|tablet)\s+(?:traffic|users?|share)|"
            r"desktop\s*/\s*mobile|mobile\s*/\s*desktop)\b"
        ),
    ),
)

_SHARE_CUE = re.compile(
    r"(?i)\b(?:pie|donut|doughnut|pareto|chart|graph|plot|visuali[sz]e|bar|distribution|"
    r"breakdown|composition|market\s+share|share|percent(?:age)?s?|device\s+traffic)\b"
)

_CHART_CUE = re.compile(
    r"(?i)\b(?:chart|graph|plot|visuali[sz]e|diagram|draw|make\s+(?:a|an|the|me)\s+"
    r"(?:\w+\s+){0,2}?(?:chart|graph|plot))\b"
)

# Last-resort curated slices when the web parse finds nothing (clearly labeled).
SHARE_FALLBACKS: dict[str, list[tuple[str, float]]] = {
    "os_share": [
        ("Windows", 72.0),
        ("macOS", 16.0),
        ("Linux", 4.0),
        ("ChromeOS", 3.0),
        ("Other", 5.0),
    ],
    "browser_share": [
        ("Chrome", 65.0),
        ("Safari", 18.0),
        ("Edge", 5.0),
        ("Firefox", 3.0),
        ("Other", 9.0),
    ],
    "mobile_os_share": [
        ("Android", 71.0),
        ("iOS", 28.0),
        ("Other", 1.0),
    ],
    "search_share": [
        ("Google", 90.0),
        ("Bing", 4.0),
        ("Yahoo", 1.5),
        ("Yandex", 1.5),
        ("Other", 3.0),
    ],
    "device_share": [
        ("Mobile", 58.0),
        ("Desktop", 39.0),
        ("Tablet", 3.0),
    ],
}

CHART_TYPE_ALIASES: dict[str, str] = {
    "bar": "bar",
    "bars": "bar",
    "column": "bar",
    "columns": "bar",
    "grouped": "grouped_bar",
    "group": "grouped_bar",
    "grouped_bar": "grouped_bar",
    "grouped-bar": "grouped_bar",
    "bar_group": "grouped_bar",
    "group_bar": "grouped_bar",
    "line": "line",
    "lines": "line",
    "trend": "line",
    "trends": "line",
    "pie": "pie",
    "donut": "pie",
    "doughnut": "pie",
    "scatter": "scatter",
    "histogram": "histogram",
    "hist": "histogram",
    "pareto": "pareto",
}


@dataclass
class ChartSeries:
    """One named series aligned to categories (e.g. year → values per country)."""

    name: str
    values: list[float]


@dataclass
class ChartDataset:
    topic: str
    indicator: str
    title: str
    ylabel: str
    categories: list[str]
    series: list[ChartSeries]
    source: str
    notes: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)

    @property
    def is_time_series(self) -> bool:
        return len(self.years) >= 2

    @property
    def is_multi_series(self) -> bool:
        return len(self.series) >= 2


@dataclass
class ChartAdvice:
    requested: str
    recommended: str
    warning: str = ""
    forced: bool = False

    @property
    def chart_type(self) -> str:
        return self.requested if self.forced else self.recommended


def detect_topic(text: str) -> str | None:
    for key, pat in TOPIC_PATTERNS:
        if pat.search(text or ""):
            return key
    return None


def detect_share_topic(text: str) -> tuple[str, str] | None:
    """Return (topic_key, title) for OS/browser/search market-share chart requests."""
    t = text or ""
    if not _SHARE_CUE.search(t):
        return None
    for key, title, pat in SHARE_SUBJECTS:
        if pat.search(t):
            return key, title
    return None


def extract_year_range(text: str) -> tuple[int | None, int | None]:
    """Return (start, end) years from phrases like 'from 2023 to 2026' or '2020-2024'."""
    t = text or ""
    m = re.search(
        r"(?i)\b(?:from|between)\s+(19|20)(\d{2})\s+(?:to|and|-|–|—)\s+(19|20)(\d{2})\b",
        t,
    )
    if m:
        a = int(m.group(1) + m.group(2))
        b = int(m.group(3) + m.group(4))
        return (min(a, b), max(a, b))
    m = re.search(r"\b(19|20)(\d{2})\s*(?:to|-|–|—|vs\.?|versus)\s*(19|20)(\d{2})\b", t, re.I)
    if m:
        a = int(m.group(1) + m.group(2))
        b = int(m.group(3) + m.group(4))
        return (min(a, b), max(a, b))
    years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", t)]
    years = [y for y in years if 1960 <= y <= 2100]
    if len(years) >= 2:
        return (min(years), max(years))
    if len(years) == 1:
        return (years[0], years[0])
    return (None, None)


def is_year_range_pseudo_data(text: str) -> bool:
    """True when NL only has a from/to year span (not real label:value data)."""
    start, end = extract_year_range(text)
    if start is None or end is None or start == end:
        return False
    # Explicit label:value pairs with non-year labels → real data.
    for m in re.finditer(r"([A-Za-z][A-Za-z0-9.&\s-]{0,24}?)\s*[:=]\s*(\d+(?:\.\d+)?)", text):
        label = m.group(1).strip().lower()
        if label not in {"from", "to", "between", "and", "vs", "versus"}:
            try:
                val = float(m.group(2))
            except ValueError:
                continue
            if not (1900 <= val <= 2100 and val == int(val)):
                return False
    return True


def extract_countries(text: str) -> list[str]:
    """Return World Bank country codes mentioned in text (order preserved)."""
    low = (text or "").lower()
    found: list[str] = []
    seen: set[str] = set()
    # Longer names first so "united states" wins over "us".
    for name in sorted(COUNTRY_CODES.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", low):
            code = COUNTRY_CODES[name]
            if code not in seen:
                seen.add(code)
                found.append(code)
    return found


def _country_from_text_blob(text: str) -> str | None:
    """Match a known country name inside free-form location text."""
    codes = extract_countries(text)
    return codes[0] if codes else None


def _country_from_locale() -> str | None:
    """Best-effort ISO2 from LANG / LC_ALL (e.g. en_IN.UTF-8 → IN)."""
    for key in ("LC_ALL", "LC_CTYPE", "LANG"):
        raw = (os.environ.get(key) or "").strip()
        if not raw or raw.upper() in {"C", "POSIX"}:
            continue
        # en_IN.UTF-8 / en_US / hi_IN
        m = re.match(r"^[a-zA-Z]{2,3}[_-]([A-Za-z]{2})\b", raw)
        if m:
            return m.group(1).upper()
    return None


def _country_from_timezone() -> str | None:
    tz = (os.environ.get("TZ") or "").strip()
    if not tz:
        try:
            # zoneinfo / system local zone name when available
            from datetime import datetime

            name = getattr(datetime.now().astimezone().tzinfo, "key", None)
            if isinstance(name, str) and name:
                tz = name
        except Exception:
            tz = ""
    if not tz:
        return None
    return TIMEZONE_COUNTRY.get(tz.lower().replace(" ", "_"))


def _country_from_chat_context() -> str | None:
    """Reuse Arka chat location cache when present (no network)."""
    candidates: list[Path] = []
    env_cache = (os.environ.get("CACHE_DIR") or "").strip()
    if env_cache:
        candidates.append(Path(env_cache).expanduser() / "chat_context.json")
    try:
        import arka.paths as _ap

        candidates.append(_ap.cache_dir() / "chat_context.json")
    except Exception:
        pass
    candidates.append(Path.home() / ".cache" / "fish-agent" / "chat_context.json")

    for path in candidates:
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("location_string", "city", "country"):
            blob = data.get(key)
            if isinstance(blob, str) and blob.strip():
                code = _country_from_text_blob(blob)
                if code:
                    return code
        # ipapi-style fields sometimes stored under coords metadata
        country_code = data.get("country_code") or data.get("countryCode")
        if isinstance(country_code, str) and len(country_code) == 2:
            return country_code.upper()
    return None


def detect_local_country() -> str:
    """
    Resolve the user's country for default indicator charts.

    Order: ARKA_CHART_COUNTRY env → chat location cache → locale → timezone → India.
    Avoids a network round-trip so chart fetch stays fast offline.
    """
    override = (os.environ.get("ARKA_CHART_COUNTRY") or "").strip().upper()
    if len(override) == 2 and override.isalpha():
        return override

    for resolver in (
        _country_from_chat_context,
        _country_from_locale,
        _country_from_timezone,
    ):
        try:
            code = resolver()
        except Exception:
            code = None
        if code and len(code) == 2:
            return code.upper()
    return DEFAULT_LOCAL_COUNTRY


def has_chart_cue(text: str) -> bool:
    """True when NL clearly asks for a visual chart (not prose/web_answer)."""
    return bool(_CHART_CUE.search(text or ""))


def detect_chart_intent(text: str) -> str | None:
    """
    Map decision-matrix phrasing → chart kind (comparison→bar, temporal→line, …).

    Used when no explicit kind prefix is present but the user still wants a chart.
    """
    t = text or ""
    if not t.strip():
        return None

    if re.search(r"(?i)\b(grouped|group)\s*[- ]?\s*bars?\b|\bbars?\s+group\b|\bbar\s+group\b", t):
        return "grouped_bar"
    if re.search(r"(?i)\b(pareto|80/20|80-20|eighty.twenty|defect\s+causes?|top\s+contributors?)\b", t):
        return "pareto"
    if re.search(r"(?i)\b(histogram|freq(?:uency)?(?:\s+dist(?:ribution)?)?|bins?)\b", t):
        return "histogram"
    if re.search(r"(?i)\bdistribution\b", t):
        return "histogram"
    if re.search(r"(?i)\b(scatter|correlation|relationship)\b", t):
        return "scatter"
    if re.search(
        r"(?i)\b(pie|donut|doughnut|breakdown|composition|part\s+of\s+(?:the\s+)?whole|"
        r"percentage|percentages|share|market\s+share)\b",
        t,
    ):
        return "pie"
    if re.search(r"(?i)\b(over\s+time|timeline|monthly|yearly|trend(?:s)?)\b", t):
        return "line"
    if re.search(r"(?i)\b(compare|comparison|versus\s+categor|magnitudes?|columns?)\b", t):
        return "bar"
    return None


def detect_requested_chart_type(text: str) -> str | None:
    low = (text or "").lower()
    if re.search(r"(?i)\b(grouped|group)\s*[- ]?\s*bars?\b|\bbars?\s+group\b|\bbar\s+group\b", low):
        return "grouped_bar"
    if re.search(r"(?i)\b(pie|donut|doughnut)\b", low):
        return "pie"
    if re.search(r"(?i)\b(scatter|correlation|relationship)\b", low):
        return "scatter"
    if re.search(r"(?i)\b(histogram|freq(?:uency)?(?:\s+dist(?:ribution)?)?|bins?)\b", low):
        return "histogram"
    if re.search(r"(?i)\b(pareto|80/20|80-20|defect\s+causes?|top\s+contributors?)\b", low):
        return "pareto"
    if re.search(r"(?i)\b(line|trend|over\s+time|timeline|monthly|yearly)\s*(?:chart|graph|plot)?\b", low):
        return "line"
    if re.search(r"(?i)\b(bar|column)s?\b", low):
        return "bar"
    if re.search(
        r"(?i)\b(breakdown|composition|part\s+of\s+(?:the\s+)?whole|percentage|share|market\s+share)\b",
        low,
    ):
        return "pie"
    if re.search(r"(?i)\b(compare|comparison|magnitudes?)\b", low):
        return "bar"
    return detect_chart_intent(text)


def recommend_chart_type(dataset: ChartDataset, requested: str | None) -> ChartAdvice:
    """Pick a suitable chart type; warn when the user's pick is a poor fit."""
    req = (requested or "").strip().lower() or "auto"
    if req in CHART_TYPE_ALIASES:
        req = CHART_TYPE_ALIASES[req]

    # Single-country year-over-year (categories are years) → line shows change clearly.
    cats_look_like_years = bool(dataset.years) and all(
        re.fullmatch(r"(19|20)\d{2}", str(c).strip()) for c in dataset.categories
    )
    share_snapshot = dataset.topic.endswith("_share") and not dataset.is_time_series
    if cats_look_like_years and len(dataset.series) == 1:
        best = "line"
    elif share_snapshot and len(dataset.categories) >= 2:
        best = "pie"
    elif dataset.is_multi_series and dataset.is_time_series:
        best = "grouped_bar"
    elif dataset.is_time_series and len(dataset.series) == 1:
        best = "line"
    elif len(dataset.categories) >= 2 and len(dataset.series) == 1:
        best = "bar"
    else:
        best = "bar"

    if req in {"", "auto"}:
        return ChartAdvice(requested="auto", recommended=best)

    warning = ""
    recommended = req

    if req == "pie":
        if dataset.is_time_series or dataset.is_multi_series:
            warning = (
                f"Pie charts are a poor fit for time-series or multi-series comparisons "
                f"({dataset.title}). Prefer a {best} chart."
            )
            recommended = best
        elif len(dataset.categories) > 8:
            warning = "Pie charts get hard to read with many slices; a bar chart is clearer."
            recommended = "bar"
    elif req == "scatter":
        warning = (
            f"Scatter plots need paired x/y observations, not indicator tables. "
            f"Using a {best} chart for {dataset.title}."
        )
        recommended = best
    elif req == "histogram":
        warning = (
            f"Histograms show value distributions, not country/year indicators. "
            f"Using a {best} chart for {dataset.title}."
        )
        recommended = best
    elif req == "pareto":
        if dataset.is_time_series:
            warning = f"Pareto is for ranked defect/cause shares, not trends. Prefer a {best} chart."
            recommended = best
    elif req == "bar" and dataset.is_multi_series and dataset.is_time_series:
        warning = (
            "A simple bar chart cannot show multiple years side-by-side cleanly. "
            "Using a grouped bar chart instead."
        )
        recommended = "grouped_bar"
    elif req == "line" and not dataset.is_time_series and len(dataset.categories) <= 2:
        warning = "A line chart needs a meaningful time axis; a bar chart fits this snapshot better."
        recommended = "bar"
    elif req == "grouped_bar" and not dataset.is_multi_series:
        # Single series: grouped_bar degenerates — use bar or line.
        recommended = best
        if best != "grouped_bar":
            warning = (
                f"Grouped bars need multiple series (e.g. several years). "
                f"Using a {best} chart instead."
            )

    return ChartAdvice(requested=req, recommended=recommended, warning=warning)


def _has_inline_chart_pairs(text: str) -> bool:
    """True when NL already includes label:value (or label value) data pairs."""
    if is_year_range_pseudo_data(text):
        return False
    labels = 0
    for m in re.finditer(
        r"([A-Za-z][A-Za-z0-9.&\s-]{0,24}?)\s*[:=]\s*(\d+(?:\.\d+)?)",
        text or "",
    ):
        label = m.group(1).strip().lower()
        if label in {"from", "to", "between", "and", "vs", "versus"}:
            continue
        try:
            val = float(m.group(2))
        except ValueError:
            continue
        if 1900 <= val <= 2100 and val == int(val) and len(m.group(2)) == 4:
            continue
        labels += 1
    return labels >= 2


def needs_external_data(text: str) -> bool:
    """True when NL asks for a chart of a known indicator/share topic without inline numbers."""
    if re.search(r"--data\b", text or "", re.I):
        return False
    if _has_inline_chart_pairs(text):
        return False
    if detect_share_topic(text):
        return True
    if not detect_topic(text):
        return False
    return True


def _worldbank_cache_dir() -> Path:
    env = (os.environ.get("ARKA_CHART_CACHE_DIR") or "").strip()
    if env:
        path = Path(env).expanduser()
    else:
        try:
            import arka.paths as _ap

            path = _ap.cache_dir() / "worldbank"
        except Exception:
            path = Path.home() / ".cache" / "fish-agent" / "worldbank"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return _worldbank_cache_dir() / f"{digest}.json"


def _cache_load(url: str) -> object | None:
    if WORLDBANK_CACHE_TTL <= 0:
        return None
    path = _cache_key(url)
    try:
        if not path.is_file():
            return None
        age = time.time() - path.stat().st_mtime
        if age > WORLDBANK_CACHE_TTL:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _cache_store(url: str, payload: object) -> None:
    if WORLDBANK_CACHE_TTL <= 0:
        return
    try:
        path = _cache_key(url)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def _http_json(url: str, *, timeout: float | None = None) -> object:
    """GET JSON with retries; prefer cache on repeated timeouts."""
    timeout = WORLDBANK_TIMEOUT if timeout is None else timeout
    cached = _cache_load(url)
    if cached is not None:
        return cached

    last_exc: BaseException | None = None
    for attempt in range(WORLDBANK_RETRIES):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            _cache_store(url, payload)
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
            last_exc = exc
            # Brief backoff; World Bank is often slow from some networks.
            if attempt + 1 < WORLDBANK_RETRIES:
                time.sleep(1.2 * (attempt + 1))
    # Stale cache is better than failing the chart entirely.
    stale = _cache_key(url)
    try:
        if stale.is_file():
            return json.loads(stale.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        pass
    raise RuntimeError(f"World Bank request failed: {last_exc}") from last_exc


def fetch_worldbank(
    codes: list[str],
    indicator: str,
    year_from: int,
    year_to: int,
) -> dict[str, dict[int, float]]:
    """
    Fetch World Bank indicator values.

    Returns {country_display_name: {year: value}} for available years in range.
    """
    if year_from > year_to:
        year_from, year_to = year_to, year_from
    # World Bank annual series rarely includes the current/future calendar year.
    from datetime import datetime

    published_cap = datetime.now().year - 1
    if year_to > published_cap:
        year_to = published_cap
    if year_from > year_to:
        year_from = year_to

    country_path = ";".join(urllib.parse.quote(c, safe="") for c in codes)
    ind = urllib.parse.quote(indicator, safe="")
    url = (
        f"https://api.worldbank.org/v2/country/{country_path}/indicator/{ind}"
        f"?format=json&per_page=20000&date={year_from}:{year_to}"
    )
    try:
        payload = _http_json(url)
    except RuntimeError:
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"World Bank request failed: {exc}") from exc

    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise RuntimeError("World Bank returned no data rows (check country codes / years).")

    # Prefer stable order matching requested ISO2 codes.
    by_code: dict[str, tuple[str, dict[int, float]]] = {}
    for row in payload[1]:
        if not isinstance(row, dict):
            continue
        val = row.get("value")
        date_raw = row.get("date")
        country_meta = row.get("country") or {}
        code = str(country_meta.get("id") or "").upper()
        name = str(country_meta.get("value") or row.get("countryiso3code") or code or "?")
        if not code or val is None or date_raw is None:
            continue
        try:
            year = int(str(date_raw)[:4])
            num = float(val)
        except (TypeError, ValueError):
            continue
        if year < year_from or year > year_to:
            continue
        if code not in by_code:
            by_code[code] = (name, {})
        by_code[code][1][year] = num

    out: dict[str, dict[int, float]] = {}
    for code in codes:
        entry = by_code.get(code.upper())
        if not entry:
            continue
        name, years = entry
        # Disambiguate duplicate display names.
        label = name
        if label in out:
            label = f"{name} ({code})"
        out[label] = years

    if not out:
        raise RuntimeError(
            f"No World Bank values for {indicator} in {year_from}–{year_to}. "
            "Try an earlier end year (data often lags 1–2 years)."
        )
    return out


def build_dataset_from_worldbank(
    text: str,
    *,
    topic: str | None = None,
    countries: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> ChartDataset:
    topic_key = topic or detect_topic(text)
    if not topic_key or topic_key not in INDICATORS:
        raise RuntimeError("Unsupported chart topic (try population, GDP, life expectancy, …).")

    ind_code, short_title, ylabel = INDICATORS[topic_key]
    named = countries if countries is not None else extract_countries(text)
    used_local_default = False
    if named:
        codes = list(named)
    else:
        codes = [detect_local_country()]
        used_local_default = True

    y0, y1 = extract_year_range(text)
    if year_from is not None:
        y0 = year_from
    if year_to is not None:
        y1 = year_to
    if y0 is None and y1 is None:
        # Default: last ~5 published years ending last calendar year.
        from datetime import datetime

        y1 = datetime.now().year - 1
        y0 = y1 - 4
    elif y0 is None:
        y0 = y1
    elif y1 is None:
        y1 = y0
    assert y0 is not None and y1 is not None

    from datetime import datetime

    requested_y1 = y1
    published_cap = datetime.now().year - 1
    fetch_y1 = min(y1, published_cap)
    fetch_y0 = y0 if y0 <= fetch_y1 else fetch_y1

    raw = fetch_worldbank(codes, ind_code, fetch_y0, fetch_y1)
    all_years = sorted({y for series in raw.values() for y in series})
    if not all_years:
        raise RuntimeError("World Bank returned empty year set.")

    notes: list[str] = []
    if used_local_default:
        country_label = next(iter(raw.keys()), codes[0])
        notes.append(
            f"No country named — showing {country_label} "
            f"(from your location; name countries to compare)."
        )
    if requested_y1 > published_cap:
        notes.append(
            f"World Bank has no data past {published_cap}; "
            f"showing through latest published year (asked for {requested_y1})."
        )
    missing_end = [y for y in range(fetch_y0, fetch_y1 + 1) if y not in all_years]
    if missing_end:
        notes.append(
            f"No published values for: {', '.join(str(y) for y in missing_end)} "
            "(World Bank often lags)."
        )

    # One country over years → categories = years (cleaner bar/line).
    # Multiple countries → categories = countries, series = years (grouped).
    if len(raw) == 1:
        country_name = next(iter(raw.keys()))
        year_vals = raw[country_name]
        categories = [str(y) for y in all_years]
        values = [float(year_vals.get(y, 0.0)) for y in all_years]
        series_list = [ChartSeries(name=country_name, values=values)]
        title = f"{short_title} — {country_name} ({all_years[0]}–{all_years[-1]})"
        if len(all_years) == 1:
            title = f"{short_title} — {country_name} ({all_years[0]})"
    else:
        categories = list(raw.keys())
        series_list = []
        for year in all_years:
            vals = [float(raw[cat].get(year, float("nan"))) for cat in categories]
            if all(v != v for v in vals):  # all NaN
                continue
            clean = [0.0 if v != v else v for v in vals]
            series_list.append(ChartSeries(name=str(year), values=clean))
        title = f"{short_title} ({all_years[0]}–{all_years[-1]})"
        if len(all_years) == 1:
            title = f"{short_title} ({all_years[0]})"

    if not series_list:
        raise RuntimeError("Could not build chart series from World Bank data.")

    # Human-scale axis labels for large absolute counts.
    plot_ylabel = ylabel
    if topic_key == "population":
        plot_ylabel = "Population"
    elif topic_key == "gdp":
        plot_ylabel = "GDP (US$)"

    return ChartDataset(
        topic=topic_key,
        indicator=ind_code,
        title=title,
        ylabel=plot_ylabel,
        categories=categories,
        series=series_list,
        source="World Bank Open Data (api.worldbank.org)",
        notes=notes,
        years=all_years,
    )


_SHARE_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "as",
        "of",
        "to",
        "in",
        "on",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "by",
        "at",
        "or",
        "global",
        "worldwide",
        "desktop",
        "laptop",
        "market",
        "share",
        "shares",
        "percent",
        "percentage",
        "distribution",
        "breakdown",
        "various",
        "operating",
        "system",
        "systems",
        "os",
        "oses",
        "browser",
        "browsers",
        "mobile",
        "search",
        "engine",
        "engines",
        "june",
        "july",
        "january",
        "february",
        "march",
        "april",
        "may",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
)

_SHARE_ALIASES: dict[str, str] = {
    "microsoft windows": "Windows",
    "windows": "Windows",
    "win": "Windows",
    "mac os": "macOS",
    "macos": "macOS",
    "mac": "macOS",
    "os x": "macOS",
    "osx": "macOS",
    "apple macos": "macOS",
    "apple": "macOS",
    "linux": "Linux",
    "desktop linux": "Linux",
    "gnu/linux": "Linux",
    "chrome os": "ChromeOS",
    "chromeos": "ChromeOS",
    "google chrome os": "ChromeOS",
    "google chromeos": "ChromeOS",
    "chrome": "Chrome",
    "google chrome": "Chrome",
    "safari": "Safari",
    "firefox": "Firefox",
    "mozilla firefox": "Firefox",
    "edge": "Edge",
    "microsoft edge": "Edge",
    "opera": "Opera",
    "samsung internet": "Samsung Internet",
    "android": "Android",
    "ios": "iOS",
    "iphone os": "iOS",
    "google": "Google",
    "bing": "Bing",
    "yahoo": "Yahoo",
    "yandex": "Yandex",
    "duckduckgo": "DuckDuckGo",
    "baidu": "Baidu",
    "mobile": "Mobile",
    "desktop": "Desktop",
    "tablet": "Tablet",
    "mobile phone": "Mobile",
    "mobile phones": "Mobile",
}


def _normalize_share_label(raw: str) -> str | None:
    label = re.sub(r"\s+", " ", (raw or "").strip(" .:;-–—"))
    if not label or len(label) > 40:
        return None
    low = label.lower()
    if low in _SHARE_ALIASES:
        return _SHARE_ALIASES[low]
    if low in _SHARE_STOP or low.isdigit():
        return None
    if low in {"unknown", "other", "others", "rest"}:
        return "Other" if low != "unknown" else "Unknown"
    # Title-case unknown brands; drop pure filler.
    if not re.search(r"[a-zA-Z]", label):
        return None
    return label if label[:1].isupper() else label.title()


def parse_share_percentages(text: str) -> list[tuple[str, float]]:
    """
    Extract label → percent pairs from free text / search snippets.

    Prefers markdown/HTML-ish table rows and known brand aliases so prose like
    "Windows holds 63%" does not pollute the pie.
    """
    # Preserve StatCounter's separate "OS X" vs "macOS" rows until the end.
    # key → (display_label, percent); first hit wins (tables before prose).
    found: dict[str, tuple[str, float]] = {}

    def _accept(raw_label: str, pct: float, *, require_alias: bool = False) -> None:
        if not (0.05 <= pct <= 99.9):
            return
        low = re.sub(r"\s+", " ", (raw_label or "").strip().lower())
        if not low or re.fullmatch(r"(19|20)\d{2}", low):
            return
        # Reject sentence fragments.
        if (
            re.search(
                r"(?i)\b(holds?|drops?|reported|made|account|combined|under|below|"
                r"roughly|about|nearly|around|share|market|percent|percentage|"
                r"worldwide|global|desktop|operating)\b",
                low,
            )
            and low not in _SHARE_ALIASES
            and low not in {"os x", "osx"}
        ):
            return
        if require_alias and low not in _SHARE_ALIASES and low not in {
            "unknown",
            "other",
            "others",
            "rest",
            "os x",
            "osx",
        }:
            return
        # Keep OS X distinct until merge step.
        if low in {"os x", "osx"}:
            label, key = "OS X", "os x"
        else:
            label = _normalize_share_label(raw_label)
            if not label:
                return
            key = label.lower()
        if key not in found:
            found[key] = (label, pct)

    blob = text or ""

    # 1) Markdown / pipe tables: | Windows | 56.61% |
    for m in re.finditer(
        r"(?im)^\s*\|\s*([A-Za-z][A-Za-z0-9./+\- ]{1,32}?)\s*\|\s*"
        r"(\d{1,2}(?:\.\d+)?)\s*%?\s*\|",
        blob,
    ):
        _accept(m.group(1), float(m.group(2)))

    # 2) Known brands with an adjacent percent (fill gaps only).
    brand_alt = "|".join(
        re.escape(k) for k in sorted(_SHARE_ALIASES.keys(), key=len, reverse=True)
    )
    for m in re.finditer(
        rf"(?i)\b({brand_alt}|unknown|other|os\s*x)\b\s*[:\|\-–—]?\s*"
        rf"(\d{{1,2}}(?:\.\d+)?)\s*%",
        blob,
    ):
        _accept(m.group(1), float(m.group(2)), require_alias=True)

    # 3) Numbered list: "1. Microsoft Windows: 62.16%"
    if len(found) < 2:
        for m in re.finditer(
            r"(?i)(?:^|[\n;•\-\u2022]|\d+\.\s*)"
            r"([A-Za-z][A-Za-z0-9./+\- ]{1,28}?)\s*[:\-–—]\s*"
            r"(\d{1,2}(?:\.\d+)?)\s*%",
            blob,
        ):
            _accept(m.group(1), float(m.group(2)))

    # Merge Apple desktop rows (StatCounter lists OS X and macOS separately).
    if "os x" in found:
        osx_pct = found.pop("os x")[1]
        if "macos" in found:
            label, pct = found["macos"]
            found["macos"] = (label, pct + osx_pct)
        else:
            found["macos"] = ("macOS", osx_pct)

    cleaned = list(found.values())
    cleaned.sort(key=lambda pair: pair[1], reverse=True)
    return cleaned[:8]


# Direct StatCounter Global Stats pages (stable, table-friendly).
SHARE_DIRECT_URLS: dict[str, tuple[str, str]] = {
    "os_share": (
        "https://gs.statcounter.com/os-market-share/desktop/worldwide",
        "StatCounter Global Stats",
    ),
    "browser_share": (
        "https://gs.statcounter.com/browser-market-share/desktop/worldwide",
        "StatCounter Global Stats",
    ),
    "mobile_os_share": (
        "https://gs.statcounter.com/os-market-share/mobile/worldwide",
        "StatCounter Global Stats",
    ),
    "search_share": (
        "https://gs.statcounter.com/search-engine-market-share/worldwide",
        "StatCounter Global Stats",
    ),
    "device_share": (
        "https://gs.statcounter.com/platform-market-share/desktop-mobile-tablet/worldwide",
        "StatCounter Global Stats",
    ),
}


def _share_search_query(topic_key: str, text: str) -> str:
    year = None
    y0, y1 = extract_year_range(text)
    if y1 is not None:
        year = y1
    elif y0 is not None:
        year = y0
    from datetime import datetime

    year = year or datetime.now().year
    # Market-share stats lag; prefer current/previous year in the query.
    year = min(year, datetime.now().year)
    topics = {
        "os_share": f"desktop operating system market share {year} percent StatCounter",
        "browser_share": f"web browser market share {year} percent StatCounter",
        "mobile_os_share": f"mobile operating system market share {year} percent StatCounter",
        "search_share": f"search engine market share {year} percent StatCounter",
        "device_share": f"desktop mobile tablet device traffic share {year} percent StatCounter",
    }
    return topics.get(topic_key, f"market share {year} percent")


def _looks_like_version_slice(label: str) -> bool:
    """True for 'Windows 11', 'Android 14', etc. — not top-level OS/browser brands."""
    return bool(re.search(r"(?i)\b(?:windows|android|macos|os\s*x|ios)\s*\d", label or ""))


def _collect_share_text(topic_key: str, query: str) -> tuple[str, str]:
    """
    Gather share tables: prefer StatCounter direct URL, then search snippets.

    Returns (combined_text, source_note).
    """
    chunks: list[str] = []
    source = "web search"
    try:
        from arka.agent.chat import duckduckgo_search, scrape_url

        direct = SHARE_DIRECT_URLS.get(topic_key)
        if direct:
            url, src_name = direct
            body = scrape_url(url, timeout=12)
            if body and len(body) > 80:
                chunks.append(body[:8000])
                source = src_name

        results = duckduckgo_search(query, max_results=5) or []
        for row in results:
            title = str(row.get("title") or "")
            snippet = str(row.get("snippet") or "")
            if title or snippet:
                chunks.append(f"{title}. {snippet}")
        # Prefer StatCounter hits from search if direct scrape was thin.
        if len(parse_share_percentages("\n".join(chunks))) < 2:
            for row in results:
                link = str(row.get("link") or "")
                if "statcounter.com" not in link.lower():
                    continue
                body = scrape_url(link, timeout=10)
                if body and len(body) > 80:
                    chunks.insert(0, body[:8000])
                    source = "StatCounter (via web)"
                    break
    except Exception:
        pass
    return "\n".join(chunks), source


def build_dataset_from_share(text: str, *, topic: str | None = None) -> ChartDataset:
    """Build a pie/bar dataset from web market-share percentages."""
    detected = detect_share_topic(text)
    if topic:
        title = next((t for k, t, _ in SHARE_SUBJECTS if k == topic), topic.replace("_", " ").title())
        topic_key = topic
    elif detected:
        topic_key, title = detected
    else:
        raise RuntimeError("Unsupported share topic (try OS, browser, or search engine share).")

    query = _share_search_query(topic_key, text)
    blob, source = _collect_share_text(topic_key, query)
    pairs = parse_share_percentages(blob)
    # Drop version breakdowns (Windows 11 vs 10) for top-level OS pies.
    if topic_key in {"os_share", "mobile_os_share"}:
        pairs = [(lbl, pct) for lbl, pct in pairs if not _looks_like_version_slice(lbl)]
    notes: list[str] = []
    used_fallback = False
    if len(pairs) < 2:
        pairs = list(SHARE_FALLBACKS.get(topic_key, []))
        used_fallback = True
        source = "illustrative fallback (web parse found no % table)"
        notes.append(
            "Could not parse live market-share percentages from the web; "
            "showing an illustrative breakdown. Pass explicit values like "
            "Windows:62,macOS:15 for exact figures."
        )

    # Collapse tiny "Unknown" into Other when present.
    cleaned: list[tuple[str, float]] = []
    other = 0.0
    for label, pct in pairs:
        if label.lower() in {"unknown", "other", "others", "rest"}:
            other += pct
            continue
        cleaned.append((label, pct))
    if other > 0:
        cleaned.append(("Other", other))
    if not cleaned:
        raise RuntimeError("No market-share slices available.")

    total = sum(p for _, p in cleaned)
    if total > 0 and abs(total - 100.0) > 8:
        notes.append(f"Parsed shares sum to {total:.1f}% (not normalized).")

    y0, y1 = extract_year_range(text)
    year_note = y1 or y0
    chart_title = title
    if year_note:
        chart_title = f"{title} ({year_note})"

    categories = [lbl for lbl, _ in cleaned]
    values = [float(pct) for _, pct in cleaned]
    if not used_fallback:
        notes.append(f"Search query: {query}")

    return ChartDataset(
        topic=topic_key,
        indicator="market_share_pct",
        title=chart_title,
        ylabel="Share (%)",
        categories=categories,
        series=[ChartSeries(name="share", values=values)],
        source=source,
        notes=notes,
        years=[],
    )


# Scatter fetch: paired financial metrics (e.g. ad spend vs revenue) for a named company.
SCATTER_AXIS_PAIRS: tuple[tuple[str, re.Pattern[str], re.Pattern[str], str, str], ...] = (
    (
        "ad_revenue",
        re.compile(r"(?i)\b(?:ad|ads|advertis\w*)\s+spend(?:ing)?\b"),
        re.compile(r"(?i)\brevenue\b|\bsales\b|\bturnover\b"),
        "Ad spend",
        "Revenue",
    ),
    (
        "marketing_revenue",
        re.compile(r"(?i)\b(?:marketing|promotion)\s+spend(?:ing)?\b|\bmarketing\s+expense\b"),
        re.compile(r"(?i)\brevenue\b|\bsales\b|\bturnover\b"),
        "Marketing spend",
        "Revenue",
    ),
)

# X-metric SEC us-gaap tags (first hit wins).
SCATTER_SEC_X_TAGS: tuple[str, ...] = (
    "AdvertisingExpense",
    "SellingAndMarketingExpense",
    "SellingGeneralAndAdministrativeExpense",
)
SCATTER_SEC_Y_TAGS: tuple[str, ...] = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
)

SCATTER_ENTITY_ALIASES: dict[str, dict[str, str]] = {
    "blinkit": {
        "display": "Blinkit (Zomato parent)",
        "query": "Zomato",
        "ticker": "ZOMATO.NS",
        "note": "Blinkit is private; using parent Zomato Ltd consolidated figures where available.",
    },
    "zomato": {"display": "Zomato", "query": "Zomato", "ticker": "ZOMATO.NS"},
    "eternal": {"display": "Eternal (Zomato)", "query": "Zomato", "ticker": "ZOMATO.NS"},
    "meta": {"display": "Meta", "query": "Meta Platforms", "ticker": "META"},
    "facebook": {"display": "Meta", "query": "Meta Platforms", "ticker": "META"},
    "amazon": {"display": "Amazon", "query": "Amazon", "ticker": "AMZN"},
    "google": {"display": "Alphabet", "query": "Alphabet Google", "ticker": "GOOGL"},
    "alphabet": {"display": "Alphabet", "query": "Alphabet Google", "ticker": "GOOGL"},
    "apple": {"display": "Apple", "query": "Apple", "ticker": "AAPL"},
    "microsoft": {"display": "Microsoft", "query": "Microsoft", "ticker": "MSFT"},
    "netflix": {"display": "Netflix", "query": "Netflix", "ticker": "NFLX"},
    "nvidia": {"display": "Nvidia", "query": "Nvidia", "ticker": "NVDA"},
    "tesla": {"display": "Tesla", "query": "Tesla", "ticker": "TSLA"},
}

_SEC_TICKERS_CACHE: dict[str, dict[str, str]] | None = None


@dataclass
class ScatterDataset:
    topic: str
    title: str
    xlabel: str
    ylabel: str
    periods: list[str]
    xs: list[float]
    ys: list[float]
    source: str
    notes: list[str] = field(default_factory=list)
    entity: str = ""


def parse_scatter_axes(text: str) -> tuple[str, str, str, str] | None:
    """Return (topic_key, xlabel, ylabel, metric_phrase) for 'x vs y' scatter requests."""
    t = text or ""
    if not re.search(r"(?i)\b(?:vs\.?|versus|against)\b", t):
        return None
    for key, x_pat, y_pat, xlabel, ylabel in SCATTER_AXIS_PAIRS:
        if x_pat.search(t) and y_pat.search(t):
            return key, xlabel, ylabel, f"{xlabel} vs {ylabel}"
    return None


def extract_scatter_entity(text: str) -> str | None:
    """Company/brand named after 'for' in scatter NL (e.g. '… for blinkit')."""
    t = text or ""
    m = re.search(
        r"(?i)\bfor\s+([a-z][a-z0-9.&\s-]{1,40}?)"
        r"(?:\s*$|\s+(?:from|in|over|during|between)\b|[,.])",
        t,
    )
    if not m:
        return None
    entity = re.sub(r"\s+", " ", m.group(1).strip(" .,:;-"))
    if not entity or entity.lower() in {"the", "a", "an", "each", "every"}:
        return None
    return entity


def _scatter_has_inline_pairs(text: str) -> bool:
    """True when NL already includes three or more explicit x:y numeric pairs."""
    cleaned = re.sub(
        r"(?i)\b(scatter|plot|chart|graph|correlation|correlate|points?|data)\b",
        " ",
        text or "",
    )
    pairs = 0
    for _ in re.finditer(r"(\d+(?:\.\d+)?)\s*[:=]\s*(\d+(?:\.\d+)?)", cleaned):
        pairs += 1
    if pairs >= 3:
        return True
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", cleaned)]
    return len(nums) >= 6


def needs_scatter_fetch(text: str) -> bool:
    """True for 'scatter <x> vs <y> for <company>' without inline numeric pairs."""
    t = text or ""
    if re.search(r"--data\b", t, re.I):
        return False
    if not re.search(r"(?i)\b(scatter|correlation)\b", t):
        return False
    if parse_scatter_axes(t) is None:
        return False
    if extract_scatter_entity(t) is None:
        return False
    return not _scatter_has_inline_pairs(t)


def resolve_scatter_entity(name: str) -> tuple[str, str, str | None, str]:
    """
    Resolve NL entity → (display_name, search_query, us_ticker_or_none, note).

    Private subsidiaries (e.g. Blinkit) map to a public parent when known.
    """
    raw = re.sub(r"\s+", " ", (name or "").strip())
    low = raw.lower()
    alias = SCATTER_ENTITY_ALIASES.get(low)
    if alias:
        return (
            alias.get("display", raw.title()),
            alias.get("query", raw.title()),
            alias.get("ticker"),
            alias.get("note", ""),
        )
    # Treat short alpha tokens as US tickers (META, AMZN).
    if re.fullmatch(r"[A-Za-z]{1,5}(?:\.[A-Za-z]{1,3})?", raw):
        return raw.upper(), raw.upper(), raw.upper(), ""
    return raw.title(), raw.title(), None, ""


def _sec_load_company_tickers() -> dict[str, dict[str, str]]:
    global _SEC_TICKERS_CACHE
    if _SEC_TICKERS_CACHE is not None:
        return _SEC_TICKERS_CACHE
    url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": SEC_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=WORLDBANK_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
        OSError,
    ) as exc:
        raise RuntimeError(f"SEC ticker lookup failed: {exc}") from exc
    out: dict[str, dict[str, str]] = {}
    if isinstance(payload, dict):
        for row in payload.values():
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").upper()
            if ticker:
                out[ticker] = row
    _SEC_TICKERS_CACHE = out
    return out


def _sec_cik_for_ticker(ticker: str) -> str | None:
    row = _sec_load_company_tickers().get((ticker or "").upper())
    if not row:
        return None
    try:
        return f"{int(row['cik_str']):010d}"
    except (KeyError, TypeError, ValueError):
        return None


def _sec_http_json(url: str) -> object:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": SEC_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=WORLDBANK_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
        OSError,
    ) as exc:
        raise RuntimeError(f"SEC request failed: {exc}") from exc


def _sec_annual_usd(facts: dict, tags: tuple[str, ...]) -> dict[int, float]:
    """Latest 10-K value per fiscal year for the first matching us-gaap tag."""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    if not isinstance(us_gaap, dict):
        return {}
    for tag in tags:
        block = us_gaap.get(tag)
        if not isinstance(block, dict):
            continue
        units = block.get("units", {})
        rows = units.get("USD") if isinstance(units, dict) else None
        if not isinstance(rows, list):
            continue
        by_fy: dict[int, tuple[str, float]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("form") not in ("10-K", "10-K/A"):
                continue
            try:
                fy = int(row.get("fy"))
                val = float(row.get("val"))
            except (TypeError, ValueError):
                continue
            filed = str(row.get("filed") or "")
            prev = by_fy.get(fy)
            if prev is None or filed > prev[0]:
                by_fy[fy] = (filed, val)
        if by_fy:
            return {fy: val for fy, (_filed, val) in sorted(by_fy.items())}
    return {}


def fetch_scatter_from_sec(
    ticker: str,
    *,
    x_tags: tuple[str, ...] = SCATTER_SEC_X_TAGS,
    y_tags: tuple[str, ...] = SCATTER_SEC_Y_TAGS,
) -> tuple[list[int], list[float], list[float], str, list[str]]:
    """Return (years, xs, ys, source_note, notes) from SEC EDGAR XBRL company facts."""
    cik = _sec_cik_for_ticker(ticker)
    if not cik:
        raise RuntimeError(f"{ticker} is not a US SEC registrant (no CIK).")
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    payload = _sec_http_json(url)
    if not isinstance(payload, dict):
        raise RuntimeError("SEC returned unexpected company facts payload.")
    xs_by_year = _sec_annual_usd(payload, x_tags)
    ys_by_year = _sec_annual_usd(payload, y_tags)
    if not xs_by_year or not ys_by_year:
        raise RuntimeError(
            f"SEC filings for {ticker} lack annual ad/marketing and revenue tags."
        )
    years = sorted(set(xs_by_year) & set(ys_by_year))
    if len(years) < 3:
        raise RuntimeError(
            f"SEC data for {ticker} has fewer than 3 years with both metrics "
            f"(found {len(years)})."
        )
    years = years[-8:]
    notes: list[str] = []
    used_tag = next(
        (
            tag
            for tag in x_tags
            if isinstance(payload.get("facts", {}).get("us-gaap", {}).get(tag), dict)
        ),
        x_tags[0],
    )
    if used_tag == "SellingGeneralAndAdministrativeExpense":
        notes.append(
            "X-axis uses SG&A (selling, general & administrative) as the closest "
            "public filing tag when advertising expense is not reported separately."
        )
    return (
        years,
        [xs_by_year[y] for y in years],
        [ys_by_year[y] for y in years],
        f"SEC EDGAR XBRL (data.sec.gov, {ticker})",
        notes,
    )


def _scatter_scale_amount(raw: str, unit: str | None) -> float:
    num = float(str(raw).replace(",", ""))
    u = (unit or "").lower().strip(".")
    if u in {"crore", "cr", "crores"}:
        return num * 1e7
    if u in {"billion", "bn", "billions"}:
        return num * 1e9
    if u in {"million", "mn", "millions", "m"}:
        return num * 1e6
    if u in {"lakh", "lac", "lakhs"}:
        return num * 1e5
    return num


def _parse_metric_year_values(blob: str, metric_words: tuple[str, ...]) -> dict[int, float]:
    """Best-effort year → amount from search snippets / scraped pages."""
    found: dict[int, float] = {}
    if not blob:
        return found
    words = "|".join(metric_words)
    metric_re = re.compile(rf"(?i)(?:{words})")
    year_re = re.compile(r"(?i)(?:fy\s*)?(20\d{2})")
    amount_re = re.compile(
        r"(?i)(?:rs\.?|₹|inr|usd|\$)?\s*([\d][\d,]*(?:\.\d+)?)\s*"
        r"(crore|cr|billion|bn|million|mn|lakh|lac)?"
    )

    for sentence in re.split(r"[.\n;]+", blob):
        if not metric_re.search(sentence):
            continue
        year_m = year_re.search(sentence)
        if not year_m:
            continue
        year = int(year_m.group(1))
        if not (2010 <= year <= 2100):
            continue
        # Prefer the amount closest after the metric keyword.
        metric_m = metric_re.search(sentence)
        tail = sentence[metric_m.end() :] if metric_m else sentence
        amount_m = amount_re.search(tail) or amount_re.search(sentence)
        if not amount_m:
            continue
        amt = _scatter_scale_amount(amount_m.group(1), amount_m.group(2))
        if amt > 0:
            found[year] = amt
    return found


def _collect_scatter_web_text(query_name: str, *, xlabel: str, ylabel: str) -> str:
    """Gather financial prose via web search (and one on-topic page when available)."""
    chunks: list[str] = []
    queries = [
        f"{query_name} annual {xlabel} {ylabel} FY report crore",
        f"{query_name} {xlabel} {ylabel} annual report 10-K",
    ]
    try:
        from arka.agent.chat import duckduckgo_search, scrape_url

        for query in queries:
            results = duckduckgo_search(query, max_results=5) or []
            for row in results:
                title = str(row.get("title") or "")
                snippet = str(row.get("snippet") or "")
                if title or snippet:
                    chunks.append(f"{title}. {snippet}")
            if len(chunks) >= 4:
                break
        for row in results[:2]:
            link = str(row.get("link") or "")
            if not link:
                continue
            body = scrape_url(link, timeout=10)
            if body and len(body) > 120:
                chunks.append(body[:10000])
    except Exception:
        pass
    return "\n".join(chunks)


def fetch_scatter_from_web(
    query_name: str,
    *,
    xlabel: str,
    ylabel: str,
) -> tuple[list[int], list[float], list[float], str, list[str]]:
    """Fallback scatter points from public web text when SEC data is unavailable."""
    blob = _collect_scatter_web_text(query_name, xlabel=xlabel, ylabel=ylabel)
    x_words = (
        r"advertis\w*",
        r"marketing\w*",
        r"ad\s+spend(?:ing)?",
        r"ad\s+expenses?",
        r"promotion\w*",
    )
    y_words = (
        r"revenue\w*",
        r"sales",
        r"turnover",
        r"operating\s+revenue",
    )
    xs_by_year = _parse_metric_year_values(blob, x_words)
    ys_by_year = _parse_metric_year_values(blob, y_words)
    years = sorted(set(xs_by_year) & set(ys_by_year))
    if len(years) < 3:
        raise RuntimeError(
            f"Could not find at least 3 public year-pairs of {xlabel} vs {ylabel} "
            f"for {query_name} from web sources."
        )
    years = years[-8:]
    return (
        years,
        [xs_by_year[y] for y in years],
        [ys_by_year[y] for y in years],
        f"Public web sources (search snippets for {query_name})",
        [
            "Parsed from news/report snippets; figures may mix fiscal periods or units. "
            "Prefer US-listed companies for audited SEC EDGAR data."
        ],
    )


def build_scatter_dataset(text: str) -> ScatterDataset:
    """Build scatter x/y pairs for 'scatter <metric> vs <metric> for <company>'."""
    axes = parse_scatter_axes(text)
    entity_raw = extract_scatter_entity(text)
    if axes is None or entity_raw is None:
        raise RuntimeError(
            "Scatter fetch needs a pattern like "
            "'scatter ad spend vs revenue for <company>'."
        )
    _topic, xlabel, ylabel, metric_phrase = axes
    display, query, ticker, alias_note = resolve_scatter_entity(entity_raw)

    notes: list[str] = []
    if alias_note:
        notes.append(alias_note)

    years: list[int]
    xs: list[float]
    ys: list[float]
    source: str
    extra_notes: list[str]

    sec_ticker: str | None = None
    if ticker:
        try:
            if _sec_cik_for_ticker(ticker):
                sec_ticker = ticker.upper()
        except RuntimeError:
            sec_ticker = None
    if sec_ticker:
        years, xs, ys, source, extra_notes = fetch_scatter_from_sec(sec_ticker)
    else:
        try:
            years, xs, ys, source, extra_notes = fetch_scatter_from_web(
                query, xlabel=xlabel, ylabel=ylabel
            )
        except RuntimeError as web_exc:
            hint = (
                f" Could not load SEC data for {display}"
                f"{f' (ticker {ticker})' if ticker else ''}."
            )
            raise RuntimeError(f"{web_exc}{hint}") from web_exc

    notes.extend(extra_notes)
    periods = [f"FY{y}" for y in years]
    title = f"{display}: {metric_phrase} ({periods[0]}–{periods[-1]})"
    return ScatterDataset(
        topic="scatter_financial",
        title=title,
        xlabel=xlabel,
        ylabel=ylabel,
        periods=periods,
        xs=xs,
        ys=ys,
        source=source,
        notes=notes,
        entity=display,
    )


def build_dataset(text: str, **kwargs: object) -> ChartDataset:
    """Route NL chart requests to web market-share or World Bank indicators."""
    share = detect_share_topic(text)
    indicator = detect_topic(text)
    # OS/browser/search share pies win over World Bank when both could match
    # (e.g. "internet" substring) — only if the user clearly asked for a share chart.
    if share and (indicator is None or any(
        w in (text or "").lower()
        for w in ("pie", "distribution", "breakdown", "market share", "share of", "os ", " os", "browser")
    )):
        if indicator is None or share[0] in {
            "os_share",
            "browser_share",
            "mobile_os_share",
            "search_share",
            "device_share",
        }:
            # Don't steal genuine World Bank "internet users" charts.
            if indicator == "internet" and "browser" not in (text or "").lower():
                return build_dataset_from_worldbank(text, **kwargs)  # type: ignore[arg-type]
            return build_dataset_from_share(text)
    return build_dataset_from_worldbank(text, **kwargs)  # type: ignore[arg-type]


def dataset_to_single_bar(dataset: ChartDataset) -> tuple[list[str], list[float]]:
    """Flatten to one bar series: years (single country) or latest year across countries."""
    if not dataset.series:
        return [], []
    # Single-country layout already has years as categories.
    if len(dataset.series) == 1:
        return list(dataset.categories), list(dataset.series[0].values)
    latest = dataset.series[-1]
    return list(dataset.categories), list(latest.values)


def dataset_to_line_points(dataset: ChartDataset) -> list[tuple[str, list[int], list[float]]]:
    """
    Convert to per-country time series for line charts.

    Returns list of (country_name, years, values).
    """
    out: list[tuple[str, list[int], list[float]]] = []

    # Layout A: categories = years, one series per country (preferred for 1 country).
    year_cats: list[int] = []
    for cat in dataset.categories:
        try:
            year_cats.append(int(str(cat).strip()))
        except ValueError:
            year_cats = []
            break
    if year_cats and dataset.series:
        for series in dataset.series:
            xs: list[int] = []
            ys: list[float] = []
            for year, val in zip(year_cats, series.values):
                if val != val:  # NaN
                    continue
                xs.append(year)
                ys.append(val)
            if xs:
                out.append((series.name, xs, ys))
        if out:
            return out

    # Layout B: categories = countries, series = years.
    for idx, cat in enumerate(dataset.categories):
        ys = []
        xs = []
        for series in dataset.series:
            if idx >= len(series.values):
                continue
            val = series.values[idx]
            if val != val:  # NaN
                continue
            try:
                year = int(series.name)
            except ValueError:
                continue
            xs.append(year)
            ys.append(val)
        if xs:
            out.append((cat, xs, ys))
    return out
