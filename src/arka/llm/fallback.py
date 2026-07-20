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

DEFAULT_OPENROUTER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemini-2.0-flash-exp:free",
    "openai/gpt-4o-mini",
    "anthropic/claude-sonnet-4",
]

DEFAULT_LLM_MAX_TOKENS = 4096
SIMPLE_QUERY_MAX_TOKENS = 512
OPENROUTER_DEFAULT_MAX_TOKENS = 4096

TASK_MAX_TOKENS: dict[str, int] = {
    "route": 256,
    "chat": 4096,
    "summarize": 4096,
    "research": 8192,
    "agent": 8192,
    "pdf": 4096,
    "predictions": 4096,
    "compose_video": 4096,
    "compose_slides": 4096,
    "default": 4096,
}

OPENROUTER_MODEL_ALIASES = {
    "anthropic/claude-3.5-sonnet": "anthropic/claude-sonnet-4",
    "google/gemini-2.0-flash-001": "google/gemini-2.0-flash",
}

GEMINI_LIST_SKIP_RE = re.compile(
    r"(tts|image|embedding|aqa|vision|exp-|experimental|preview-tts|nano-banana)",
    re.I,
)

GROQ_LIST_SKIP_RE = re.compile(r"(whisper|distil|guard|prompt)", re.I)

OLLAMA_LIST_SKIP_RE = re.compile(r"(embed|bge-|nomic-embed|mxbai-embed)", re.I)
OLLAMA_VISION_SKIP_RE = re.compile(r"(?i)(llava|moondream|bakllava|minicpm-v|\bvision\b)")

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

_OPENROUTER_LIVE_CACHE: tuple[float, list[str]] | None = None
_OPENROUTER_META_CACHE: tuple[float, dict[str, dict[str, Any]]] | None = None
_OPENROUTER_LIVE_LOCK = threading.Lock()
_OPENROUTER_LIVE_TTL = 600.0

OPENROUTER_LIST_SKIP_RE = re.compile(
    r"(?i)(embed|embedding|tts|whisper|image|vision|audio|moderation|rerank)",
)
OPENROUTER_DEPRIORITIZE_RE = re.compile(
    r"(?i)(multi-agent|grok-4|grok-3|claude-opus|/o1-|/o3-|deepseek-r1|/r1\b)",
)

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
    "compose_slides": "compose_slides",
}


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _truthy(name: str, default: str = "1") -> bool:
    return env(name, default).lower() in {"1", "true", "yes", "on"}


def llm_trace_enabled() -> bool:
    """Verbose LLM routing/fallback stderr (debug mode only)."""
    try:
        from arka.core.mode import is_debug_mode

        return is_debug_mode()
    except ImportError:
        return False


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
    tried: list[str] = field(default_factory=list)


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
            if provider == "openrouter" and any(
                x in msg
                for x in (
                    "no endpoints found",
                    "endpoints found",
                    "model_not_found",
                    "not_found",
                    "not found for",
                    "requires more credits",
                    "insufficient credits",
                    "can only afford",
                )
            ):
                self._exhausted.add(("openrouter", model_id))
                aliased = normalize_openrouter_model(model_id)
                if aliased != model_id:
                    self._exhausted.add(("openrouter", aliased))

    def exhausted(self, provider: str, model_id: str) -> bool:
        with self._lock:
            return (provider.lower(), model_id) in self._exhausted

    def reset(self) -> None:
        with self._lock:
            self._exhausted.clear()


EXHAUSTION = ExhaustionStore()
_EXHAUSTION_NOTIFIED = False
_LAST_EXHAUSTION_LOG = 0.0


def _notify_total_exhaustion(message: str) -> None:
    """Best-effort cross-platform notification; never disrupts fallback."""
    global _EXHAUSTION_NOTIFIED
    if _EXHAUSTION_NOTIFIED or not _truthy("LLM_EXHAUSTION_NOTIFY", "1"):
        return
    try:
        from arka.paths import cache_dir
        stamp = cache_dir() / "llm-exhaustion-notified"
        cooldown = max(60, int(float(os.environ.get("LLM_EXHAUSTION_COOLDOWN", "3600"))))
        if stamp.is_file() and time.time() - stamp.stat().st_mtime < cooldown:
            _EXHAUSTION_NOTIFIED = True
            return
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
    except (OSError, ValueError):
        pass
    _EXHAUSTION_NOTIFIED = True
    try:
        import platform
        import subprocess
        if platform.system() == "Darwin":
            subprocess.run(["osascript", "-e", f'display notification "{message[:180]}" with title "Arka LLM"'], check=False, timeout=2)
        elif platform.system() == "Linux":
            subprocess.run(["notify-send", "Arka LLM", message[:180]], check=False, timeout=2)
        elif platform.system() == "Windows":
            print(f"Arka notification: {message}", file=sys.stderr)
        else:
            print(f"Arka notification: {message}", file=sys.stderr)
    except Exception:
        print(f"Arka notification: {message}", file=sys.stderr)


