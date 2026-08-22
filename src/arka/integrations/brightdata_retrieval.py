"""Bright Data search & retrieval — decision matrix, query tuning, geo targeting."""

from __future__ import annotations

import os
import re

BRIGHTDATA_RETRIEVAL_SYSTEM = """\
You are a Real-Time Intelligence Assistant. Provide accurate, grounded answers using \
Bright Data (Web Search, Web Scraper, LLM Scraper) for verified live web data.

Do NOT search for simple arithmetic, direct logic, pure code generation, or static \
historical knowledge before your training cutoff.

Trigger Bright Data ONLY for:
- Time-sensitive data (breaking news, markets, recent events)
- Dynamic entities (prices, availability, specs, event dates)
- Fact verification (statistics, press releases, citations)
- Deep site extraction (specific pages, threads, product listings)

Search payload rules:
- Strip conversational noise; use precise keywords + dates/site: operators.
- Prefer markdown scrape output for narrative context; JSON/SERP rows for headlines.
- Set geo_location to match user geography (us, uk, in, …).
- Use num_results sparingly (5–8); never invent URLs not present in results.
"""

_CONVERSATIONAL_PREFIX_RE = re.compile(
    r"(?i)^(?:"
    r"(?:please\s+)?(?:(?:can you|could you|would you)\s+)?"
    r"(?:tell me|give me|show me|find|get|summarize|share)\s+"
    r"|(?:i want|i need|looking for)\s+(?:the\s+)?"
    r"|(?:what is|what are|what's)\s+the\s+(?:best|latest|current)\s+"
    r")+"
)

_CONVERSATIONAL_MIDDLE_RE = re.compile(
    r"(?i)\b(?:the\s+best\s+)?(?:latest\s+)?(?:news\s+)?(?:that is in|from|on|about)\s+"
)

_CONVERSATIONAL_SUFFIX_RE = re.compile(
    r"(?i)\s+(?:please|thanks|thank you|for me|right now|as of today)\.?$"
)

_SKIP_BRIGHTDATA_PATTERNS: tuple[str, ...] = (
    r"^\s*(?:what is|what's)\s+\d+\s*[\+\-\*/×÷]",
    r"^\s*(?:compute|calculate|solve)\s+\d",
    r"^\s*(?:write|generate|implement|debug|refactor)\s+(?:a\s+)?(?:python|javascript|typescript|rust|go|code)\b",
    r"^\s*(?:explain|describe)\s+(?:how\s+)?(?:for loops?|recursion|binary search)\b",
)

_TIME_SENSITIVE_RE = re.compile(
    r"(?i)\b("
    r"latest|recent|today|todays|current|breaking|live|now|news|headlines?|"
    r"stock|price|market|crypto|weather|release|changelog|announcement|"
    r"verify|fact check|press release"
    r")\b"
)


def brightdata_retrieval_system_prompt() -> str:
    return BRIGHTDATA_RETRIEVAL_SYSTEM.strip()


def should_trigger_brightdata_search(question: str, *, deep: bool = False) -> bool:
    """Decision matrix: skip static/code/math; search time-sensitive or deep lookups."""
    q = (question or "").strip()
    if not q:
        return False
    for pattern in _SKIP_BRIGHTDATA_PATTERNS:
        if re.search(pattern, q):
            return False
    try:
        from arka.agent.chat import detect_math

        if detect_math(q):
            return False
    except ImportError:
        pass
    if deep:
        return True
    if _TIME_SENSITIVE_RE.search(q):
        return True
    try:
        from arka.agent.daily_brief import should_use_live_news_web

        if should_use_live_news_web(q):
            return True
    except ImportError:
        pass
    try:
        from arka.agent.chat import should_auto_search

        return should_auto_search(q)
    except ImportError:
        return False


def optimize_brightdata_query(question: str) -> str:
    """Strip conversational noise; keep keywords, dates, and site: operators."""
    q = re.sub(r"\s+", " ", (question or "").strip())
    if not q:
        return q
    q = _CONVERSATIONAL_PREFIX_RE.sub("", q)
    q = _CONVERSATIONAL_MIDDLE_RE.sub("", q)
    q = _CONVERSATIONAL_SUFFIX_RE.sub("", q)
    q = re.sub(r"\s+", " ", q).strip(" ,.;")
    return q or (question or "").strip()


def infer_brightdata_geo_location(question: str) -> str:
    """Return a 2-letter Bright Data geo_location code (default from env or us)."""
    q = (question or "").lower()
    try:
        from arka.agent.daily_brief import news_source_host

        host = news_source_host(question)
        if host == "bbc.com":
            return "uk"
        if host in {"ndtv.com", "indiatoday.in"}:
            return "in"
    except ImportError:
        host = ""

    if re.search(r"\b(india|indian|delhi|mumbai|bangalore|bengaluru|nse|bse|rupee)\b", q):
        return "in"
    if re.search(r"\b(uk|britain|british|london|scotland|wales|bbc)\b", q):
        return "uk"
    if re.search(r"\b(eu|europe|eurozone|frankfurt|paris|berlin)\b", q):
        return "de"
    if re.search(r"\b(australia|sydney|melbourne|aud)\b", q):
        return "au"
    if re.search(r"\b(canada|toronto|cad)\b", q):
        return "ca"

    default = (os.environ.get("BRIGHTDATA_SEARCH_GEO") or "us").strip().lower()
    return default[:2] if len(default) >= 2 else "us"


def brightdata_search_parameters(question: str, *, optimized_query: str = "") -> dict[str, str]:
    """Build Bright Data search_engine arguments from a user question."""
    query = optimize_brightdata_query(optimized_query or question)
    params: dict[str, str] = {
        "query": query,
        "engine": (os.environ.get("BRIGHTDATA_SEARCH_ENGINE") or "google").strip().lower(),
    }
    geo = infer_brightdata_geo_location(question)
    if geo:
        params["geo_location"] = geo
    return params
