#!/usr/bin/env python3
"""Detect, persist, and auto-remediate retired LLM models (HTTP 410, etc.)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_RETIRED_FILE_NAME = "llm-retired-models.json"
_LOCK = threading.Lock()

# Seed known retirements so we skip them before the first failed call.
_KNOWN_RETIRED: set[tuple[str, str]] = {
    ("ollama", "minimax-m2.5:cloud"),
    ("ollama", "minimax-m2.5"),
    ("ollama", "minimax-m2:cloud"),
}

_CONFIG_KEYS = (
    "AI_PREFERRED_MODEL",
    "LLM_MODEL",
    "OLLAMA_CHAT_MODEL",
    "CHAT_MODEL",
    "PDF_RAG_MODEL",
)


def _cache_path() -> Path:
    try:
        from arka.paths import cache_dir

        return cache_dir() / _RETIRED_FILE_NAME
    except ImportError:
        return Path.home() / ".cache" / "fish-agent" / _RETIRED_FILE_NAME


def _enabled() -> bool:
    return os.environ.get("LLM_AUTO_RETIRED_FIX", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def is_retired_model_error(msg: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b410\b|\b(?:retired|deprecated|shut\s*down|no longer available)\b",
            str(msg or ""),
        )
    )


def _normalize_key(provider: str, model_id: str) -> tuple[str, str]:
    provider = (provider or "").strip().lower()
    model = (model_id or "").strip()
    if provider == "gemini":
        try:
            from arka.llm.fallback import normalize_gemini_model

            model = normalize_gemini_model(model)
        except ImportError:
            pass
    elif provider == "groq":
        try:
            from arka.llm.fallback import normalize_groq_model

            model = normalize_groq_model(model)
        except ImportError:
            pass
    elif provider == "openrouter":
        try:
            from arka.llm.fallback import normalize_openrouter_model

            model = normalize_openrouter_model(model)
        except ImportError:
            pass
    return provider, model


def _load_store() -> dict[str, Any]:
    path = _cache_path()
    if not path.is_file():
        return {"models": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"models": []}
    if not isinstance(data, dict):
        return {"models": []}
    models = data.get("models")
    if not isinstance(models, list):
        data["models"] = []
    return data


def _save_store(data: dict[str, Any]) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def list_retired() -> list[dict[str, str]]:
    with _LOCK:
        rows = list(_load_store().get("models") or [])
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for provider, model in sorted(_KNOWN_RETIRED):
        if (provider, model) not in seen:
            seen.add((provider, model))
            out.append({"provider": provider, "model": model, "source": "known"})
    for row in rows:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "").strip().lower()
        model = str(row.get("model") or row.get("model_id") or "").strip()
        if not provider or not model:
            continue
        key = (provider, model)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "provider": provider,
                "model": model,
                "source": "runtime",
                "reason": str(row.get("reason") or "")[:240],
                "at": str(row.get("at") or ""),
            }
        )
    return out


def is_retired(provider: str, model_id: str) -> bool:
    key = _normalize_key(provider, model_id)
    if key in _KNOWN_RETIRED:
        return True
    with _LOCK:
        for row in _load_store().get("models") or []:
            if not isinstance(row, dict):
                continue
            p = str(row.get("provider") or "").strip().lower()
            m = str(row.get("model") or row.get("model_id") or "").strip()
            if _normalize_key(p, m) == key:
                return True
    return False


def record_retired(provider: str, model_id: str, *, reason: str = "") -> bool:
    """Persist a retired model. Returns True if newly recorded."""
    if not _enabled():
        return False
    provider, model_id = _normalize_key(provider, model_id)
    if not provider or not model_id:
        return False
    if (provider, model_id) in _KNOWN_RETIRED:
        return False
    with _LOCK:
        data = _load_store()
        models = data.setdefault("models", [])
        for row in models:
            if not isinstance(row, dict):
                continue
            if (
                str(row.get("provider") or "").lower() == provider
                and str(row.get("model") or row.get("model_id") or "") == model_id
            ):
                return False
        models.append(
            {
                "provider": provider,
                "model": model_id,
                "reason": (reason or "")[:500],
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        _save_store(data)
        return True


def filter_model_ids(provider: str, model_ids: list[str]) -> list[str]:
    out: list[str] = []
    for model_id in model_ids:
        if model_id and not is_retired(provider, model_id):
            out.append(model_id)
    return out


def filter_chain(chain: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(p, m) for p, m in chain if not is_retired(p, m)]


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _models_match(provider: str, configured: str, retired: str) -> bool:
    if not configured:
        return False
    cp, cm = _normalize_key(provider, configured)
    _, rm = _normalize_key(provider, retired)
    if cm == rm:
        return True
    # Bare model id in env without provider prefix.
    return configured.strip() == retired.strip()


def pick_replacement(provider: str, retired_model: str) -> str | None:
    """Pick the next usable model for a provider, skipping retired entries."""
    provider = (provider or "").strip().lower()
    if not provider:
        return None
    try:
        from arka.llm.provider_select import detect_provider_models, pick_default_model

        models, _source = detect_provider_models(provider, include_live=True)
        models = filter_model_ids(provider, models)
        if not models:
            return None
        preferred = pick_default_model(provider, models)
        if preferred and not is_retired(provider, preferred):
            return preferred
        for model in models:
            if not is_retired(provider, model):
                return model
    except ImportError:
        pass

    try:
        from arka.llm.fallback import (
            DEFAULT_OLLAMA_MODELS,
            gemini_model_ids,
            groq_model_ids,
            ollama_model_ids,
            openrouter_model_ids,
        )

        if provider == "gemini":
            candidates = gemini_model_ids(include_live=True)
        elif provider == "groq":
            candidates = groq_model_ids(include_live=True)
        elif provider == "ollama":
            candidates = ollama_model_ids(include_live=True)
        elif provider == "openrouter":
            candidates = openrouter_model_ids(include_live=True)
        else:
            candidates = list(DEFAULT_OLLAMA_MODELS)
        for model in filter_model_ids(provider, candidates):
            if model != retired_model:
                return model
    except ImportError:
        pass
    return None


def _update_env_models(provider: str, retired_model: str, replacement: str) -> list[str]:
    from arka.llm.provider_select import PREFERRED_MODEL_ENV, set_env_vars

    updates: dict[str, str | None] = {}
    changed: list[str] = []

    pref_provider = _env("AI_PREFERRED_PROVIDER") or _env("LLM_PROVIDER")
    pref_provider = pref_provider.lower() if pref_provider else ""

    for key in _CONFIG_KEYS:
        val = _env(key)
        if not val:
            continue
        if key in {PREFERRED_MODEL_ENV, "LLM_MODEL"}:
            if pref_provider and pref_provider != provider.lower():
                continue
            if val.strip() == retired_model.strip() or val.strip() == retired_model.split(":")[0]:
                updates[key] = replacement
                changed.append(key)
            continue
        if provider == "ollama" and (key.startswith("OLLAMA") or key == "CHAT_MODEL"):
            if _models_match(provider, val, retired_model):
                updates[key] = replacement
                changed.append(key)

    if not updates:
        return []

    set_env_vars(updates)
    return changed


def auto_remediate_config(
    provider: str,
    model_id: str,
    *,
    reason: str = "",
) -> dict[str, Any] | None:
    """If config/env still points at a retired model, switch to a replacement."""
    if not _enabled():
        return None
    provider, model_id = _normalize_key(provider, model_id)
    record_retired(provider, model_id, reason=reason)
    replacement = pick_replacement(provider, model_id)
    if not replacement:
        return None
    changed = _update_env_models(provider, model_id, replacement)
    if not changed:
        return None
    return {
        "provider": provider,
        "from": model_id,
        "to": replacement,
        "env_keys": changed,
        "reason": (reason or "")[:240],
    }


def ensure_config_not_retired() -> list[dict[str, Any]]:
    """Proactively replace retired models referenced in env/config."""
    if not _enabled():
        return []
    remediated: list[dict[str, Any]] = []
    pref_provider = _env("AI_PREFERRED_PROVIDER") or _env("LLM_PROVIDER")
    pref_model = _env("AI_PREFERRED_MODEL") or _env("LLM_MODEL")
    if pref_provider and pref_model and is_retired(pref_provider, pref_model):
        hit = auto_remediate_config(pref_provider, pref_model, reason="configured preferred model retired")
        if hit:
            remediated.append(hit)

    ollama_model = _env("OLLAMA_CHAT_MODEL")
    if ollama_model and is_retired("ollama", ollama_model):
        hit = auto_remediate_config("ollama", ollama_model, reason="OLLAMA_CHAT_MODEL retired")
        if hit:
            remediated.append(hit)
    return remediated


def handle_retired_model_error(
    provider: str,
    model_id: str,
    err_text: str,
    *,
    store: Any | None = None,
    verbose: bool = False,
) -> dict[str, Any] | None:
    """Record retirement, mark exhaustion, and auto-update config when possible."""
    if not is_retired_model_error(err_text):
        return None
    provider, model_id = _normalize_key(provider, model_id)
    record_retired(provider, model_id, reason=err_text)
    if store is not None:
        with store._lock:
            store._exhausted.add((provider, model_id))
    remediated = auto_remediate_config(provider, model_id, reason=err_text)
    if remediated:
        msg = (
            f"arka_llm: auto-replaced retired model {provider}/{remediated['from']} "
            f"→ {remediated['to']} ({', '.join(remediated['env_keys'])})"
        )
        print(msg, file=__import__("sys").stderr)
    elif verbose:
        print(f"arka_llm: skip retired model {provider}/{model_id}", file=__import__("sys").stderr)
    return remediated