def _log_exhaustion_once(message: str, *, verbose: bool) -> None:
    """Avoid repeating the same exhaustion line in tight loops."""
    global _LAST_EXHAUSTION_LOG
    if not verbose:
        return
    cooldown = max(60, int(float(os.environ.get("LLM_EXHAUSTION_LOG_COOLDOWN", "3600"))))
    now = time.time()
    if now - _LAST_EXHAUSTION_LOG >= cooldown:
        print(f"arka_llm: all providers failed ({message})", file=sys.stderr)
        _LAST_EXHAUSTION_LOG = now
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
            "connection error",
            "network error",
            "failed to connect",
            "connect timeout",
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
            "no endpoints found",
            "endpoints found",
            "requires more credits",
            "insufficient credits",
            "can only afford",
            "fewer max_tokens",
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
                "exo",
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


def _benchmark_orchestrate_enabled() -> bool:
    try:
        from arka.llm.benchmarks import is_benchmark_orchestrate_enabled

        return is_benchmark_orchestrate_enabled()
    except ImportError:
        return False


def _benchmark_chain_entries(task: str) -> list[tuple[str, str]]:
    try:
        from arka.llm.benchmarks import benchmark_chain_entries

        return benchmark_chain_entries(task)
    except ImportError:
        return []


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
    preferred = [
        env("CHAT_MODEL"),
        env("AI_PREFERRED_MODEL"),
        env("LLM_MODEL"),
    ]
    live = fetch_gemini_models_live() if include_live and _gemini_list_enabled() else []
    live_set = set(live) if live else None
    raw = preferred + (explicit or ([] if live_set is not None else list(DEFAULT_GEMINI_MODELS)))
    if live_set is not None:
        raw.extend(live)
    elif include_live and _gemini_list_enabled():
        raw.extend(live)
    out: list[str] = []
    for model in raw:
        model = normalize_gemini_model(model)
        if not model or not model.startswith("gemini-"):
            continue
        if GEMINI_LIST_SKIP_RE.search(model):
            continue
        if live_set is not None and model not in live_set:
            continue
        if model not in out:
            out.append(model)
    if not out:
        if live:
            return list(live)
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
    preferred = [
        normalize_groq_model(env("GROQ_MODEL")),
        env("AI_PREFERRED_MODEL") if pref_provider == "groq" else "",
        env("LLM_MODEL") if pref_provider == "groq" else "",
    ]
    live = fetch_groq_models_live() if include_live and _groq_list_enabled() else []
    live_set = set(live) if live else None
    raw = preferred + (explicit or ([] if live_set is not None else list(DEFAULT_GROQ_MODELS)))
    if live_set is not None:
        raw.extend(live)
    elif include_live and _groq_list_enabled():
        raw.extend(live)
    out: list[str] = []
    for model in raw:
        model = normalize_groq_model(model)
        if not model or model.startswith("gemini-"):
            continue
        if live_set is not None and model not in live_set:
            continue
        if model not in out:
            out.append(model)
    if not out:
        if live:
            return list(live)
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
    preferred = [
        env("OLLAMA_CHAT_MODEL"),
        pref_model if pref_provider == "ollama" else "",
        env("LLM_MODEL") if pref_provider == "ollama" else "",
    ]
    live = fetch_ollama_models_live() if include_live and _ollama_list_enabled() else []
    live_set = set(live) if live else None
    raw = preferred + (explicit or ([] if live_set is not None else list(DEFAULT_OLLAMA_MODELS)))
    if live_set is not None:
        raw.extend(live)
    elif include_live and _ollama_list_enabled():
        raw.extend(live)
    out: list[str] = []
    for model in raw:
        if not model or model.startswith("gemini-"):
            continue
        if live_set is not None and model not in live_set:
            continue
        if model not in out:
            out.append(model)
    if not out:
        if live:
            return list(live)
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


