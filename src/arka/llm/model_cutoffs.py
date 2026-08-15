#!/usr/bin/env python3
"""Knowledge-cutoff registry and model-aware web-search triggering."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from functools import lru_cache
from typing import NamedTuple

# Live / volatile topics — search regardless of model cutoff.
ALWAYS_SEARCH_KEYWORDS: tuple[str, ...] = (
    "latest",
    "recent",
    "now",
    "today",
    "current",
    "live",
    "hackathon",
    "conference",
    "release",
    "update",
    "changelog",
    "event",
    "news",
    "announcement",
    "stock",
    "price",
    "value",
    "market",
    "crypto",
    "ipl",
    "t20",
    "cricket",
    "match",
    "score",
    "winner",
    "championship",
    "fifa",
    "nfl",
    "nba",
    "wimbledon",
    "olympics",
    "documentation",
    "api",
    "tutorial",
    "guide",
    "weather",
)

# When the query year equals the model cutoff year, these imply post-cutoff facts.
CUTOFF_YEAR_EVENT_KEYWORDS: tuple[str, ...] = (
    "winner",
    "won",
    "score",
    "result",
    "final",
    "champion",
    "release",
    "launched",
    "announced",
    "election",
    "appointed",
    "ipo",
    "acquired",
    "merger",
)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# (model id regex, knowledge cutoff). Order matters — first match wins.
_BUILTIN_CUTOFFS: tuple[tuple[re.Pattern[str], date], ...] = (
    (re.compile(r"gemini-2\.5", re.I), date(2025, 1, 1)),
    (re.compile(r"gemini-2\.0", re.I), date(2024, 8, 1)),
    (re.compile(r"gemini-1\.5", re.I), date(2024, 4, 1)),
    (re.compile(r"gemini-1\.0|gemini-pro(?!-vision)", re.I), date(2023, 4, 1)),
    (re.compile(r"llama-3\.3|llama3\.3", re.I), date(2024, 12, 1)),
    (re.compile(r"llama-3\.1|llama3\.1", re.I), date(2023, 12, 1)),
    (re.compile(r"llama-3\.2|llama3\.2", re.I), date(2023, 12, 1)),
    (re.compile(r"llama-?3(?!\.|\-)", re.I), date(2023, 3, 1)),
    (re.compile(r"llama-?2", re.I), date(2022, 9, 1)),
    (re.compile(r"gpt-4o-mini", re.I), date(2024, 10, 1)),
    (re.compile(r"gpt-4o", re.I), date(2024, 10, 1)),
    (re.compile(r"gpt-4-turbo", re.I), date(2023, 12, 1)),
    (re.compile(r"gpt-4(?!o)", re.I), date(2023, 4, 1)),
    (re.compile(r"gpt-3\.5", re.I), date(2021, 9, 1)),
    (re.compile(r"claude-sonnet-4|claude-4", re.I), date(2025, 3, 1)),
    (re.compile(r"claude-3\.5|claude-3-5", re.I), date(2024, 4, 1)),
    (re.compile(r"claude-3", re.I), date(2023, 8, 1)),
    (re.compile(r"deepseek-v3|deepseek-r1", re.I), date(2024, 7, 1)),
    (re.compile(r"deepseek", re.I), date(2023, 11, 1)),
    (re.compile(r"mistral-large", re.I), date(2024, 4, 1)),
    (re.compile(r"mixtral", re.I), date(2023, 12, 1)),
    (re.compile(r"qwen3|qwen-3", re.I), date(2024, 9, 1)),
    (re.compile(r"qwen2\.5|qwen-2\.5", re.I), date(2024, 6, 1)),
    (re.compile(r"qwen", re.I), date(2023, 9, 1)),
    (re.compile(r"gemma-3|gemma3", re.I), date(2024, 10, 1)),
    (re.compile(r"gemma-?2", re.I), date(2024, 2, 1)),
    (re.compile(r"minimax", re.I), date(2024, 6, 1)),
    (re.compile(r"apple-fm", re.I), date(2024, 6, 1)),
)


class ModelCutoff(NamedTuple):
    provider: str
    model_id: str
    cutoff: date


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def model_aware_search_enabled() -> bool:
    return env("MODEL_AWARE_SEARCH", "1").lower() not in {"0", "false", "no", "off"}


def _default_cutoff() -> date:
    raw = env("MODEL_DEFAULT_CUTOFF", "2023-01-01")
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return date(2023, 1, 1)


@lru_cache(maxsize=1)
def _load_cutoff_overrides() -> dict[str, date]:
    raw = env("MODEL_CUTOFF_OVERRIDES")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, date] = {}
    for key, value in data.items():
        label = str(key).strip().lower()
        if not label:
            continue
        try:
            out[label] = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
    return out


def normalize_model_label(provider: str, model_id: str) -> str:
    p = (provider or "").strip().lower()
    m = (model_id or "").strip()
    if p and m:
        return f"{p}/{m}".lower()
    return m.lower()


def resolve_knowledge_cutoff(provider: str, model_id: str) -> date:
    """Return the training-data cutoff for ``provider/model_id``."""
    label = normalize_model_label(provider, model_id)
    overrides = _load_cutoff_overrides()
    if label in overrides:
        return overrides[label]
    bare = (model_id or "").strip().lower()
    if bare in overrides:
        return overrides[bare]

    for pattern, cutoff in _BUILTIN_CUTOFFS:
        if pattern.search(model_id or "") or pattern.search(label):
            return cutoff
    return _default_cutoff()


def resolve_effective_chat_model(*, task: str | None = None, skill: str | None = None) -> tuple[str, str]:
    """First available provider/model for chat-style Q&A."""
    try:
        from arka.llm.fallback import EXHAUSTION, ordered_model_candidates, provider_available
    except ImportError:
        return "", ""

    for provider, model_id in ordered_model_candidates(task=task or "chat", skill=skill or "web_answer"):
        if not provider_available(provider):
            continue
        if EXHAUSTION.exhausted(provider, model_id):
            continue
        return provider, model_id
    chain = ordered_model_candidates(task=task or "chat", skill=skill or "web_answer")
    if chain:
        return chain[0]
    return "", ""


def active_model_cutoff(*, task: str | None = None, skill: str | None = None) -> ModelCutoff | None:
    if not model_aware_search_enabled():
        return None
    provider, model_id = resolve_effective_chat_model(task=task, skill=skill)
    if not model_id:
        return None
    return ModelCutoff(provider, model_id, resolve_knowledge_cutoff(provider, model_id))


def extract_years(text: str) -> list[int]:
    return [int(match.group(0)) for match in _YEAR_RE.finditer(text or "")]


def query_postdates_cutoff(text: str, cutoff: date) -> bool:
    """True when the query references facts likely after the model cutoff."""
    years = extract_years(text)
    if not years:
        return False
    low = (text or "").lower()
    for year in years:
        if year > cutoff.year:
            return True
        if year == cutoff.year and any(
            re.search(r"\b" + re.escape(kw) + r"\b", low) for kw in CUTOFF_YEAR_EVENT_KEYWORDS
        ):
            return True
    return False


def cutoff_search_keywords(cutoff: date) -> tuple[str, ...]:
    """Year tokens that should trigger search for this cutoff."""
    current = datetime.now().year
    years: list[str] = []
    for year in range(cutoff.year + 1, current + 2):
        years.append(str(year))
    return tuple(years)


def should_search_for_model(
    text: str,
    *,
    task: str | None = None,
    skill: str | None = None,
    cutoff: ModelCutoff | None = None,
) -> bool:
    """Model-aware search trigger beyond static live-data keywords."""
    if not model_aware_search_enabled():
        return False
    info = cutoff or active_model_cutoff(task=task, skill=skill)
    if info is None:
        return False
    if query_postdates_cutoff(text, info.cutoff):
        return True
    low = (text or "").lower()
    for kw in cutoff_search_keywords(info.cutoff):
        if re.search(r"\b" + re.escape(kw) + r"\b", low):
            return True
    return False


def format_cutoff_for_prompt(cutoff: date) -> str:
    return cutoff.strftime("%B %Y")
