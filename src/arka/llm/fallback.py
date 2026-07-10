#!/usr/bin/env python3
"""Modular LLM provider/model fallback for all Arka skills and talents."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from arka.llm.api_keys import (
    apply_provider_key,
    iter_provider_keys,
    is_key_retryable,
    provider_has_keys,
    reset_key_rotators,
    rotate_provider_key,
    key_rotation_label,
)
from arka.llm.providers import (
    get_provider,
    provider_api_key,
    provider_base_url,
    provider_model_ids,
    provider_specs,
)
from arka.llm.servers import (
    LOCAL_PROVIDERS,
    LlmServerSession,
    apply_vllm_defaults,
    is_reachable,
    provider_available_with_servers,
    vllm_explicitly_configured,
)

DEFAULT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
]

DEFAULT_GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama-3.3-70b-specdec",
    "gemma2-9b-it",
]

DEFAULT_OLLAMA_MODELS = [
    "minimax-m2.5:cloud",
    "minimax-m2:cloud",
    "qwen3:8b",
    "llama3.2:1b",
]

GEMINI_LIST_SKIP_RE = re.compile(
    r"(tts|image|embedding|aqa|vision|exp-|experimental|preview-tts|nano-banana)",
    re.I,
)

GROQ_LIST_SKIP_RE = re.compile(r"(whisper|distil|guard|prompt)", re.I)

OLLAMA_LIST_SKIP_RE = re.compile(r"(embed|bge-|nomic-embed|mxbai-embed)", re.I)

DEFAULT_CHAIN: list[tuple[str, str]] = [
    *(( "gemini", mid) for mid in DEFAULT_GEMINI_MODELS),
    ("groq", "llama-3.3-70b-versatile"),
    ("groq", "llama-3.1-8b-instant"),
    ("ollama", "minimax-m2.5:cloud"),
    ("ollama", "minimax-m2:cloud"),
    ("ollama", "qwen3:8b"),
    ("ollama", "llama3.2:1b"),
]

KNOWN_GEMINI = set(DEFAULT_GEMINI_MODELS) | {"gemini-3.5-flash", "gemini-flash-latest", "gemini-pro-latest"}

GEMINI_MODEL_ALIASES = {
    "gemini-pro": "gemini-pro-latest",
    "gemini-flash": "gemini-flash-latest",
}

_GEMINI_LIVE_CACHE: tuple[float, list[str]] | None = None
_GEMINI_LIVE_LOCK = threading.Lock()
_GEMINI_LIVE_TTL = 600.0

_GROQ_LIVE_CACHE: tuple[float, list[str]] | None = None
_GROQ_LIVE_LOCK = threading.Lock()
_GROQ_LIVE_TTL = 600.0

_OLLAMA_LIVE_CACHE: tuple[float, list[str]] | None = None
_OLLAMA_LIVE_LOCK = threading.Lock()
_OLLAMA_LIVE_TTL = 120.0

TASK_ALIASES = {
    "default": "default",
    "route": "route",
    "routing": "route",
    "summarize": "summarize",
    "summary": "summarize",
    "media": "summarize",
    "chat": "chat",
    "research": "research",
    "youtube": "research",
    "agent": "agent",
    "pdf": "pdf",
    "doc": "pdf",
    "predictions": "predictions",
    "prediction": "predictions",
    "stock": "predictions",
    "skill": "agent",
    "talk": "chat",
    "ask": "chat",
    "compose_video": "compose_video",
}


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _truthy(name: str, default: str = "1") -> bool:
    return env(name, default).lower() in {"1", "true", "yes", "on"}


def normalize_task(task: str | None) -> str:
    raw = (task or env("LLM_TASK") or "default").strip().lower()
    return TASK_ALIASES.get(raw, raw or "default")


@dataclass
class CompletionResult:
    text: str = ""
    provider: str = ""
    model_id: str = ""
    error: str = ""
    attempts: int = 0


@dataclass
class ExhaustionStore:
    """Session-scoped provider/model exhaustion (shared across skills)."""

    _exhausted: set[tuple[str, str]] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def mark(self, provider: str, model_id: str, exc: Exception) -> None:
        msg = str(exc).lower()
        if not is_retryable_error(msg):
            return
        provider = provider.lower()
        with self._lock:
            self._exhausted.add((provider, model_id))
            if provider == "gemini" and any(
                x in msg for x in ("free_tier", "quota exceeded", "resource_exhausted", "429")
            ):
                quota_models = _gemini_models_in_error(msg)
                if quota_models:
                    for mid in quota_models:
                        self._exhausted.add(("gemini", normalize_gemini_model(mid)))
                elif "perproject" in msg or "per day" in msg or "per minute" in msg:
                    for mid in gemini_model_ids(include_live=False):
                        self._exhausted.add(("gemini", mid))
            if provider == "groq" and any(
                x in msg for x in ("429", "rate limit", "quota", "resource_exhausted", "tokens per day")
            ):
                if any(x in msg for x in ("organization", "account", "org ", "daily token")):
                    for mid in groq_model_ids(include_live=False):
                        self._exhausted.add(("groq", mid))
                else:
                    self._exhausted.add(("groq", model_id))
            if provider == "groq" and "invalid api key" in msg:
                for mid in groq_model_ids(include_live=False):
                    self._exhausted.add(("groq", mid))
            if provider == "groq" and any(
                x in msg for x in ("decommissioned", "model_decommissioned", "model_not_found")
            ):
                self._exhausted.add(("groq", model_id))
                dep = normalize_groq_model(model_id)
                if dep != model_id:
                    self._exhausted.add(("groq", dep))
            if provider == "ollama" and any(
                x in msg for x in ("model_not_found", "not found", "404", "does not exist", "unknown model")
            ):
                self._exhausted.add(("ollama", model_id))

    def exhausted(self, provider: str, model_id: str) -> bool:
        with self._lock:
            return (provider.lower(), model_id) in self._exhausted

    def reset(self) -> None:
        with self._lock:
            self._exhausted.clear()


EXHAUSTION = ExhaustionStore()
_LAST_MODEL: tuple[str, str] | None = None
_LAST_ERROR: str = ""


def is_retryable_error(msg: str) -> bool:
    low = msg.lower()
    return any(
        x in low
        for x in (
            "429",
            "404",
            "not_found",
            "not found",
            "resource_exhausted",
            "quota exceeded",
            "rate limit",
            "invalid api key",
            "invalid_api_key",
            "api_key_invalid",
            "connection refused",
            "timed out",
            "timeout",
            "503",
            "502",
            "500",
            "401",
            "403",
            "unauthorized",
            "permission denied",
            "invalid model",
            "model_not_found",
            "model_decommissioned",
            "decommissioned",
        )
    )


def infer_provider_from_model(model_id: str) -> str | None:
    """Guess provider slug from a bare model id (no provider prefix)."""
    mid = (model_id or "").strip()
    if not mid:
        return None
    low = mid.lower()
    if low.startswith("gemini-"):
        return "gemini"
    if low.startswith(("gpt-", "o1", "o3", "chatgpt")):
        return "openai"
    if low.startswith("claude-"):
        return "anthropic"
    if low.startswith("grok-"):
        return "xai"
    if low.startswith("deepseek-"):
        return "deepseek"
    if low.startswith(("moonshot-", "kimi-")):
        return "moonshot"
    if low.startswith("glm-"):
        return "zai"
    if low.startswith(("minimax-", "abab")):
        return "minimax"
    if low.startswith("venice-"):
        return "venice"
    if low.startswith("mistral-") or low.startswith("codestral"):
        return "mistral"
    if low.startswith("command-"):
        return "cohere"
    if low.startswith("sonar"):
        return "perplexity"
    if low.startswith("accounts/fireworks/"):
        return "fireworks"
    if "/" in mid and not mid.startswith(("http://", "https://")):
        pref = (env("AI_PREFERRED_PROVIDER") or env("LLM_PROVIDER")).lower()
        if pref in {"together", "fireworks", "huggingface", "hf", "openrouter"}:
            return "huggingface" if pref == "hf" else pref
        return "openrouter"
    if ":" in mid or low.startswith(("qwen", "llama3", "minimax-m", "mistral", "phi")):
        return "ollama"
    if low.startswith(("llama-", "llama3", "gemma", "mixtral")):
        return "groq"
    pref = (env("AI_PREFERRED_PROVIDER") or env("LLM_PROVIDER")).lower()
    return pref or None


def parse_chain(raw: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        provider = ""
        model_id = ""
        if ":" in part and not part.lower().startswith(("http:", "https:")):
            head, _, tail = part.partition(":")
            if head.strip().lower() in {
                "gemini",
                "groq",
                "ollama",
                "openai",
                "anthropic",
                "vllm",
                "vllm-cloud",
                "xai",
                "deepseek",
                "moonshot",
                "zai",
                "minimax",
                "venice",
                "bedrock",
                "azure",
                "openrouter",
                "litellm",
                "lmstudio",
                "mistral",
                "cohere",
                "together",
                "fireworks",
                "perplexity",
                "huggingface",
                "hf",
            }:
                provider, model_id = head, tail
            else:
                inferred = infer_provider_from_model(part)
                if inferred:
                    out.append((inferred, part.strip()))
                continue
        elif "/" in part:
            provider, model_id = part.split("/", 1)
        else:
            inferred = infer_provider_from_model(part)
            if inferred:
                out.append((inferred, part.strip()))
            continue
        provider = provider.strip().lower()
        model_id = model_id.strip()
        if provider and model_id:
            out.append((provider, model_id))
    return out


def _dedupe_chain(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for provider, model_id in entries:
        key = (provider.lower(), model_id)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _prepend_chain(head: list[tuple[str, str]], tail: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return _dedupe_chain(head + tail)


def _explicit_fallback_chain(task: str) -> list[tuple[str, str]] | None:
    """Full chain override from env (task-specific beats global)."""
    task_key = normalize_task(task).upper()
    for env_name in (f"LLM_FALLBACK_{task_key}", "LLM_FALLBACK", "LLM_FALLBACK_CHAIN"):
        explicit = parse_chain(env(env_name))
        if explicit:
            return explicit
    return None


_SKILL_MODELS_CACHE: tuple[str, float, dict[str, list[tuple[str, str]]]] | None = None
_SKILL_MODELS_LOCK = threading.Lock()


def _parse_skill_model_value(raw: Any) -> list[tuple[str, str]]:
    if isinstance(raw, str):
        return parse_chain(raw)
    if isinstance(raw, list):
        out: list[tuple[str, str]] = []
        for item in raw:
            if isinstance(item, str):
                out.extend(parse_chain(item))
            elif isinstance(item, dict):
                provider = str(item.get("provider") or item.get("slug") or "").strip().lower()
                model_id = str(item.get("model") or item.get("model_id") or item.get("id") or "").strip()
                if provider and model_id:
                    out.append((provider, model_id))
        return out
    if isinstance(raw, dict):
        provider = str(raw.get("provider") or raw.get("slug") or "").strip().lower()
        model_id = str(raw.get("model") or raw.get("model_id") or raw.get("id") or "").strip()
        if provider and model_id:
            return [(provider, model_id)]
    return []


def _skill_models_from_data(data: Any) -> dict[str, list[tuple[str, str]]]:
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[tuple[str, str]]] = {}
    for key, value in data.items():
        key_raw = str(key).strip()
        if not key_raw or key_raw.startswith("_"):
            continue
        key_norm = key_raw.lower().replace("-", "_")
        entries = _parse_skill_model_value(value)
        if entries:
            out[key_norm] = entries
    return out


def _load_skill_models_inline() -> dict[str, list[tuple[str, str]]]:
    """Inline JSON map from SKILL_MODELS env (e.g. {\"chat\":\"gemini-2.5-flash\"})."""
    raw = env("SKILL_MODELS")
    if not raw or not raw.lstrip().startswith(("{", "[")):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return _skill_models_from_data(data)


def _load_skill_models_config() -> dict[str, list[tuple[str, str]]]:
    """Load per-task models from SKILL_MODELS JSON and/or LLM_SKILL_MODELS file."""
    global _SKILL_MODELS_CACHE

    inline = _load_skill_models_inline()
    path_raw = env("LLM_SKILL_MODELS")
    if not path_raw:
        return inline

    path = Path(path_raw).expanduser()
    if not path.is_file():
        return inline

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return inline

    cache_key = f"{env('SKILL_MODELS')}|{path}"
    with _SKILL_MODELS_LOCK:
        if _SKILL_MODELS_CACHE and _SKILL_MODELS_CACHE[0] == cache_key and _SKILL_MODELS_CACHE[1] == mtime:
            return dict(_SKILL_MODELS_CACHE[2])

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return inline

    data: Any = None
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception:
            return inline
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return inline

    file_map = _skill_models_from_data(data)
    profiles = data.get("_profiles") if isinstance(data, dict) else None
    if isinstance(profiles, dict):
        for profile_key, value in profiles.items():
            key_norm = str(profile_key).strip().lower().replace("-", "_")
            entries = _parse_skill_model_value(value)
            if key_norm and entries:
                file_map[key_norm] = _dedupe_chain(file_map.get(key_norm, []) + entries)

    merged = dict(inline)
    for task_key, entries in file_map.items():
        merged[task_key] = _dedupe_chain(merged.get(task_key, []) + entries)

    with _SKILL_MODELS_LOCK:
        _SKILL_MODELS_CACHE = (cache_key, mtime, dict(merged))
    return merged


def _route_model_entries() -> list[tuple[str, str]]:
    """Preferred model for NL routing (task=route). ROUTING_MODEL is an alias."""
    raw = env("ROUTE_MODEL") or env("ROUTING_MODEL")
    return parse_chain(raw)


def _active_skill_name() -> str:
    try:
        from arka.llm.skill_profiles import normalize_skill_name

        return normalize_skill_name(env("ARKA_SKILL"))
    except ImportError:
        return normalize_skill_name_local(env("ARKA_SKILL"))


def normalize_skill_name_local(skill: str | None) -> str:
    raw = (skill or "").strip().lower()
    if not raw:
        return ""
    return raw.replace("-", "_")


def resolve_llm_context(*, task: str | None = None, skill: str | None = None) -> tuple[str, str]:
    """Return (task_profile, skill_name) for model chain resolution."""
    try:
        from arka.llm.skill_profiles import normalize_skill_name, skill_task_profile
    except ImportError:
        skill_key = normalize_skill_name_local(skill) or normalize_skill_name_local(env("ARKA_SKILL"))
        if task:
            return normalize_task(task), skill_key
        if skill_key:
            return "default", skill_key
        return normalize_task(None), ""

    skill_key = normalize_skill_name(skill) or _active_skill_name()
    if task:
        return normalize_task(task), skill_key
    if skill_key:
        return skill_task_profile(skill_key), skill_key
    return normalize_task(None), ""


def _skill_model_entries(task: str, *, skill: str | None = None) -> list[tuple[str, str]]:
    """Per-skill and per-task model guidance — prepended to the auto-built chain.

    Precedence (first wins at attempt time; all are prepended in this order):
      1. SKILL_MODEL_<SKILL> env (e.g. SKILL_MODEL_WEB_ANSWER)
      2. SKILL_MODELS / LLM_SKILL_MODELS map entry for this skill name
      3. Profile default from llm-skill-models.json "_profiles" for the task profile
      4. SKILL_MODEL_<TASK> env
      5. SKILL_MODELS / LLM_SKILL_MODELS map entries for task profile
      6. ROUTE_MODEL / ROUTING_MODEL (route task only)
    """
    task_key = normalize_task(task)
    task_upper = task_key.upper()
    skill_key = normalize_skill_name_local(skill) or _active_skill_name()
    entries: list[tuple[str, str]] = []

    if skill_key:
        skill_upper = skill_key.upper()
        entries.extend(parse_chain(env(f"SKILL_MODEL_{skill_upper}")))

    file_map = _load_skill_models_config()
    if skill_key:
        entries.extend(file_map.get(skill_key, []))

    entries.extend(parse_chain(env(f"SKILL_MODEL_{task_upper}")))
    entries.extend(file_map.get(task_key, []))

    if task_key == "route":
        entries.extend(_route_model_entries())

    return _dedupe_chain(entries)


def _guidance_entries() -> list[tuple[str, str]]:
    return parse_chain(env("LLM_FALLBACK_GUIDANCE"))


def normalize_gemini_model(model_id: str) -> str:
    mid = (model_id or "").strip()
    if not mid:
        return mid
    aliased = GEMINI_MODEL_ALIASES.get(mid, mid)
    if aliased in KNOWN_GEMINI or aliased.startswith("gemini-"):
        return aliased
    return mid


def _gemini_models_in_error(msg: str) -> list[str]:
    found = re.findall(r"'model':\s*'([^']+)'", msg, flags=re.I)
    found += re.findall(r'"model":\s*"([^"]+)"', msg, flags=re.I)
    found += re.findall(r"model:\s*(gemini[\w.-]+)", msg, flags=re.I)
    out: list[str] = []
    for mid in found:
        mid = mid.strip()
        if mid.startswith("gemini-") and mid not in out:
            out.append(mid)
    return out


def _gemini_list_enabled() -> bool:
    if env("GEMINI_LIST") in {"0", "false", "no", "off"}:
        return False
    if env("GEMINI_LIST") in {"1", "true", "yes", "on"}:
        return bool(_ensure_google_key())
    return bool(_ensure_google_key())


def _rank_gemini_model(model_id: str) -> tuple[int, int, str]:
    """Lower sorts first: flash before pro, newer versions first."""
    mid = model_id.lower()
    kind = 0 if "flash" in mid else (1 if "pro" in mid else 2)
    version = 0
    for token, score in (
        ("3.1", 31),
        ("3.", 30),
        ("2.5", 25),
        ("2.0", 20),
        ("1.5", 15),
    ):
        if token in mid:
            version = score
            break
    if mid.endswith("-latest"):
        version += 1
    return (kind, -version, mid)


def _filter_gemini_chat_models(model_ids: list[str]) -> list[str]:
    out: list[str] = []
    for mid in model_ids:
        if not mid.startswith("gemini-"):
            continue
        if GEMINI_LIST_SKIP_RE.search(mid):
            continue
        if mid not in out:
            out.append(mid)
    out.sort(key=_rank_gemini_model)
    return out


def fetch_gemini_models_live(*, force: bool = False) -> list[str]:
    """List Gemini models that support generateContent (cached ~10 min)."""
    global _GEMINI_LIVE_CACHE

    if not _gemini_list_enabled():
        return []

    keys = iter_provider_keys("gemini")
    if not keys:
        return []

    now = time.time()
    with _GEMINI_LIVE_LOCK:
        if not force and _GEMINI_LIVE_CACHE and now - _GEMINI_LIVE_CACHE[0] < _GEMINI_LIVE_TTL:
            return list(_GEMINI_LIVE_CACHE[1])

    data = None
    for key in keys:
        os.environ["GEMINI_API_KEY"] = key
        os.environ["GOOGLE_API_KEY"] = key
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            break
        except urllib.error.HTTPError as exc:
            if is_key_retryable(str(exc)) and key != keys[-1]:
                continue
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            if key != keys[-1]:
                continue
    if data is None:
        with _GEMINI_LIVE_LOCK:
            if _GEMINI_LIVE_CACHE:
                return list(_GEMINI_LIVE_CACHE[1])
        return []

    models: list[str] = []
    for item in data.get("models") or []:
        if not isinstance(item, dict):
            continue
        methods = item.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        name = str(item.get("name") or "")
        if name.startswith("models/"):
            name = name.split("/", 1)[1]
        if name:
            models.append(name)

    models = _filter_gemini_chat_models(models)
    with _GEMINI_LIVE_LOCK:
        _GEMINI_LIVE_CACHE = (now, models)
    return list(models)


def gemini_model_ids(*, include_live: bool = True) -> list[str]:
    explicit = [normalize_gemini_model(m.strip()) for m in env("GEMINI_MODELS").split(",") if m.strip()]
    raw = [
        env("CHAT_MODEL"),
        env("AI_PREFERRED_MODEL"),
        env("LLM_MODEL"),
    ]
    raw.extend(explicit or DEFAULT_GEMINI_MODELS)
    if include_live and _gemini_list_enabled():
        raw.extend(fetch_gemini_models_live())
    out: list[str] = []
    for model in raw:
        model = normalize_gemini_model(model)
        if not model or not model.startswith("gemini-"):
            continue
        if GEMINI_LIST_SKIP_RE.search(model):
            continue
        if model not in out:
            out.append(model)
    if not out:
        return list(DEFAULT_GEMINI_MODELS)
    preferred = {normalize_gemini_model(m) for m in raw[:3] if m}
    head = [m for m in out if m in preferred]
    tail = sorted([m for m in out if m not in preferred], key=_rank_gemini_model)
    merged: list[str] = []
    for model in head + tail:
        if model not in merged:
            merged.append(model)
    return merged


GROQ_MODEL_ALIASES = {
    "llama3-8b-8192": "llama-3.1-8b-instant",
    "llama3-70b-8192": "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile": "llama-3.3-70b-versatile",
    "mixtral-8x7b-32768": "llama-3.3-70b-versatile",
    "gemma2-9b-it": "llama-3.1-8b-instant",
}


def normalize_groq_model(model_id: str) -> str:
    mid = (model_id or "").strip()
    return GROQ_MODEL_ALIASES.get(mid, mid)


def _groq_list_enabled() -> bool:
    if env("GROQ_LIST") in {"0", "false", "no", "off"}:
        return False
    return bool(provider_has_keys("groq") or env("GROQ_API_KEY"))


def _rank_groq_model(model_id: str) -> tuple[int, str]:
    mid = model_id.lower()
    tier = 0 if "70b" in mid or "405b" in mid else (1 if "8b" in mid or "9b" in mid else 2)
    if "versatile" in mid or "specdec" in mid:
        tier -= 1
    return (tier, mid)


def fetch_groq_models_live(*, force: bool = False) -> list[str]:
    """List Groq chat models from OpenAI-compatible API (cached ~10 min)."""
    global _GROQ_LIVE_CACHE

    if not _groq_list_enabled():
        return []

    keys = iter_provider_keys("groq")
    if not keys:
        return []

    now = time.time()
    with _GROQ_LIVE_LOCK:
        if not force and _GROQ_LIVE_CACHE and now - _GROQ_LIVE_CACHE[0] < _GROQ_LIVE_TTL:
            return list(_GROQ_LIVE_CACHE[1])

    data = None
    for key in keys:
        try:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            break
        except urllib.error.HTTPError as exc:
            if is_key_retryable(str(exc)) and key != keys[-1]:
                continue
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            if key != keys[-1]:
                continue

    if data is None:
        with _GROQ_LIVE_LOCK:
            if _GROQ_LIVE_CACHE:
                return list(_GROQ_LIVE_CACHE[1])
        return []

    models: list[str] = []
    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid or GROQ_LIST_SKIP_RE.search(mid):
            continue
        mid = normalize_groq_model(mid)
        if mid not in models:
            models.append(mid)
    models.sort(key=_rank_groq_model)

    with _GROQ_LIVE_LOCK:
        _GROQ_LIVE_CACHE = (now, models)
    return list(models)


def groq_model_ids(*, include_live: bool = True) -> list[str]:
    pref_provider = (env("AI_PREFERRED_PROVIDER") or env("LLM_PROVIDER")).lower()
    explicit = [
        normalize_groq_model(m.strip())
        for m in env("GROQ_MODELS").split(",")
        if m.strip()
    ]
    raw = [
        normalize_groq_model(env("GROQ_MODEL")),
        env("AI_PREFERRED_MODEL") if pref_provider == "groq" else "",
        env("LLM_MODEL") if pref_provider == "groq" else "",
    ]
    raw.extend(explicit or DEFAULT_GROQ_MODELS)
    if include_live and _groq_list_enabled():
        raw.extend(fetch_groq_models_live())
    out: list[str] = []
    for model in raw:
        model = normalize_groq_model(model)
        if not model or model.startswith("gemini-"):
            continue
        if model not in out:
            out.append(model)
    if not out:
        return list(DEFAULT_GROQ_MODELS)
    preferred = {normalize_groq_model(m) for m in raw[:4] if m}
    head = [m for m in out if m in preferred]
    tail = sorted([m for m in out if m not in preferred], key=_rank_groq_model)
    merged: list[str] = []
    for model in head + tail:
        if model not in merged:
            merged.append(model)
    return merged


def _ollama_list_enabled() -> bool:
    if env("OLLAMA_LIST") in {"0", "false", "no", "off"}:
        return False
    if env("OLLAMA_LIST") in {"1", "true", "yes", "on"}:
        return _ollama_reachable()
    return _ollama_reachable()


def _rank_ollama_model(model_id: str) -> tuple[int, str]:
    mid = model_id.lower()
    tier = 0 if ":cloud" in mid else 1
    if mid.startswith("minimax"):
        tier = 0
    return (tier, mid)


def fetch_ollama_models_live(*, force: bool = False) -> list[str]:
    """List installed Ollama models from /api/tags (cached ~2 min)."""
    global _OLLAMA_LIVE_CACHE

    if not _ollama_list_enabled():
        return []

    now = time.time()
    with _OLLAMA_LIVE_LOCK:
        if not force and _OLLAMA_LIVE_CACHE and now - _OLLAMA_LIVE_CACHE[0] < _OLLAMA_LIVE_TTL:
            return list(_OLLAMA_LIVE_CACHE[1])

    try:
        req = urllib.request.Request(f"{_ollama_host()}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        with _OLLAMA_LIVE_LOCK:
            if _OLLAMA_LIVE_CACHE:
                return list(_OLLAMA_LIVE_CACHE[1])
        return []

    models: list[str] = []
    for item in data.get("models") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or OLLAMA_LIST_SKIP_RE.search(name):
            continue
        if name.startswith("gemini-"):
            continue
        if name not in models:
            models.append(name)
    models.sort(key=_rank_ollama_model)

    with _OLLAMA_LIVE_LOCK:
        _OLLAMA_LIVE_CACHE = (now, models)
    return list(models)


def ollama_model_ids(*, include_live: bool = True) -> list[str]:
    pref_provider = (env("AI_PREFERRED_PROVIDER") or env("LLM_PROVIDER")).lower()
    pref_model = env("AI_PREFERRED_MODEL") or env("LLM_MODEL")
    explicit = [m.strip() for m in env("OLLAMA_MODELS").split(",") if m.strip()]
    raw = [
        env("OLLAMA_CHAT_MODEL"),
        pref_model if pref_provider == "ollama" else "",
        env("LLM_MODEL") if pref_provider == "ollama" else "",
    ]
    raw.extend(explicit or DEFAULT_OLLAMA_MODELS)
    if include_live and _ollama_list_enabled():
        raw.extend(fetch_ollama_models_live())
    out: list[str] = []
    for model in raw:
        if not model or model.startswith("gemini-"):
            continue
        if model not in out:
            out.append(model)
    if not out:
        return list(DEFAULT_OLLAMA_MODELS)
    preferred = {m for m in raw[:4] if m}
    head = [m for m in out if m in preferred]
    tail = sorted([m for m in out if m not in preferred], key=_rank_ollama_model)
    merged: list[str] = []
    for model in head + tail:
        if model not in merged:
            merged.append(model)
    return merged


def _has_groq() -> bool:
    return bool(provider_has_keys("groq") or env("GROQ_API_KEY"))


def _has_gemini() -> bool:
    return bool(_ensure_google_key())


def _expand_provider_models(
    add,
    pref_provider: str,
    *,
    provider: str,
    model_ids: list[str],
) -> None:
    """Add full Gemini list when preferred or no preference is set."""
    if pref_provider == provider or not pref_provider:
        for model_id in model_ids:
            add(provider, model_id)


def build_default_chain(*, task: str = "default", skill: str | None = None) -> list[tuple[str, str]]:
    explicit = _explicit_fallback_chain(task)
    if explicit:
        return explicit

    pref_provider = (env("AI_PREFERRED_PROVIDER") or env("LLM_PROVIDER")).lower()
    pref_model = env("AI_PREFERRED_MODEL") or env("LLM_MODEL")

    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []

    def add(provider: str, model_id: str) -> None:
        key = (provider.lower(), model_id)
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    if pref_provider and pref_model:
        if pref_provider == "gemini":
            add(pref_provider, normalize_gemini_model(pref_model))
        elif pref_provider == "groq":
            mid = normalize_groq_model(pref_model)
            if mid and not mid.startswith("gemini-"):
                add(pref_provider, mid)
        elif pref_provider == "ollama":
            if not pref_model.startswith("gemini-"):
                add(pref_provider, pref_model)
        else:
            add(pref_provider, pref_model)

    if env("VLLM_CLOUD_URL") or env("VLLM_CLOUD_API_URL"):
        cloud_model = env("VLLM_CLOUD_MODEL") or "default"
        add("vllm-cloud", cloud_model)

    explicit_vllm = vllm_explicitly_configured()
    apply_vllm_defaults()
    if explicit_vllm or is_reachable("vllm"):
        add("vllm", env("VLLM_MODEL") or "default")

    _expand_provider_models(add, pref_provider, provider="gemini", model_ids=gemini_model_ids())
    if _has_groq():
        for model_id in groq_model_ids():
            add("groq", model_id)
    for model_id in ollama_model_ids():
        add("ollama", model_id)

    for spec in provider_specs():
        if spec.slug in {"gemini", "groq", "ollama", "vllm", "vllm-cloud"}:
            continue
        if not provider_available(spec.slug):
            continue
        for model_id in provider_model_ids(spec):
            add(spec.slug, model_id)

    for provider, model_id in DEFAULT_CHAIN:
        add(provider, model_id)

    if pref_provider:
        pref_first = [x for x in ordered if x[0] == pref_provider]
        pref_rest = [x for x in ordered if x[0] != pref_provider]
        ordered = pref_first + pref_rest

    guidance = _guidance_entries()
    skill_models = _skill_model_entries(task, skill=skill)
    if skill_models or guidance:
        ordered = _prepend_chain(skill_models + guidance, ordered)

    return ordered


def _ensure_google_key() -> str:
    apply_provider_key("gemini")
    return (
        (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    )


def _ollama_host() -> str:
    host = env("OLLAMA_HOST", "127.0.0.1:11434").replace("0.0.0.0", "127.0.0.1")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host.rstrip("/")


def _ollama_reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(f"{_ollama_host()}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _vllm_base_url() -> str:
    base = env("VLLM_API_URL")
    if not base:
        host = env("VLLM_HOST", "127.0.0.1:8000")
        base = f"http://{host}"
    if not base.startswith("http"):
        base = f"http://{base}"
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _vllm_cloud_base_url() -> str:
    spec = get_provider("vllm-cloud")
    base = provider_base_url(spec) if spec else ""
    if not base:
        return ""
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _inference_backend(provider: str) -> str:
    provider = provider.lower()
    if provider == "vllm-cloud":
        return "vllm-cloud"
    if provider == "vllm":
        return "vllm"
    return provider


def provider_available(provider: str) -> bool:
    return provider_available_with_servers(provider)


def build_model(provider: str, model_id: str, temperature: float, *, session: LlmServerSession | None = None) -> Any | None:
    provider = provider.lower()
    if provider in LOCAL_PROVIDERS:
        if session is not None:
            if not session.prepare(provider):
                return None
        elif not provider_available(provider):
            return None
    elif not provider_available(provider):
        return None

    if provider == "gemini":
        from agno.models.google import Gemini

        _ensure_google_key()
        return Gemini(id=normalize_gemini_model(model_id), temperature=temperature)

    if provider == "groq":
        from agno.models.groq import Groq

        apply_provider_key("groq")
        return Groq(id=normalize_groq_model(model_id), temperature=temperature)

    if provider == "ollama":
        from agno.models.ollama import Ollama

        mid = model_id or env("OLLAMA_CHAT_MODEL") or "minimax-m2.5:cloud"
        if mid.startswith("gemini-"):
            mid = "minimax-m2.5:cloud"
        apply_provider_key("ollama")
        return Ollama(
            id=mid,
            host=_ollama_host(),
            api_key=env("OLLAMA_API_KEY") or None,
            options={"temperature": temperature},
        )

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        apply_provider_key("openai")
        return OpenAIChat(id=model_id, temperature=temperature)

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        apply_provider_key("anthropic")
        return Claude(id=model_id, temperature=temperature)

    if provider == "vllm":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(
            id=model_id or "default",
            base_url=_vllm_base_url(),
            api_key=env("VLLM_API_KEY") or "EMPTY",
            temperature=temperature,
        )

    if provider == "vllm-cloud":
        from agno.models.openai import OpenAIChat

        apply_provider_key("vllm-cloud")
        base = _vllm_cloud_base_url()
        if not base:
            return None
        spec = get_provider("vllm-cloud")
        mid = model_id or env("VLLM_CLOUD_MODEL") or (spec.default_model if spec else "default")
        api_key = (provider_api_key(spec) if spec else "") or env("VLLM_CLOUD_API_KEY") or "EMPTY"
        return OpenAIChat(
            id=mid,
            base_url=base,
            api_key=api_key,
            temperature=temperature,
        )

    spec = get_provider(provider)
    if spec and spec.kind in {"openai_compatible", "local_openai"}:
        from agno.models.openai import OpenAIChat

        apply_provider_key(provider)
        base = provider_base_url(spec)
        if not base:
            return None
        api_key = provider_api_key(spec) or env("OPENAI_API_KEY") or "EMPTY"
        mid = model_id or spec.default_model
        return OpenAIChat(
            id=mid,
            base_url=base,
            api_key=api_key,
            temperature=temperature,
        )

    return None


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z0-9]*\n*", "", text)
    text = re.sub(r"\n*```$", "", text)
    return text.strip()


def _looks_like_error(text: str) -> bool:
    if not text:
        return True
    stripped = text.strip()
    if stripped.startswith("{") and '"error"' in stripped:
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "error" in data:
                return True
        except json.JSONDecodeError:
            pass
    low = stripped.lower()
    if any(
        x in low
        for x in (
            "could not generate",
            "resource_exhausted",
            "unauthorized",
            "permission denied",
            "invalid api key",
            "quota exceeded",
            "rate limit",
            "model_not_found",
            "not found for api",
            "not found (status code",
            "status code: 404",
            "status code: 401",
            "status code: 403",
        )
    ):
        return True
    if re.search(r"\b401\b", stripped) or re.search(r"\b403\b", stripped):
        return True
    return False


@contextmanager
def _quiet_llm_logs() -> Iterator[None]:
    if env("LLM_VERBOSE") in {"1", "true", "yes"}:
        yield
        return
    prev_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    agno_levels: list[tuple[Any, int]] = []
    try:
        from agno.utils import log as agno_log

        for lg in (agno_log.logger, agno_log.agent_logger, agno_log.team_logger, agno_log.workflow_logger):
            agno_levels.append((lg, lg.level))
            lg.setLevel(logging.CRITICAL + 1)
    except ImportError:
        pass
    try:
        yield
    finally:
        logging.disable(prev_disable)
        for lg, level in agno_levels:
            lg.setLevel(level)


@dataclass
class LlmFallbackEngine:
    """Try providers/models in order until one succeeds."""

    task: str = "default"
    skill: str = ""
    chain: list[tuple[str, str]] | None = None
    store: ExhaustionStore = field(default_factory=lambda: EXHAUSTION)

    def candidates(self) -> list[tuple[str, str]]:
        if self.chain:
            return list(self.chain)
        return build_default_chain(task=self.task, skill=self.skill or None)

    def complete(self, system: str, user: str, *, temperature: float = 0.2) -> CompletionResult:
        from agno.agent import Agent

        global _LAST_MODEL, _LAST_ERROR

        if not _truthy("LLM_AUTO_FALLBACK", "1") and self.chain is None:
            chain = self.candidates()[:1]
        else:
            chain = self.candidates()

        last_error = ""
        verbose = env("LLM_VERBOSE") in {"1", "true", "yes"}
        notify = _truthy("LLM_FALLBACK_NOTIFY", "0")
        attempts = 0
        tried: list[str] = []

        session = LlmServerSession()
        with _quiet_llm_logs():
            try:
                for provider, model_id in chain:
                    if self.store.exhausted(provider, model_id):
                        continue
                    key_retry = True
                    while key_retry:
                        key_retry = False
                        apply_provider_key(provider)
                        model = build_model(provider, model_id, temperature, session=session)
                        if model is None:
                            break
                        attempts += 1
                        label = f"{provider}/{model_id}"
                        kr = key_rotation_label(provider)
                        if kr:
                            label = f"{label} ({kr})"
                        tried.append(label)
                        try:
                            from arka.telemetry import (
                                llm_http_span_attributes,
                                mark_error,
                                mark_ok,
                                parse_http_status_code,
                                set_http_span_attributes,
                                span as trace_span,
                            )
                        except ImportError:
                            trace_span = None  # type: ignore[assignment,misc]
                            llm_http_span_attributes = None  # type: ignore[assignment,misc]
                            parse_http_status_code = None  # type: ignore[assignment,misc]
                            set_http_span_attributes = None  # type: ignore[assignment,misc]
                        from contextlib import nullcontext

                        attempt_attrs = {
                            "gen_ai.provider.name": provider,
                            "gen_ai.request.model": model_id,
                            "arka.task": normalize_task(self.task),
                            "arka.llm.attempt_index": attempts,
                            **(
                                {"arka.inference.backend": _inference_backend(provider)}
                                if provider
                                in {"vllm", "vllm-cloud", "ollama", "lmstudio", "litellm"}
                                else {}
                            ),
                        }
                        if llm_http_span_attributes is not None:
                            attempt_attrs.update(llm_http_span_attributes(provider))

                        attempt_mgr = (
                            trace_span("arka.llm.attempt", attributes=attempt_attrs)
                            if trace_span is not None
                            else nullcontext()
                        )
                        try:
                            with attempt_mgr as attempt_span:
                                if verbose:
                                    print(
                                        f"arka_llm: trying {label} (task={normalize_task(self.task)})",
                                        file=sys.stderr,
                                    )
                                attempt_start = time.perf_counter()
                                agent = Agent(model=model, instructions=system, markdown=False)
                                run = agent.run(user)
                                text = getattr(run, "content", None)
                                if text is None:
                                    text = str(run)
                                text = _strip_fences(str(text).strip())
                                if text and not _looks_like_error(text):
                                    _LAST_MODEL = (provider, model_id)
                                    _LAST_ERROR = ""
                                    if trace_span is not None:
                                        try:
                                            from arka.telemetry.tracing import set_timing_attrs

                                            set_timing_attrs(
                                                attempt_span,
                                                start=attempt_start,
                                                streaming=False,
                                            )
                                        except ImportError:
                                            pass
                                        attempt_span.set_attribute("arka.llm.completion_chars", len(text))
                                        try:
                                            from arka.telemetry.llm_obs import apply_run_telemetry

                                            apply_run_telemetry(
                                                attempt_span,
                                                run,
                                                provider=provider,
                                                model_id=model_id,
                                                task=normalize_task(self.task),
                                                label=label,
                                            )
                                        except ImportError:
                                            try:
                                                from arka.telemetry.logs import emit_log
                                                from arka.telemetry.metrics import record_llm_attempt

                                                record_llm_attempt(
                                                    provider=provider,
                                                    model=model_id,
                                                    success=True,
                                                    backend=_inference_backend(provider),
                                                )
                                                emit_log(
                                                    f"llm ok {label}",
                                                    level="info",
                                                    attributes={
                                                        "gen_ai.provider.name": provider,
                                                        "gen_ai.request.model": model_id,
                                                    },
                                                )
                                            except ImportError:
                                                pass
                                        if set_http_span_attributes is not None:
                                            set_http_span_attributes(attempt_span, status_code=200)
                                        mark_ok(attempt_span)
                                    if notify and len(tried) > 1:
                                        print(
                                            f"arka_llm: fallback ok → {label} "
                                            f"(after {len(tried) - 1} failure(s))",
                                            file=sys.stderr,
                                        )
                                    elif verbose:
                                        print(f"arka_llm: ok {label}", file=sys.stderr)
                                    return CompletionResult(
                                        text=text,
                                        provider=provider,
                                        model_id=model_id,
                                        attempts=attempts,
                                    )
                                err_text = (text or "empty response")[:300]
                                last_error = f"{label}: {err_text}"
                                if trace_span is not None:
                                    if set_http_span_attributes is not None:
                                        code = (
                                            parse_http_status_code(err_text)
                                            if parse_http_status_code is not None
                                            else None
                                        )
                                        if code is not None:
                                            set_http_span_attributes(attempt_span, status_code=code)
                                    mark_error(attempt_span, err_text)
                                if rotate_provider_key(provider, err_text):
                                    if verbose:
                                        print(
                                            f"arka_llm: rotating {provider} API key after error",
                                            file=sys.stderr,
                                        )
                                    key_retry = True
                                    continue
                                self.store.mark(provider, model_id, RuntimeError(err_text))
                                if verbose:
                                    print(f"arka_llm: fail {label}: {err_text}", file=sys.stderr)
                        except Exception as exc:
                            last_error = f"{label}: {exc}"
                            if trace_span is not None:
                                if set_http_span_attributes is not None:
                                    code = (
                                        parse_http_status_code(exc)
                                        if parse_http_status_code is not None
                                        else None
                                    )
                                    if code is not None:
                                        set_http_span_attributes(attempt_span, status_code=code)
                                mark_error(attempt_span, str(exc), exc=exc)
                            if rotate_provider_key(provider, exc):
                                if verbose:
                                    print(
                                        f"arka_llm: rotating {provider} API key after {exc}",
                                        file=sys.stderr,
                                    )
                                key_retry = True
                                continue
                            self.store.mark(provider, model_id, exc)
                            if verbose:
                                print(f"arka_llm: fail {label}: {exc}", file=sys.stderr)
            finally:
                session.close()

        _LAST_ERROR = last_error
        if last_error and verbose:
            print(f"arka_llm: all providers failed ({last_error})", file=sys.stderr)
        return CompletionResult(error=last_error, attempts=attempts)

    def stream_complete(
        self, system: str, user: str, *, temperature: float = 0.2
    ) -> Iterator[str]:
        """Yield incremental text deltas from the first successful provider."""
        from agno.agent import Agent

        global _LAST_MODEL, _LAST_ERROR

        if not _truthy("LLM_AUTO_FALLBACK", "1") and self.chain is None:
            chain = self.candidates()[:1]
        else:
            chain = self.candidates()

        last_error = ""
        session = LlmServerSession()
        with _quiet_llm_logs():
            try:
                for provider, model_id in chain:
                    if self.store.exhausted(provider, model_id):
                        continue
                    key_retry = True
                    while key_retry:
                        key_retry = False
                        apply_provider_key(provider)
                        model = build_model(provider, model_id, temperature, session=session)
                        if model is None:
                            break
                        try:
                            agent = Agent(model=model, instructions=system, markdown=False)
                            seen = ""
                            for event in agent.run(user, stream=True):
                                event_name = getattr(event, "event", "") or type(event).__name__
                                if event_name not in (
                                    "RunContent",
                                    "IntermediateRunContent",
                                    "ReasoningContentDelta",
                                ):
                                    continue
                                piece = getattr(event, "content", None)
                                if piece is None:
                                    piece = getattr(event, "reasoning_content", None)
                                if not piece:
                                    continue
                                text = str(piece)
                                if text.startswith(seen):
                                    delta = text[len(seen) :]
                                    seen = text
                                else:
                                    delta = text
                                    seen += text
                                if delta:
                                    yield delta
                            if seen.strip():
                                text = _strip_fences(seen.strip())
                                if text and not _looks_like_error(text):
                                    _LAST_MODEL = (provider, model_id)
                                    _LAST_ERROR = ""
                                    return
                                last_error = text[:300] if text else "empty stream response"
                                if rotate_provider_key(provider, last_error):
                                    key_retry = True
                                    continue
                            else:
                                last_error = "empty stream response"
                                if rotate_provider_key(provider, last_error):
                                    key_retry = True
                                    continue
                            self.store.mark(provider, model_id, RuntimeError(last_error))
                        except Exception as exc:
                            last_error = str(exc)
                            if rotate_provider_key(provider, exc):
                                key_retry = True
                                continue
                            self.store.mark(provider, model_id, exc)
            finally:
                session.close()

        _LAST_ERROR = last_error
        if last_error:
            yield f"[LLM error: {last_error}]"


_DEFAULT_ENGINE = LlmFallbackEngine(task="default")


def llm_complete(
    system: str,
    user: str,
    temperature: float = 0.2,
    *,
    task: str | None = None,
    skill: str | None = None,
    chain: list[tuple[str, str]] | None = None,
) -> str:
    resolved_task, resolved_skill = resolve_llm_context(task=task, skill=skill)
    if task or skill or chain:
        engine = LlmFallbackEngine(
            task=resolved_task,
            skill=resolved_skill,
            chain=chain,
        )
    else:
        engine = _DEFAULT_ENGINE
    result = engine.complete(system, user, temperature=temperature)
    return result.text


def llm_stream_complete(
    system: str,
    user: str,
    temperature: float = 0.2,
    *,
    task: str | None = None,
    skill: str | None = None,
    chain: list[tuple[str, str]] | None = None,
) -> Iterator[str]:
    resolved_task, resolved_skill = resolve_llm_context(task=task, skill=skill)
    if task or skill or chain:
        engine = LlmFallbackEngine(
            task=resolved_task,
            skill=resolved_skill,
            chain=chain,
        )
    else:
        engine = _DEFAULT_ENGINE
    yield from engine.stream_complete(system, user, temperature=temperature)


def llm_last_error() -> str:
    return _LAST_ERROR


def llm_last_model() -> tuple[str, str] | None:
    return _LAST_MODEL


def ordered_model_candidates(*, task: str | None = None, skill: str | None = None) -> list[tuple[str, str]]:
    resolved_task, resolved_skill = resolve_llm_context(task=task, skill=skill)
    return build_default_chain(task=resolved_task, skill=resolved_skill or None)


def builtin_tail_chain() -> list[tuple[str, str]]:
    """Built-in DEFAULT_CHAIN tail appended after provider discovery."""
    return list(DEFAULT_CHAIN)


def reset_llm_exhaustion() -> None:
    EXHAUSTION.reset()
    reset_key_rotators()


def model_label(*, prefer_last: bool = True, task: str | None = None, skill: str | None = None) -> str:
    if prefer_last and _LAST_MODEL:
        provider, model_id = _LAST_MODEL
        return f"{provider}/{model_id}"
    resolved_task, resolved_skill = resolve_llm_context(task=task, skill=skill)
    for provider, model_id in ordered_model_candidates(task=resolved_task, skill=resolved_skill or None):
        if not provider_available(provider):
            continue
        if EXHAUSTION.exhausted(provider, model_id):
            continue
        return f"{provider}/{model_id}"
    return ""