_PRIMARY_CLOUD_PROVIDERS = frozenset({"gemini", "groq", "openai", "anthropic"})


def _has_primary_cloud_keys() -> bool:
    return any(provider_has_keys(p) for p in _PRIMARY_CLOUD_PROVIDERS)


def _has_openrouter() -> bool:
    return provider_has_keys("openrouter")


def _openrouter_list_enabled() -> bool:
    if env("OPENROUTER_LIST") in {"0", "false", "no", "off"}:
        return False
    return bool(provider_has_keys("openrouter"))


def _parse_positive_int(raw: str, default: int) -> int:
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


def _is_simple_query(user: str) -> bool:
    text = re.sub(r"\s+", " ", (user or "").strip())
    if not text or len(text) > 80:
        return False
    if "\n" in text:
        return False
    words = text.split()
    return len(words) <= 8


def _openrouter_completion_price(item: dict[str, Any]) -> float:
    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    for key in ("completion", "prompt"):
        raw = pricing.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def _openrouter_meta_from_item(item: dict[str, Any]) -> dict[str, Any]:
    top = item.get("top_provider") if isinstance(item.get("top_provider"), dict) else {}
    max_out = top.get("max_completion_tokens")
    try:
        max_out_int = int(max_out) if max_out is not None else None
    except (TypeError, ValueError):
        max_out_int = None
    ctx = item.get("context_length") or top.get("context_length")
    try:
        ctx_int = int(ctx) if ctx is not None else None
    except (TypeError, ValueError):
        ctx_int = None
    return {
        "completion_price": _openrouter_completion_price(item),
        "max_completion_tokens": max_out_int,
        "context_length": ctx_int,
    }


def openrouter_model_meta(model_id: str) -> dict[str, Any] | None:
    mid = normalize_openrouter_model(model_id)
    if not mid:
        return None
    with _OPENROUTER_LIVE_LOCK:
        if _OPENROUTER_META_CACHE:
            meta = _OPENROUTER_META_CACHE[1].get(mid)
            if meta:
                return dict(meta)
    return None


def resolve_max_tokens(
    provider: str,
    model_id: str,
    *,
    task: str = "default",
    user: str = "",
) -> int:
    """Cap completion tokens per provider, task, and prompt complexity."""
    profile = normalize_task(task)
    cap = TASK_MAX_TOKENS.get(profile, DEFAULT_LLM_MAX_TOKENS)
    if env("LLM_MAX_TOKENS"):
        cap = min(cap, _parse_positive_int(env("LLM_MAX_TOKENS"), cap))

    provider = provider.lower()
    if provider == "openrouter":
        or_cap = env("OPENROUTER_MAX_TOKENS") or str(OPENROUTER_DEFAULT_MAX_TOKENS)
        cap = min(cap, _parse_positive_int(or_cap, OPENROUTER_DEFAULT_MAX_TOKENS))
        meta = openrouter_model_meta(model_id)
        if meta and meta.get("max_completion_tokens"):
            cap = min(cap, int(meta["max_completion_tokens"]))

    if _is_simple_query(user):
        cap = min(cap, SIMPLE_QUERY_MAX_TOKENS)

    return max(64, cap)


def _is_openrouter_credit_error(msg: str) -> bool:
    low = (msg or "").lower()
    return (
        "requires more credits" in low
        or "insufficient credits" in low
        or ("can only afford" in low and "max_tokens" in low)
    )


def _is_retired_model_error(msg: str) -> bool:
    """Retirement/410 responses are permanent for this model, not key failures."""
    return bool(re.search(r"(?i)\b410\b|\b(?:retired|deprecated|shut\s*down|no longer available)\b", str(msg or "")))


def _is_openrouter_account_credit_failure(err_text: str, attempt_max_tokens: int) -> bool:
    """True when lowering max_tokens is unlikely to help (account balance vs request cap)."""
    if not _is_openrouter_credit_error(err_text):
        return False
    low = (err_text or "").lower()
    if "insufficient credits" in low:
        return True
    affordable = _parse_affordable_tokens(err_text)
    return affordable is not None and affordable >= attempt_max_tokens


