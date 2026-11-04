"""Watch LLM provider health: config warnings, reaction-time budgets, drift notes."""

from __future__ import annotations

import concurrent.futures
import json
import os
import queue
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# Bound time-to-first-token, not the whole answer. After the first token
# the request may finish at the model's own pace (up to a long drain cap).
# A single 3.5s TTFT is only valid for small/fast models; pro, vision, and
# reasoning endpoints need a longer first-chunk wait or they false-failover.
_DEFAULT_REACTION_MS = 400.0
_DEFAULT_CHAT_ATTEMPT_MS = 3500.0
_DEFAULT_ROUTE_ATTEMPT_MS = 2000.0
_DEFAULT_ATTEMPT_MS = 8000.0
_DEFAULT_FAST_TTFT_S = 4.0
_DEFAULT_STANDARD_TTFT_S = 9.0
_DEFAULT_REASONING_TTFT_S = 25.0
_DEFAULT_CONNECT_MS = 2000.0
_DEFAULT_DRAIN_S = 120.0
_MAX_TTFT_S = 45.0
_PREFILL_TOKEN_STEP = 7500
_CHARS_PER_TOKEN = 4.0

_REASONING_RE = re.compile(
    r"(?i)(\bo1\b|\bo3\b|\bo4\b|o1-|o3-|o4-|r1\b|deepseek-r1|qwq|"
    r"thinking|reason(?:ing)?|extended-think)"
)
_FAST_RE = re.compile(
    r"(?i)(haiku|flash|lite|mini|nano|instant|8b|7b|3b|1b|small|fast)"
)
_STANDARD_RE = re.compile(
    r"(?i)(sonnet|opus|pro\b|gpt-4(?!o-mini)|gpt-4o(?!-mini)|"
    r"robotics|vision|multimodal|70b|72b|405b|235b|large)"
)

_WARNED = False
_WARN_LOCK = threading.Lock()
_FILE = "llm-provider-health.json"
_MAX_INCIDENTS = 40


def _cache_path() -> Path:
    try:
        from arka.paths import cache_dir

        return cache_dir() / _FILE
    except ImportError:
        return Path.home() / ".cache" / "fish-agent" / _FILE


