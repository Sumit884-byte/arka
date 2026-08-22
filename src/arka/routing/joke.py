"""Detect joke requests and fetch jokes from public APIs (no LLM generation)."""

from __future__ import annotations

import json
import random
import re
import urllib.error
import urllib.parse
import urllib.request

_ICANHAZ = "https://icanhazdadjoke.com"
_JOKEAPI = "https://v2.jokeapi.dev/joke/Any"
_USER_AGENT = "Arka (https://github.com/sumitmishra/arka; joke fetcher)"

_EXCLUDE = re.compile(
    r"(?i)\b("
    r"fun\s+fact|random\s+fact|something\s+interesting|trivia|"
    r"explain\s+(?:the|this|that)\s+joke|meaning\s+of\s+(?:the|this|that)\s+joke"
    r")\b"
)

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)^(please\s+)?(tell|give|share|send)\s+(me\s+)?(a\s+)?"
        r"(dad\s+joke|funny\s+joke|joke)\b"
    ),
    re.compile(r"(?i)^(please\s+)?(got|have)\s+(any\s+)?(a\s+)?jokes?\b"),
    re.compile(r"(?i)^(please\s+)?jokes?\b"),
    re.compile(r"(?i)^(please\s+)?make\s+me\s+laugh\b"),
    re.compile(r"(?i)^(please\s+)?(tell|give)\s+(me\s+)?(a\s+)?joke\s+about\b"),
)

_TOPIC = re.compile(
    r"(?i)(?:"
    r"(?:dad\s+joke|funny\s+joke|joke|jokes)\s+about|"
    r"joke\s+on|jokes?\s+on"
    r")\s+(.+)$"
)


def is_joke_request(text: str) -> bool:
    """True for casual joke prompts, not fact lookup or joke explanation."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return False
    if _EXCLUDE.search(clean):
        return False
    if _TOPIC.search(clean):
        return True
    return any(p.search(clean) for p in _PATTERNS)


def extract_joke_topic(text: str) -> str | None:
    """Optional topic from phrases like 'joke about robots'."""
    clean = " ".join((text or "").split()).strip()
    match = _TOPIC.search(clean)
    if not match:
        return None
    topic = match.group(1).strip().rstrip("?.!")
    return topic or None


def _http_json(url: str, *, timeout: float = 8.0) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        OSError,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
    ):
        return None
    return data if isinstance(data, dict) else None


def _fetch_random_icanhazdadjoke() -> str | None:
    data = _http_json(f"{_ICANHAZ}/")
    if not data:
        return None
    joke = data.get("joke")
    return joke.strip() if isinstance(joke, str) and joke.strip() else None


def _fetch_search_icanhazdadjoke(topic: str) -> str | None:
    params = urllib.parse.urlencode({"term": topic, "limit": 8})
    data = _http_json(f"{_ICANHAZ}/search?{params}")
    if not data:
        return None
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    jokes = [
        str(item.get("joke", "")).strip()
        for item in results
        if isinstance(item, dict) and str(item.get("joke", "")).strip()
    ]
    if not jokes:
        return None
    return random.choice(jokes)


def _fetch_jokeapi_fallback() -> str | None:
    params = urllib.parse.urlencode({"type": "single", "safe-mode": "", "format": "json"})
    data = _http_json(f"{_JOKEAPI}?{params}")
    if not data:
        return None
    if data.get("type") == "single":
        joke = data.get("joke")
        return joke.strip() if isinstance(joke, str) and joke.strip() else None
    setup = data.get("setup")
    delivery = data.get("delivery")
    if isinstance(setup, str) and isinstance(delivery, str):
        text = f"{setup.strip()} {delivery.strip()}".strip()
        return text or None
    return None


def fetch_joke(text: str = "", *, topic: str | None = None) -> str:
    """Fetch a joke from public APIs. Returns empty string when all sources fail."""
    resolved = (topic or extract_joke_topic(text) or "").strip()
    if resolved:
        hit = _fetch_search_icanhazdadjoke(resolved)
        if hit:
            return hit
    hit = _fetch_random_icanhazdadjoke()
    if hit:
        return hit
    return _fetch_jokeapi_fallback() or ""
