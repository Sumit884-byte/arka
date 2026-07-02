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
from typing import Any, Iterator

from arka_llm_servers import LOCAL_PROVIDERS, LlmServerSession, is_reachable, provider_available_with_servers

DEFAULT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
]

GEMINI_LIST_SKIP_RE = re.compile(
    r"(tts|image|embedding|aqa|vision|exp-|experimental|preview-tts|nano-banana)",
    re.I,
)

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
}


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _truthy(name: str, default: str = "1") -> bool:
    return env(name, default).lower() in {"1", "true", "yes", "on"}


def normalize_task(task: str | None) -> str:
    raw = (task or env("ARKA_LLM_TASK") or "default").strip().lower()
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
            if provider == "groq" and "invalid api key" in msg:
                for mid in groq_model_ids():
                    self._exhausted.add(("groq", mid))
            if provider == "groq" and any(
                x in msg for x in ("decommissioned", "model_decommissioned", "model_not_found")
            ):
                self._exhausted.add(("groq", model_id))
                for deprecated in GROQ_MODEL_ALIASES:
                    self._exhausted.add(("groq", deprecated))

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


def parse_chain(raw: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            provider, model_id = part.split(":", 1)
        elif "/" in part:
            provider, model_id = part.split("/", 1)
        else:
            continue
        provider = provider.strip().lower()
        model_id = model_id.strip()
        if provider and model_id:
            out.append((provider, model_id))
    return out


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
    if env("ARKA_GEMINI_LIST") in {"0", "false", "no", "off"}:
        return False
    if env("ARKA_GEMINI_LIST") in {"1", "true", "yes", "on"}:
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

    key = _ensure_google_key()
    if not key:
        return []

    now = time.time()
    with _GEMINI_LIVE_LOCK:
        if not force and _GEMINI_LIVE_CACHE and now - _GEMINI_LIVE_CACHE[0] < _GEMINI_LIVE_TTL:
            return list(_GEMINI_LIVE_CACHE[1])

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
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
    explicit = [normalize_gemini_model(m.strip()) for m in env("ARKA_GEMINI_MODELS").split(",") if m.strip()]
    raw = [
        env("ARKA_CHAT_MODEL"),
        env("AI_PREFERRED_MODEL"),
        env("ARKA_LLM_MODEL"),
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


def groq_model_ids() -> list[str]:
    raw = [
        normalize_groq_model(env("GROQ_MODEL")),
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ]
    out: list[str] = []
    for model in raw:
        if model and model not in out:
            out.append(model)
    return out


def ollama_model_ids() -> list[str]:
    pref_provider = (env("AI_PREFERRED_PROVIDER") or env("ARKA_LLM_PROVIDER")).lower()
    pref_model = env("AI_PREFERRED_MODEL") or env("ARKA_LLM_MODEL")
    raw = [
        env("OLLAMA_CHAT_MODEL"),
        pref_model if pref_provider == "ollama" else "",
        env("ARKA_LLM_MODEL") if pref_provider == "ollama" else "",
        "minimax-m2.5:cloud",
        "minimax-m2:cloud",
        "qwen3:8b",
        "llama3.2:1b",
    ]
    out: list[str] = []
    for model in raw:
        if model and model not in out:
            out.append(model)
    return out


def build_default_chain(*, task: str = "default") -> list[tuple[str, str]]:
    task_key = normalize_task(task).upper()
    for env_name in (f"ARKA_LLM_FALLBACK_{task_key}", "ARKA_LLM_FALLBACK"):
        explicit = parse_chain(env(env_name))
        if explicit:
            return explicit

    pref_provider = (env("AI_PREFERRED_PROVIDER") or env("ARKA_LLM_PROVIDER")).lower()
    pref_model = env("AI_PREFERRED_MODEL") or env("ARKA_LLM_MODEL")

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
        else:
            add(pref_provider, pref_model)

    if env("VLLM_HOST") or env("VLLM_API_URL"):
        add("vllm", env("VLLM_MODEL") or "default")

    if pref_provider == "gemini" or not pref_provider:
        for model_id in gemini_model_ids():
            add("gemini", model_id)

    if env("GROQ_API_KEY"):
        for model_id in groq_model_ids():
            add("groq", model_id)

    for model_id in ollama_model_ids():
        add("ollama", model_id)

    for provider, model_id in DEFAULT_CHAIN:
        add(provider, model_id)

    if pref_provider:
        pref_first = [x for x in ordered if x[0] == pref_provider]
        pref_rest = [x for x in ordered if x[0] != pref_provider]
        ordered = pref_first + pref_rest

    return ordered


def _ensure_google_key() -> str:
    key = env("GEMINI_API_KEY") or env("GOOGLE_API_KEY")
    if key and not env("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = key
    return key


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

        return Groq(id=normalize_groq_model(model_id), temperature=temperature)

    if provider == "ollama":
        from agno.models.ollama import Ollama

        mid = model_id or env("OLLAMA_CHAT_MODEL") or "minimax-m2.5:cloud"
        if mid.startswith("gemini-"):
            mid = "minimax-m2.5:cloud"
        return Ollama(
            id=mid,
            host=_ollama_host(),
            api_key=env("OLLAMA_API_KEY") or None,
            options={"temperature": temperature},
        )

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id, temperature=temperature)

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=model_id, temperature=temperature)

    if provider == "vllm":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(
            id=model_id or "default",
            base_url=_vllm_base_url(),
            api_key=env("VLLM_API_KEY") or "EMPTY",
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
    if env("ARKA_LLM_VERBOSE") in {"1", "true", "yes"}:
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
    chain: list[tuple[str, str]] | None = None
    store: ExhaustionStore = field(default_factory=lambda: EXHAUSTION)

    def candidates(self) -> list[tuple[str, str]]:
        if self.chain:
            return list(self.chain)
        return build_default_chain(task=self.task)

    def complete(self, system: str, user: str, *, temperature: float = 0.2) -> CompletionResult:
        from agno.agent import Agent

        global _LAST_MODEL, _LAST_ERROR

        if not _truthy("ARKA_LLM_AUTO_FALLBACK", "1") and self.chain is None:
            chain = self.candidates()[:1]
        else:
            chain = self.candidates()

        last_error = ""
        verbose = env("ARKA_LLM_VERBOSE") in {"1", "true", "yes"}
        notify = _truthy("ARKA_LLM_FALLBACK_NOTIFY", "0")
        attempts = 0
        tried: list[str] = []

        session = LlmServerSession()
        with _quiet_llm_logs():
            try:
                for provider, model_id in chain:
                    if self.store.exhausted(provider, model_id):
                        continue
                    model = build_model(provider, model_id, temperature, session=session)
                    if model is None:
                        continue
                    attempts += 1
                    label = f"{provider}/{model_id}"
                    tried.append(label)
                    try:
                        if verbose:
                            print(
                                f"arka_llm: trying {label} (task={normalize_task(self.task)})",
                                file=sys.stderr,
                            )
                        agent = Agent(model=model, instructions=system, markdown=False)
                        run = agent.run(user)
                        text = getattr(run, "content", None)
                        if text is None:
                            text = str(run)
                        text = _strip_fences(str(text).strip())
                        if text and not _looks_like_error(text):
                            _LAST_MODEL = (provider, model_id)
                            _LAST_ERROR = ""
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
                        self.store.mark(provider, model_id, RuntimeError(err_text))
                        if verbose:
                            print(f"arka_llm: fail {label}: {err_text}", file=sys.stderr)
                    except Exception as exc:
                        last_error = f"{label}: {exc}"
                        self.store.mark(provider, model_id, exc)
                        if verbose:
                            print(f"arka_llm: fail {label}: {exc}", file=sys.stderr)
            finally:
                session.close()

        _LAST_ERROR = last_error
        if last_error and verbose:
            print(f"arka_llm: all providers failed ({last_error})", file=sys.stderr)
        return CompletionResult(error=last_error, attempts=attempts)


_DEFAULT_ENGINE = LlmFallbackEngine(task="default")


def llm_complete(
    system: str,
    user: str,
    temperature: float = 0.2,
    *,
    task: str | None = None,
    chain: list[tuple[str, str]] | None = None,
) -> str:
    if task or chain:
        engine = LlmFallbackEngine(
            task=normalize_task(task) if task else "default",
            chain=chain,
        )
    else:
        engine = _DEFAULT_ENGINE
    result = engine.complete(system, user, temperature=temperature)
    return result.text


def llm_last_error() -> str:
    return _LAST_ERROR


def llm_last_model() -> tuple[str, str] | None:
    return _LAST_MODEL


def ordered_model_candidates(*, task: str | None = None) -> list[tuple[str, str]]:
    return build_default_chain(task=normalize_task(task))


def reset_llm_exhaustion() -> None:
    EXHAUSTION.reset()


def model_label(*, prefer_last: bool = True, task: str | None = None) -> str:
    if prefer_last and _LAST_MODEL:
        provider, model_id = _LAST_MODEL
        return f"{provider}/{model_id}"
    for provider, model_id in ordered_model_candidates(task=task):
        if not provider_available(provider):
            continue
        if EXHAUSTION.exhausted(provider, model_id):
            continue
        return f"{provider}/{model_id}"
    return ""