def _env_ms(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def reaction_ms() -> float:
    return _env_ms("ARKA_REACTION_MS", _DEFAULT_REACTION_MS)


def connect_timeout_s() -> float:
    """TCP/TLS establish budget. Separate from TTFT (first response chunk)."""
    return _env_ms("ARKA_LLM_CONNECT_MS", _DEFAULT_CONNECT_MS) / 1000.0


def ttft_tier(model_id: str | None) -> str:
    """Classify a model for first-token SLA: fast | standard | reasoning."""
    low = (model_id or "").strip().lower()
    if not low:
        return "fast"
    if _REASONING_RE.search(low):
        return "reasoning"
    if _STANDARD_RE.search(low):
        return "standard"
    if _FAST_RE.search(low):
        return "fast"
    return "standard"


def _tier_base_s(tier: str) -> float:
    if tier == "reasoning":
        return _env_ms("ARKA_LLM_TTFT_REASONING_MS", _DEFAULT_REASONING_TTFT_S * 1000.0) / 1000.0
    if tier == "standard":
        return _env_ms("ARKA_LLM_TTFT_STANDARD_MS", _DEFAULT_STANDARD_TTFT_S * 1000.0) / 1000.0
    return _env_ms("ARKA_LLM_TTFT_FAST_MS", _DEFAULT_FAST_TTFT_S * 1000.0) / 1000.0


def prefill_bonus_s(prompt_chars: int = 0) -> float:
    """Add time for long prefill: +1s per ~7.5k tokens after the first 10k."""
    if prompt_chars <= 0:
        return 0.0
    tokens = prompt_chars / _CHARS_PER_TOKEN
    if tokens <= 10_000:
        return 0.0
    return (tokens - 10_000) / _PREFILL_TOKEN_STEP


def ttft_failover_backoff_s(misses: int) -> float:
    """Exponential pause after a TTFT miss so keys are not burned in a burst."""
    n = max(1, int(misses))
    return min(2.0, 0.25 * (2 ** (n - 1)))


def is_first_token_timeout(exc: Exception | str) -> bool:
    return "no first token" in str(exc or "").lower()


def attempt_timeout_s(
    task: str = "chat",
    *,
    model_id: str | None = None,
    prompt_chars: int = 0,
) -> float:
    """Seconds allowed before the first output token. Not full-answer time."""
    override = _env_ms("ARKA_LLM_ATTEMPT_MS", 0.0)
    if override > 0:
        return override / 1000.0
    profile = (task or "chat").strip().lower()
    if profile in {"route", "routing"}:
        if model_id and ttft_tier(model_id) == "reasoning":
            return min(8.0, _tier_base_s("reasoning"))
        return _DEFAULT_ROUTE_ATTEMPT_MS / 1000.0
    if not model_id and profile in {"chat", "default"}:
        return _DEFAULT_CHAT_ATTEMPT_MS / 1000.0
    if not model_id:
        return _DEFAULT_ATTEMPT_MS / 1000.0
    budget = _tier_base_s(ttft_tier(model_id)) + prefill_bonus_s(prompt_chars)
    return min(_MAX_TTFT_S, max(1.0, budget))


def first_token_timeout_s(
    task: str = "chat",
    *,
    model_id: str | None = None,
    prompt_chars: int = 0,
) -> float:
    return attempt_timeout_s(task, model_id=model_id, prompt_chars=prompt_chars)


def drain_timeout_s() -> float:
    return _env_ms("ARKA_LLM_DRAIN_MS", _DEFAULT_DRAIN_S * 1000.0) / 1000.0


def call_with_timeout(fn: Callable[[], T], timeout_s: float) -> T:
    """Run *fn* and raise TimeoutError when it exceeds the first-token budget."""
    if timeout_s <= 0:
        return fn()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError(f"no first token in {timeout_s:.1f}s") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _stream_delta(event: Any, seen: str) -> tuple[str, str]:
    event_name = getattr(event, "event", "") or type(event).__name__
    if event_name == "RunError":
        return seen, ""
    if event_name not in (
        "RunContent",
        "IntermediateRunContent",
        "ReasoningContentDelta",
    ):
        return seen, ""
    piece = getattr(event, "content", None)
    if piece is None:
        piece = getattr(event, "reasoning_content", None)
    if not piece:
        return seen, ""
    text = str(piece)
    if text.startswith(seen):
        delta = text[len(seen) :]
        return text, delta
    return seen + text, text


def run_with_first_token_budget(agent: Any, user: str, timeout_s: float) -> Any:
    """Stream a run. Fail only if the first token misses *timeout_s*; then drain."""
    if timeout_s <= 0:
        return agent.run(user)

    events: queue.Queue[tuple[str, Any]] = queue.Queue()

    def _worker() -> None:
        try:
            seen = ""
            for event in agent.run(user, stream=True):
                seen, delta = _stream_delta(event, seen)
                if delta:
                    events.put(("tok", delta))
            events.put(("done", seen))
        except TypeError:
            try:
                run = agent.run(user)
                events.put(("done_run", run))
            except Exception as exc:
                events.put(("err", exc))
        except Exception as exc:
            events.put(("err", exc))

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    try:
        kind, payload = events.get(timeout=timeout_s)
    except queue.Empty as exc:
        raise TimeoutError(f"no first token in {timeout_s:.1f}s") from exc
    if kind == "err":
        raise payload
    if kind == "done_run":
        return payload

    parts: list[str] = []
    if kind == "tok":
        parts.append(str(payload))
    elif kind == "done":
        text = str(payload or "").strip()
        return SimpleNamespace(content=text)

    deadline = time.monotonic() + drain_timeout_s()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            kind, payload = events.get(timeout=remaining)
        except queue.Empty:
            break
        if kind == "err":
            if parts:
                break
            raise payload
        if kind == "tok":
            parts.append(str(payload))
            continue
        if kind == "done":
            text = str(payload or "").strip() or "".join(parts).strip()
            return SimpleNamespace(content=text)
    text = "".join(parts).strip()
    if text:
        return SimpleNamespace(content=text)
    raise TimeoutError(f"no first token in {timeout_s:.1f}s")


def _configured_clouds() -> list[str]:
    found: list[str] = []
    if (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip():
        found.append("gemini")
    if (os.environ.get("GROQ_API_KEY") or "").strip():
        found.append("groq")
    if (os.environ.get("OPENROUTER_API_KEY") or "").strip():
        found.append("openrouter")
    if (os.environ.get("OPENAI_API_KEY") or "").strip():
        found.append("openai")
    if (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        found.append("anthropic")
    return found


def inspect_config() -> list[str]:
    """Warnings when the current LLM config will hang or has no fallback."""
    warnings: list[str] = []
    pref = (os.environ.get("AI_PREFERRED_PROVIDER") or os.environ.get("LLM_PROVIDER") or "").strip().lower()
    pref_model = (os.environ.get("AI_PREFERRED_MODEL") or os.environ.get("LLM_MODEL") or "").strip()
    clouds = _configured_clouds()

    if pref and pref_model:
        try:
            from arka.llm.retired_models import is_retired

            if is_retired(pref, pref_model):
                warnings.append(
                    f"preferred {pref}/{pref_model} is marked retired — run `arka provider set` or `arka doctor`"
                )
        except ImportError:
            pass

    if pref in {"ollama", "vllm"}:
        try:
            from arka.llm.servers import is_reachable

            if not is_reachable(pref):
                warnings.append(
                    f"preferred local provider {pref} is not reachable — cloud fallback will be used"
                )
        except ImportError:
            pass

    if len(clouds) == 1:
        warnings.append(
            f"only {clouds[0]} is configured — add GROQ_API_KEY or OPENROUTER_API_KEY so rate limits can fail over"
        )
    if not clouds and pref not in {"ollama", "vllm", "apple-fm"}:
        warnings.append("no cloud LLM keys found — set GEMINI_API_KEY, GROQ_API_KEY, or OPENROUTER_API_KEY")

    return warnings


def emit_config_warnings(*, force: bool = False) -> list[str]:
    global _WARNED
    warnings = inspect_config()
    if not warnings:
        return []
    with _WARN_LOCK:
        if _WARNED and not force:
            return warnings
        _WARNED = True
    for item in warnings:
        print(f"arka_llm: warning: {item}", file=__import__("sys").stderr)
    return warnings


def reset_warning_state() -> None:
    global _WARNED
    _WARNED = False


def _load() -> dict[str, Any]:
    path = _cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("incidents", [])
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"incidents": []}


def _save(data: dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_incident(provider: str, model_id: str, kind: str, detail: str = "") -> None:
    data = _load()
    incidents = data.setdefault("incidents", [])
    if not isinstance(incidents, list):
        incidents = []
        data["incidents"] = incidents
    incidents.append(
        {
            "provider": (provider or "").strip().lower(),
            "model": (model_id or "").strip(),
            "kind": (kind or "error").strip().lower(),
            "detail": (detail or "")[:300],
            "at": time.time(),
        }
    )
    data["incidents"] = incidents[-_MAX_INCIDENTS:]
    _save(data)
    if kind in {"timeout", "rate_limit", "retired", "deprecated"}:
        threading.Thread(
            target=_background_status_search,
            args=((provider or "").strip().lower(), kind),
            daemon=True,
        ).start()


def recent_notes(*, limit: int = 8) -> list[str]:
    notes: list[str] = []
    for row in reversed(_load().get("incidents") or []):
        if not isinstance(row, dict):
            continue
        notes.append(
            f"{row.get('kind', 'error')} {row.get('provider', '?')}/{row.get('model', '?')}: {row.get('detail', '')}"
        )
        if len(notes) >= limit:
            break
    hint = (_load().get("status_hint") or "").strip()
    if hint:
        notes.append(f"status search: {hint}")
    return notes


def doctor_lines() -> list[str]:
    lines = [f"  {item}" for item in inspect_config()]
    notes = recent_notes(limit=3)
    if notes:
        lines.append("  LLM drift:      recent provider incidents (rate limit / timeout / retired)")
        lines.append("                  run: arka self improve llm fallback")
    return lines


def _background_status_search(provider: str, kind: str) -> None:
    if os.environ.get("ARKA_PROVIDER_STATUS_SEARCH", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    data = _load()
    last = float(data.get("searched_at") or 0)
    if time.time() - last < 6 * 3600:
        return
    query = f"{provider} api {kind} model deprecation rate limit 2026"
    hint = ""
    try:
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen

        params = urlencode({"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
        req = Request(
            f"https://api.duckduckgo.com/?{params}",
            headers={"User-Agent": "arka-provider-health/1.0"},
        )
        with urlopen(req, timeout=2.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        hint = str(payload.get("AbstractText") or payload.get("Answer") or "").strip()
        if not hint:
            related = payload.get("RelatedTopics") or []
            if related and isinstance(related[0], dict):
                hint = str(related[0].get("Text") or "").strip()
    except Exception:
        hint = ""
    data = _load()
    data["searched_at"] = time.time()
    data["status_query"] = query
    if hint:
        data["status_hint"] = hint[:400]
    _save(data)