def _exhaust_all_openrouter_models(store: ExhaustionStore) -> None:
    for mid in openrouter_model_ids(include_live=False):
        store.mark("openrouter", mid, RuntimeError("openrouter credit exhausted"))


def _parse_affordable_tokens(msg: str) -> int | None:
    m = re.search(r"can only afford\s+(\d+)", msg, re.I)
    if not m:
        return None
    try:
        return max(64, int(m.group(1)))
    except ValueError:
        return None


def _reduce_max_tokens_for_credit_error(current: int, err_text: str) -> int:
    affordable = _parse_affordable_tokens(err_text)
    if affordable is not None:
        return max(64, min(current, affordable))
    return max(256, current // 2)


def normalize_openrouter_model(model_id: str) -> str:
    mid = (model_id or "").strip()
    return OPENROUTER_MODEL_ALIASES.get(mid, mid)


def _openrouter_model_routable(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    mid = str(item.get("id") or "").strip()
    if not mid or OPENROUTER_LIST_SKIP_RE.search(mid):
        return False
    arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    modality = str(arch.get("modality") or "").lower()
    if modality and "text" not in modality:
        return False
    top = item.get("top_provider")
    return isinstance(top, dict) and bool(top)


def _rank_openrouter_model(model_id: str) -> tuple[int, float, str]:
    mid = model_id.lower()
    defaults = list(DEFAULT_OPENROUTER_MODELS)
    spec = get_provider("openrouter")
    if spec and spec.default_models:
        defaults = list(spec.default_models)
    for idx, candidate in enumerate(defaults):
        if candidate.lower() == mid:
            return (0, float(idx), mid)
    if ":free" in mid:
        return (1, 0.0, mid)
    if OPENROUTER_DEPRIORITIZE_RE.search(mid):
        return (9, 0.0, mid)
    meta = openrouter_model_meta(model_id)
    price = float(meta.get("completion_price", 0.0)) if meta else 0.0
    if price <= 0:
        tier = 2
    elif price < 0.000001:
        tier = 2
    elif price < 0.00001:
        tier = 3
    else:
        tier = 4
    return (tier, price, mid)


def _filter_openrouter_chat_models(model_ids: list[str]) -> list[str]:
    out: list[str] = []
    for mid in model_ids:
        if mid not in out:
            out.append(mid)
    out.sort(key=_rank_openrouter_model)
    return out


def pick_openrouter_default_model(models: list[str]) -> str:
    spec = get_provider("openrouter")
    defaults = list(spec.default_models) if spec and spec.default_models else list(DEFAULT_OPENROUTER_MODELS)
    for candidate in defaults:
        if candidate in models:
            return candidate
    ranked = _filter_openrouter_chat_models(models)
    if ranked:
        return ranked[0]
    return spec.default_model if spec else ""


def fetch_openrouter_models_live(*, force: bool = False) -> list[str]:
    """List OpenRouter chat models from /api/v1/models (cached ~10 min)."""
    global _OPENROUTER_LIVE_CACHE, _OPENROUTER_META_CACHE

    if not _openrouter_list_enabled():
        return []

    keys = iter_provider_keys("openrouter")
    if not keys:
        return []

    now = time.time()
    with _OPENROUTER_LIVE_LOCK:
        if not force and _OPENROUTER_LIVE_CACHE and now - _OPENROUTER_LIVE_CACHE[0] < _OPENROUTER_LIVE_TTL:
            return list(_OPENROUTER_LIVE_CACHE[1])

    data = None
    for key in keys:
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            break
        except urllib.error.HTTPError as exc:
            if is_key_retryable(str(exc)) and key != keys[-1]:
                continue
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            if key != keys[-1]:
                continue

    if data is None:
        with _OPENROUTER_LIVE_LOCK:
            if _OPENROUTER_LIVE_CACHE:
                return list(_OPENROUTER_LIVE_CACHE[1])
        return []

    models: list[str] = []
    meta_map: dict[str, dict[str, Any]] = {}
    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        if not _openrouter_model_routable(item):
            continue
        mid = str(item.get("id") or "").strip()
        if mid not in models:
            models.append(mid)
            meta_map[mid] = _openrouter_meta_from_item(item)

    models = _filter_openrouter_chat_models(models)
    default = pick_openrouter_default_model(models)
    if default and default in models:
        models.remove(default)
        models.insert(0, default)

    with _OPENROUTER_LIVE_LOCK:
        _OPENROUTER_LIVE_CACHE = (now, models)
        _OPENROUTER_META_CACHE = (now, meta_map)
    return list(models)


def openrouter_model_ids(*, include_live: bool = True) -> list[str]:
    spec = get_provider("openrouter")
    if not spec:
        return []
    pref_provider = (env("AI_PREFERRED_PROVIDER") or env("LLM_PROVIDER")).lower()
    pref_raw = env("AI_PREFERRED_MODEL") if pref_provider == "openrouter" else ""
    llm_raw = env("LLM_MODEL") if pref_provider == "openrouter" else ""
    explicit = [
        normalize_openrouter_model(m.strip())
        for m in env("OPENROUTER_MODELS").split(",")
        if m.strip()
    ]
    live = fetch_openrouter_models_live() if include_live and _openrouter_list_enabled() else []
    live_set = set(live)
    catalog = explicit or list(spec.default_models) or [spec.default_model]

    out: list[str] = []

    def _add(model: str) -> None:
        model = normalize_openrouter_model(model)
        if not model or model in out:
            return
        if live_set and model not in live_set:
            return
        out.append(model)

    if pref_raw and (not live_set or pref_raw in live_set):
        _add(pref_raw)
    if llm_raw and (not live_set or llm_raw in live_set):
        _add(llm_raw)
    for model in live or catalog:
        _add(model)
    if not out and live:
        out.extend(live)
    if out:
        return out
    return [normalize_openrouter_model(m) for m in provider_model_ids(spec)]


def provider_detected_model_count(provider: str) -> int | None:
    """Best-effort model count for doctor output (uses live cache when available)."""
    try:
        from arka.llm.provider_select import detect_provider_models

        models, _source = detect_provider_models(provider, include_live=True)
        return len(models) if models else None
    except ImportError:
        slug = (provider or "").strip().lower()
        if slug == "gemini":
            models = gemini_model_ids(include_live=True)
        elif slug == "groq":
            models = groq_model_ids(include_live=True)
        elif slug == "ollama":
            models = ollama_model_ids(include_live=True)
        elif slug == "openrouter":
            models = openrouter_model_ids(include_live=True)
        else:
            spec = get_provider(slug)
            models = provider_model_ids(spec) if spec else []
        return len(models) if models else None


def llm_doctor_lines() -> list[str]:
    """Diagnostic lines for ``arka doctor`` — configured LLM providers."""
    configured = [spec.slug for spec in provider_specs() if provider_available(spec.slug)]
    pref = (env("AI_PREFERRED_PROVIDER") or env("LLM_PROVIDER")).lower()
    pref_model = env("AI_PREFERRED_MODEL") or env("LLM_MODEL")
    lines: list[str] = []
    if configured:
        lines.append(f"  LLM providers:  {', '.join(configured)}")
    else:
        lines.append(
            "  LLM providers:  none "
            "(set OPENROUTER_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, or run ollama serve)"
        )
    if pref and pref_model:
        count = provider_detected_model_count(pref)
        suffix = f" ({count} models detected)" if count else ""
        lines.append(f"  LLM preferred:  {pref} → {pref_model}{suffix}")
    elif _has_openrouter() and not _has_primary_cloud_keys():
        spec = get_provider("openrouter")
        default = spec.default_model if spec else "meta-llama/llama-3.3-70b-instruct"
        count = provider_detected_model_count("openrouter")
        suffix = f" ({count} models detected)" if count else ""
        lines.append(f"  LLM preferred:  openrouter → {default} (auto — only cloud key){suffix}")
    return lines


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

    # Local vLLM is a text-generation fallback; multimodal/embedding/TTS tasks
    # should stay on providers that advertise those capabilities.
    non_text_task = bool(re.search(r"(?i)\b(?:vision|image|audio|speech|tts|stt|embedding|embed|rerank|moderation)\b", f"{task} {skill or ''}"))

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
        elif pref_provider == "openrouter":
            live = fetch_openrouter_models_live() if _openrouter_list_enabled() else []
            if not live or pref_model in live:
                add(pref_provider, normalize_openrouter_model(pref_model))
        else:
            add(pref_provider, pref_model)

    if (env("VLLM_CLOUD_URL") or env("VLLM_CLOUD_API_URL")) and not non_text_task:
        cloud_model = env("VLLM_CLOUD_MODEL") or "default"
        add("vllm-cloud", cloud_model)

    explicit_vllm = vllm_explicitly_configured()
    vllm_fallback = env("VLLM_FALLBACK", "0").lower() in {"1", "true", "yes", "on"}
    if explicit_vllm:
        apply_vllm_defaults()
    if (explicit_vllm or vllm_fallback or is_reachable("vllm")) and not non_text_task:
        add("vllm", env("VLLM_MODEL") or "default")

    openrouter_only = _has_openrouter() and not _has_primary_cloud_keys()
    if openrouter_only and pref_provider != "openrouter":
        for model_id in openrouter_model_ids():
            add("openrouter", model_id)

    _expand_provider_models(add, pref_provider, provider="gemini", model_ids=gemini_model_ids())
    if _has_groq():
        for model_id in groq_model_ids():
            add("groq", model_id)
    ollama_models = ollama_model_ids()
    if not non_text_task:
        text_models = [m for m in ollama_models if not OLLAMA_VISION_SKIP_RE.search(m)]
        ollama_models = text_models
    for model_id in ollama_models:
        add("ollama", model_id)

    for spec in provider_specs():
        if spec.slug in {"gemini", "groq", "ollama", "vllm", "vllm-cloud"}:
            continue
        if spec.slug == "openrouter" and openrouter_only and pref_provider != "openrouter":
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
    benchmark: list[tuple[str, str]] = []
    if _benchmark_orchestrate_enabled():
        benchmark = _benchmark_chain_entries(task)
    head = benchmark + skill_models + guidance
    if head:
        ordered = _prepend_chain(head, ordered)

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


def build_model(
    provider: str,
    model_id: str,
    temperature: float,
    *,
    max_tokens: int | None = None,
    session: LlmServerSession | None = None,
) -> Any | None:
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
        kwargs: dict[str, Any] = {"id": normalize_gemini_model(model_id), "temperature": temperature}
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        return Gemini(**kwargs)

    if provider == "groq":
        from agno.models.groq import Groq

        apply_provider_key("groq")
        kwargs = {"id": normalize_groq_model(model_id), "temperature": temperature}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return Groq(**kwargs)

    if provider == "ollama":
        from agno.models.ollama import Ollama

        mid = model_id or env("OLLAMA_CHAT_MODEL") or "minimax-m2.5:cloud"
        if mid.startswith("gemini-"):
            mid = "minimax-m2.5:cloud"
        apply_provider_key("ollama")
        options: dict[str, int | float] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        return Ollama(
            id=mid,
            host=_ollama_host(),
            api_key=env("OLLAMA_API_KEY") or None,
            options=options,
        )

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        apply_provider_key("openai")
        kwargs = {"id": model_id, "temperature": temperature}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return OpenAIChat(**kwargs)

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        apply_provider_key("anthropic")
        kwargs = {"id": model_id, "temperature": temperature}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return Claude(**kwargs)

    if provider == "vllm":
        from agno.models.openai import OpenAIChat

        kwargs = {
            "id": model_id or "default",
            "base_url": _vllm_base_url(),
            "api_key": env("VLLM_API_KEY") or "EMPTY",
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return OpenAIChat(**kwargs)

    if provider == "vllm-cloud":
        from agno.models.openai import OpenAIChat

        apply_provider_key("vllm-cloud")
        base = _vllm_cloud_base_url()
        if not base:
            return None
        spec = get_provider("vllm-cloud")
        mid = model_id or env("VLLM_CLOUD_MODEL") or (spec.default_model if spec else "default")
        api_key = (provider_api_key(spec) if spec else "") or env("VLLM_CLOUD_API_KEY") or "EMPTY"
        kwargs = {
            "id": mid,
            "base_url": base,
            "api_key": api_key,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return OpenAIChat(**kwargs)

    spec = get_provider(provider)
    if spec and spec.kind in {"openai_compatible", "local_openai"}:
        from agno.models.openai import OpenAIChat

        apply_provider_key(provider)
        base = provider_base_url(spec)
        if not base:
            return None
        api_key = provider_api_key(spec) or env("OPENAI_API_KEY") or "EMPTY"
        mid = model_id or spec.default_model
        kwargs = {
            "id": mid,
            "base_url": base,
            "api_key": api_key,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return OpenAIChat(**kwargs)

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
            "connection error",
            "network error",
            "failed to connect",
            "connection refused",
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
            "no endpoints found",
            "endpoints found",
            "requires more credits",
            "insufficient credits",
            "can only afford",
            "fewer max_tokens",
            "empty response",
        )
    ):
        return True
    if re.search(r"\b401\b", stripped) or re.search(r"\b403\b", stripped):
        return True
    return False


def format_llm_failure(*, tried: list[str] | None = None, last_error: str = "", attempts: int = 0) -> str:
    """User-facing message when every provider/model in the chain failed."""
    providers: list[str] = []
    seen: set[str] = set()
    for label in tried or []:
        prov = label.split("/", 1)[0].split(" ", 1)[0].strip().lower()
        if prov and prov not in seen:
            seen.add(prov)
            providers.append(prov)

    lines = ["All configured LLM providers failed."]
    if providers:
        attempt_note = f" ({attempts} model attempt(s))" if attempts else ""
        lines.append(f"Tried providers: {', '.join(providers)}{attempt_note}.")
    elif attempts:
        lines.append(f"Tried {attempts} model(s) with no successful response.")
    if last_error:
        lines.append(f"Last error: {last_error[:240]}")
    lines.append("Run `arka doctor` to verify API keys and provider reachability.")
    return "\n".join(lines)


@contextmanager
def _quiet_llm_logs() -> Iterator[None]:
    if llm_trace_enabled():
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
        verbose = llm_trace_enabled()
        notify = verbose and _truthy("LLM_FALLBACK_NOTIFY", "0")
        attempts = 0
        tried: list[str] = []

        session = LlmServerSession()
        with _quiet_llm_logs():
            try:
                for provider, model_id in chain:
                    if self.store.exhausted(provider, model_id):
                        continue
                    attempt_max_tokens = resolve_max_tokens(
                        provider,
                        model_id,
                        task=self.task,
                        user=user,
                    )
                    credit_retries_left = 2
                    key_retry = True
                    while key_retry:
                        key_retry = False
                        token_retry = True
                        while token_retry:
                            token_retry = False
                            apply_provider_key(provider)
                            model = build_model(
                                provider,
                                model_id,
                                temperature,
                                max_tokens=attempt_max_tokens,
                                session=session,
                            )
                            if model is None:
                                break
                            attempts += 1
                            label = f"{provider}/{model_id}"
                            kr = key_rotation_label(provider)
                            if kr:
                                label = f"{label} ({kr})"
                            if attempt_max_tokens:
                                label = f"{label} (max_tokens={attempt_max_tokens})"
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
                                "arka.llm.max_tokens": attempt_max_tokens,
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
                                    if _is_retired_model_error(err_text):
                                        self.store.mark(provider, model_id, RuntimeError(f"retired model: {err_text}"))
                                        if verbose:
                                            print(f"arka_llm: skip retired model {label}", file=sys.stderr)
                                        break
                                    if rotate_provider_key(provider, err_text):
                                        if verbose:
                                            print(
                                                f"arka_llm: rotating {provider} API key after error",
                                                file=sys.stderr,
                                            )
                                        key_retry = True
                                        break
                                    if (
                                        provider == "openrouter"
                                        and _is_openrouter_credit_error(err_text)
                                    ):
                                        if (
                                            _is_openrouter_account_credit_failure(
                                                err_text, attempt_max_tokens
                                            )
                                            and _has_primary_cloud_keys()
                                        ):
                                            _exhaust_all_openrouter_models(self.store)
                                            if verbose:
                                                print(
                                                    "arka_llm: openrouter credits exhausted — "
                                                    "falling back to alternate provider",
                                                    file=sys.stderr,
                                                )
                                            break
                                        if credit_retries_left > 0:
                                            reduced = _reduce_max_tokens_for_credit_error(
                                                attempt_max_tokens,
                                                err_text,
                                            )
                                            if reduced < attempt_max_tokens:
                                                attempt_max_tokens = reduced
                                                credit_retries_left -= 1
                                                token_retry = True
                                                if verbose:
                                                    print(
                                                        f"arka_llm: credit limit — retry {label} "
                                                        f"with max_tokens={attempt_max_tokens}",
                                                        file=sys.stderr,
                                                    )
                                                continue
                                    self.store.mark(provider, model_id, RuntimeError(err_text))
                                    if verbose:
                                        print(f"arka_llm: fail {label}: {err_text}", file=sys.stderr)
                            except Exception as exc:
                                last_error = f"{label}: {exc}"
                                err_text = str(exc)
                                if trace_span is not None:
                                    if set_http_span_attributes is not None:
                                        code = (
                                            parse_http_status_code(exc)
                                            if parse_http_status_code is not None
                                            else None
                                        )
                                        if code is not None:
                                            set_http_span_attributes(attempt_span, status_code=code)
                                    mark_error(attempt_span, err_text, exc=exc)
                                if _is_retired_model_error(err_text):
                                    self.store.mark(provider, model_id, RuntimeError(f"retired model: {err_text}"))
                                    if verbose:
                                        print(f"arka_llm: skip retired model {label}", file=sys.stderr)
                                    continue
                                if rotate_provider_key(provider, exc):
                                    if verbose:
                                        print(
                                            f"arka_llm: rotating {provider} API key after {exc}",
                                            file=sys.stderr,
                                        )
                                    key_retry = True
                                    break
                                if (
                                    provider == "openrouter"
                                    and _is_openrouter_credit_error(err_text)
                                ):
                                    if (
                                        _is_openrouter_account_credit_failure(
                                            err_text, attempt_max_tokens
                                        )
                                        and _has_primary_cloud_keys()
                                    ):
                                        _exhaust_all_openrouter_models(self.store)
                                        if verbose:
                                            print(
                                                "arka_llm: openrouter credits exhausted — "
                                                "falling back to alternate provider",
                                                file=sys.stderr,
                                            )
                                        break
                                    if credit_retries_left > 0:
                                        reduced = _reduce_max_tokens_for_credit_error(
                                            attempt_max_tokens,
                                            err_text,
                                        )
                                        if reduced < attempt_max_tokens:
                                            attempt_max_tokens = reduced
                                            credit_retries_left -= 1
                                            token_retry = True
                                            if verbose:
                                                print(
                                                    f"arka_llm: credit limit — retry {label} "
                                                    f"with max_tokens={attempt_max_tokens}",
                                                    file=sys.stderr,
                                                )
                                            continue
                                self.store.mark(provider, model_id, exc)
                                if verbose:
                                    print(f"arka_llm: fail {label}: {exc}", file=sys.stderr)
            finally:
                session.close()

        _LAST_ERROR = last_error
        if last_error and chain and all(self.store.exhausted(p, m) for p, m in chain):
            _notify_total_exhaustion("All configured models/providers are exhausted. Check quotas or reset the fallback chain.")
        if last_error and verbose:
            _log_exhaustion_once(last_error, verbose=verbose)
        failure = format_llm_failure(tried=tried, last_error=last_error, attempts=attempts)
        return CompletionResult(error=failure, attempts=attempts, tried=list(tried))

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
                    attempt_max_tokens = resolve_max_tokens(
                        provider,
                        model_id,
                        task=self.task,
                        user=user,
                    )
                    key_retry = True
                    while key_retry:
                        key_retry = False
                        apply_provider_key(provider)
                        model = build_model(
                            provider,
                            model_id,
                            temperature,
                            max_tokens=attempt_max_tokens,
                            session=session,
                        )
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
    from arka.llm.thinking import instruction
    system = f"{system}\n\nThinking preference: {instruction()}"
    resolved_task, resolved_skill = resolve_llm_context(task=task, skill=skill)
    try:
        from arka.llm.prompt_compact import compact_user_prompt

        compacted = compact_user_prompt(user, task=resolved_task)
        if compacted.changed:
            user = compacted.compact
    except ImportError:
        pass
    if task or skill or chain:
        engine = LlmFallbackEngine(
            task=resolved_task,
            skill=resolved_skill,
            chain=chain,
        )
    else:
        engine = _DEFAULT_ENGINE
    result = engine.complete(system, user, temperature=temperature)
    if result.text:
        return result.text
    if result.error:
        return result.error
    return ""


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
    try:
        from arka.llm.prompt_compact import compact_user_prompt

        compacted = compact_user_prompt(user, task=resolved_task)
        if compacted.changed:
            user = compacted.compact
    except ImportError:
        pass
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


# Backward-compatible alias used by agent teams executor.
LlmOrchestrator = LlmFallbackEngine
