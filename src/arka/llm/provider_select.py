#!/usr/bin/env python3
"""Preferred LLM provider selection with live model autodetection."""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from arka.llm.fallback import (
    EXHAUSTION,
    env,
    fetch_gemini_models_live,
    fetch_groq_models_live,
    fetch_ollama_models_live,
    fetch_openrouter_models_live,
    gemini_model_ids,
    groq_model_ids,
    normalize_gemini_model,
    normalize_groq_model,
    normalize_openrouter_model,
    ollama_model_ids,
    openrouter_model_ids,
    pick_openrouter_default_model,
    provider_available,
)
from arka.llm.providers import (
    PROVIDER_SLUG_ALIASES,
    ProviderSpec,
    get_provider,
    provider_api_key,
    provider_base_url,
    provider_catalog_models,
    provider_model_ids,
    provider_specs,
)
from arka.paths import config_dir, env_file

PREFERRED_PROVIDER_ENV = "AI_PREFERRED_PROVIDER"
PREFERRED_MODEL_ENV = "AI_PREFERRED_MODEL"

_SET_PROVIDER_RE = re.compile(
    r"(?i)\b(?:set|choose|select|switch)\s+(?:the\s+)?(?:preferred\s+)?"
    r"(?:ai\s+|llm\s+)?provider\s+(?:to\s+)?([\w-]+)\b"
)
_MODELS_ON_RE = re.compile(
    r"(?i)(?:what\s+)?models?\s+(?:are\s+)?(?:available\s+)?(?:on|for|from)\s+([\w-]+)\b"
)
_LIST_PROVIDERS_RE = re.compile(
    r"(?i)\b(?:list|show)\s+(?:available\s+)?(?:ai\s+|llm\s+)?providers?\b"
)
_SHOW_PREF_RE = re.compile(
    r"(?i)\b(?:show|what\s+is|get)\s+(?:my\s+)?(?:preferred\s+)?(?:ai\s+|llm\s+)?provider\b"
)
_EXPLICIT_MODEL_SET_RE = re.compile(
    r"(?i)^(?:select|use|switch)\s+(?:to\s+)?(?:model\s+)?(?P<model>.+?)\s*$"
)
_HARDWARE_ADVISOR_HINTS = re.compile(
    r"(?i)\b(?:best|for\s+my|for\s+this|hardware|pc|mac|laptop|computer|machine|"
    r"resources|optimize|recommend|should\s+i\s+use|my\s+pc)\b"
)
_MODEL_ID_LIKE = re.compile(
    r"(?i)(?:claude|gpt|gemini|llama|qwen|mistral|grok|deepseek|sonnet|haiku|opus|"
    r"mixtral|phi|codestral|command-|sonar|venice|moonshot|kimi|glm|abab|o1|o3|nano)"
)


@dataclass
class ProviderRow:
    slug: str
    display_name: str
    configured: bool
    default_model: str
    env_keys: tuple[str, ...]


def normalize_provider_slug(raw: str) -> str:
    slug = (raw or "").strip().lower()
    return PROVIDER_SLUG_ALIASES.get(slug, slug)


def get_preferred() -> tuple[str, str]:
    provider = normalize_provider_slug(env(PREFERRED_PROVIDER_ENV) or env("LLM_PROVIDER"))
    model = env(PREFERRED_MODEL_ENV) or env("LLM_MODEL")
    return provider, model


def _read_env_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def set_env_vars(updates: dict[str, str | None]) -> Path:
    """Persist env keys to ~/.config/arka/.env (None removes a key)."""
    config_dir().mkdir(parents=True, exist_ok=True)
    path = env_file()
    remove_keys = {k for k, v in updates.items() if v is None}
    set_keys = {k: v for k, v in updates.items() if v is not None}

    kept: list[str] = []
    for line in _read_env_lines(path):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            kept.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remove_keys or key in set_keys:
            continue
        kept.append(line)

    while kept and not kept[-1].strip():
        kept.pop()

    for key, val in set_keys.items():
        kept.append(f"{key}={val}")

    text = "\n".join(kept)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")

    for key, val in set_keys.items():
        os.environ[key] = val
    for key in remove_keys:
        os.environ.pop(key, None)
    return path


def list_provider_rows() -> list[ProviderRow]:
    rows: list[ProviderRow] = []
    for spec in provider_specs():
        rows.append(
            ProviderRow(
                slug=spec.slug,
                display_name=spec.display_name,
                configured=provider_available(spec.slug),
                default_model=spec.default_model,
                env_keys=spec.env_keys,
            )
        )
    return rows


def _fetch_openai_compat_models_live(spec: ProviderSpec, *, force: bool = False) -> list[str]:
    if spec.kind not in {"openai_compatible", "local_openai"}:
        return []
    base = provider_base_url(spec)
    if not base:
        return []
    api_key = provider_api_key(spec)
    if not api_key and spec.kind != "local_openai":
        return []
    url = f"{base.rstrip('/')}/models"
    try:
        headers = {"Authorization": f"Bearer {api_key or 'EMPTY'}"}
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = __import__("json").loads(resp.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, urllib.error.HTTPError):
        return []

    models: list[str] = []
    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "").strip()
        if mid and mid not in models:
            models.append(mid)
    if spec.default_model and spec.default_model in models:
        models.remove(spec.default_model)
        models.insert(0, spec.default_model)
    return models


def _catalog_models_for_provider(slug: str) -> list[str]:
    spec = get_provider(slug)
    if slug == "gemini":
        return gemini_model_ids(include_live=False)
    if slug == "groq":
        return groq_model_ids(include_live=False)
    if slug == "ollama":
        return ollama_model_ids(include_live=False)
    if slug == "openrouter":
        return openrouter_model_ids(include_live=False)
    if spec:
        return provider_model_ids(spec) or provider_catalog_models(spec)
    return []


def _merge_live_and_catalog(live: list[str], catalog: list[str]) -> list[str]:
    seen = set(live)
    merged = list(live)
    for model_id in catalog:
        if model_id not in seen:
            seen.add(model_id)
            merged.append(model_id)
    return merged


def _filter_exhausted_models(provider: str, models: list[str]) -> list[str]:
    slug = normalize_provider_slug(provider)
    return [mid for mid in models if not EXHAUSTION.exhausted(slug, mid)]


def detect_provider_models(
    provider: str,
    *,
    include_live: bool = True,
    force: bool = False,
    include_all: bool = False,
    exclude_exhausted: bool = True,
) -> tuple[list[str], str]:
    """Return (model_ids, source) where source is ``live``, ``catalog``, or ``live+catalog``."""
    slug = normalize_provider_slug(provider)
    spec = get_provider(slug)
    if not spec:
        return [], "catalog"

    if slug == "gemini":
        if include_live:
            live = fetch_gemini_models_live(force=force)
            if live and not include_all:
                models = list(live)
                source = "live"
            elif live and include_all:
                models = _merge_live_and_catalog(live, _catalog_models_for_provider(slug))
                source = "live+catalog"
            else:
                models = gemini_model_ids(include_live=False)
                source = "catalog"
        else:
            models = gemini_model_ids(include_live=False)
            source = "catalog"
        if exclude_exhausted:
            models = _filter_exhausted_models(slug, models)
        return models, source

    if slug == "groq":
        if include_live:
            live = fetch_groq_models_live(force=force)
            if live and not include_all:
                models = list(live)
                source = "live"
            elif live and include_all:
                models = _merge_live_and_catalog(live, _catalog_models_for_provider(slug))
                source = "live+catalog"
            else:
                models = groq_model_ids(include_live=False)
                source = "catalog"
        else:
            models = groq_model_ids(include_live=False)
            source = "catalog"
        if exclude_exhausted:
            models = _filter_exhausted_models(slug, models)
        return models, source

    if slug == "ollama":
        if include_live:
            live = fetch_ollama_models_live(force=force)
            if live and not include_all:
                models = list(live)
                source = "live"
            elif live and include_all:
                models = _merge_live_and_catalog(live, _catalog_models_for_provider(slug))
                source = "live+catalog"
            else:
                models = ollama_model_ids(include_live=False)
                source = "catalog"
        else:
            models = ollama_model_ids(include_live=False)
            source = "catalog"
        if exclude_exhausted:
            models = _filter_exhausted_models(slug, models)
        return models, source

    if slug == "openrouter":
        if include_live:
            live = fetch_openrouter_models_live(force=force)
            if live and not include_all:
                models = list(live)
                source = "live"
            elif live and include_all:
                models = _merge_live_and_catalog(live, _catalog_models_for_provider(slug))
                source = "live+catalog"
            else:
                models = openrouter_model_ids(include_live=False)
                source = "catalog"
        else:
            models = openrouter_model_ids(include_live=False)
            source = "catalog"
        if exclude_exhausted:
            models = _filter_exhausted_models(slug, models)
        return models, source

    if include_live:
        live = _fetch_openai_compat_models_live(spec, force=force)
        if live:
            models = live
            source = "live"
            if include_all:
                models = _merge_live_and_catalog(live, _catalog_models_for_provider(slug))
                source = "live+catalog"
            if exclude_exhausted:
                models = _filter_exhausted_models(slug, models)
            return models, source
    catalog = provider_model_ids(spec) or provider_catalog_models(spec)
    if exclude_exhausted:
        catalog = _filter_exhausted_models(slug, catalog)
    return catalog, "catalog"


def pick_default_model(provider: str, models: list[str]) -> str:
    if not models:
        spec = get_provider(normalize_provider_slug(provider))
        return spec.default_model if spec else ""
    slug = normalize_provider_slug(provider)
    if slug == "openrouter":
        return pick_openrouter_default_model(models)
    spec = get_provider(slug)
    if spec and spec.default_model in models:
        return spec.default_model
    return models[0]


def normalize_model_for_provider(provider: str, model_id: str) -> str:
    slug = normalize_provider_slug(provider)
    mid = (model_id or "").strip()
    if not mid:
        return mid
    if slug == "gemini":
        return normalize_gemini_model(mid)
    if slug == "groq":
        return normalize_groq_model(mid)
    if slug == "openrouter":
        return normalize_openrouter_model(mid)
    return mid


def set_preferred_provider(
    provider: str,
    *,
    model: str | None = None,
    autodetect: bool = True,
    force_refresh: bool = False,
) -> tuple[str, str, Path]:
    slug = normalize_provider_slug(provider)
    spec = get_provider(slug)
    if not spec:
        raise ValueError(f"Unknown provider: {provider!r}")

    chosen_model = (model or "").strip()
    if not chosen_model and autodetect:
        models, _source = detect_provider_models(slug, force=force_refresh)
        chosen_model = pick_default_model(slug, models)
    if not chosen_model:
        chosen_model = spec.default_model
    if slug == "openrouter" and autodetect and not model:
        live = fetch_openrouter_models_live(force=force_refresh)
        chosen_model = normalize_openrouter_model(chosen_model)
        if live and chosen_model not in live:
            chosen_model = pick_default_model(slug, live)

    chosen_model = normalize_model_for_provider(slug, chosen_model)
    path = set_env_vars(
        {
            PREFERRED_PROVIDER_ENV: slug,
            PREFERRED_MODEL_ENV: chosen_model,
            "LLM_PROVIDER": None,
            "LLM_MODEL": None,
        }
    )
    return slug, chosen_model, path


def clear_preferred() -> Path:
    return set_env_vars(
        {
            PREFERRED_PROVIDER_ENV: None,
            PREFERRED_MODEL_ENV: None,
        }
    )


def auto_pick_model_if_needed(provider: str | None = None, *, force: bool = False) -> str | None:
    pref_provider, pref_model = get_preferred()
    slug = normalize_provider_slug(provider or pref_provider)
    if not slug:
        return None
    if pref_model and (not provider or provider == pref_provider):
        if slug == "openrouter":
            live = fetch_openrouter_models_live(force=force)
            if live and pref_model not in live:
                chosen = pick_default_model(slug, live)
                set_env_vars({PREFERRED_MODEL_ENV: chosen})
                return chosen
        return pref_model
    models, _source = detect_provider_models(slug, force=force)
    if not models:
        return None
    chosen = pick_default_model(slug, models)
    set_env_vars({PREFERRED_MODEL_ENV: chosen})
    return chosen


def looks_like_model_id(model: str) -> bool:
    raw = (model or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if low in {"model", "llm", "ai"}:
        return False
    if "/" in raw or ":" in raw:
        return True
    if _MODEL_ID_LIKE.search(raw):
        return True
    if re.fullmatch(r"[\w][\w./:-]*[\w]", raw) and "-" in raw:
        return True
    return False


def extract_explicit_model_id(text: str) -> str | None:
    """Return a concrete model id from 'select/use/switch <model>' NL, else None."""
    clean = (text or "").strip()
    if not clean or _HARDWARE_ADVISOR_HINTS.search(clean):
        return None
    if re.search(r"(?i)\bfree\b.*\bmodels?\b|\bmodels?\b.*\bfree\b", clean):
        return None
    match = _EXPLICIT_MODEL_SET_RE.match(clean)
    if not match:
        return None
    model = match.group("model").strip()
    if not looks_like_model_id(model):
        return None
    return model


def is_preferred_model_set_query(text: str) -> bool:
    return extract_explicit_model_id(text) is not None


def resolve_model_set_target(model: str) -> tuple[str, str]:
    """Return (provider_slug, model_id) for set_preferred_provider."""
    from arka.llm.fallback import infer_provider_from_model

    raw = (model or "").strip()
    if "/" in raw and not raw.lower().startswith(("http://", "https://")):
        head, _, tail = raw.partition("/")
        slug = normalize_provider_slug(head)
        if tail and get_provider(slug):
            return slug, tail
    provider = infer_provider_from_model(raw)
    if not provider:
        pref, _ = get_preferred()
        provider = pref or "openrouter"
    return provider, raw


def build_preferred_model_set_command(text: str) -> str | None:
    model = extract_explicit_model_id(text)
    if not model:
        return None
    provider, model_id = resolve_model_set_target(model)
    return f"provider set {provider} --model {model_id}"


def is_provider_select_query(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if clean.lower().startswith("provider "):
        return True
    if is_preferred_model_set_query(clean):
        return True
    patterns = (_SET_PROVIDER_RE, _MODELS_ON_RE, _LIST_PROVIDERS_RE, _SHOW_PREF_RE)
    return any(p.search(clean) for p in patterns)


def nl_to_argv(text: str) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return []

    model = extract_explicit_model_id(clean)
    if model:
        provider, model_id = resolve_model_set_target(model)
        return ["set", provider, "--model", model_id]

    if clean.lower().startswith("provider "):
        return clean.split()[1:]

    m = _SET_PROVIDER_RE.search(clean)
    if m:
        argv = ["set", normalize_provider_slug(m.group(1))]
        model_m = re.search(r"(?i)\bmodel\s+(?:to\s+)?(\S+)", clean)
        if model_m:
            argv.extend(["--model", model_m.group(1)])
        return argv

    m = _MODELS_ON_RE.search(clean)
    if m:
        return ["models", normalize_provider_slug(m.group(1))]

    if _LIST_PROVIDERS_RE.search(clean):
        return ["list"]

    if _SHOW_PREF_RE.search(clean):
        return ["show"]

    return []


def cmd_list(_args: argparse.Namespace) -> int:
    print("slug\tdisplay_name\tconfigured\tdefault_model\tenv_keys")
    for row in list_provider_rows():
        keys = ",".join(row.env_keys[:3])
        ok = "yes" if row.configured else "no"
        print(f"{row.slug}\t{row.display_name}\t{ok}\t{row.default_model}\t{keys}")
    return 0


def cmd_show(_args: argparse.Namespace) -> int:
    provider, model = get_preferred()
    if not provider:
        print("Preferred provider: not set")
        return 0
    models, source = detect_provider_models(provider)
    print(f"provider\t{provider}")
    print(f"model\t{model or '(not set)'}")
    print(f"models_detected\t{len(models)}")
    print(f"models_source\t{source}")
    if model and model not in models and models:
        print("model_valid\tno", file=sys.stderr)
    elif model:
        print("model_valid\tyes")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    provider = normalize_provider_slug(args.provider or get_preferred()[0])
    if not provider:
        print("No preferred provider set. Run: arka provider set <provider>", file=sys.stderr)
        return 1

    models, source = detect_provider_models(
        provider,
        force=bool(args.refresh),
        include_all=bool(getattr(args, "all", False)),
    )
    if not models:
        print(f"No models found for {provider}. Check API keys or run ollama serve.", file=sys.stderr)
        return 1

    auto_saved = ""
    if args.autopick:
        _, pref_model = get_preferred()
        if not pref_model or args.refresh:
            chosen = auto_pick_model_if_needed(provider, force=bool(args.refresh))
            if chosen:
                auto_saved = chosen

    print(f"provider\t{provider}")
    print(f"source\t{source}")
    print(f"count\t{len(models)}")
    if auto_saved:
        print(f"auto_saved\t{auto_saved}")
    for model_id in models:
        current = get_preferred()[1]
        prefix = "current\t" if model_id == current else "model\t"
        print(f"{prefix}{model_id}")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    raw = (args.provider or "").strip()
    if raw.lower() == "clear":
        path = clear_preferred()
        print(f"Cleared preferred provider ({path})")
        return 0

    try:
        slug, model, path = set_preferred_provider(
            raw,
            model=args.model,
            autodetect=not args.model,
            force_refresh=bool(args.refresh),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not args.model:
        auto_pick_model_if_needed(slug, force=bool(args.refresh))

    models, source = detect_provider_models(slug)
    print(f"Saved preferred provider → {slug} / {model}")
    print(f"Config: {path}")
    print(f"Detected {len(models)} model(s) ({source})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preferred LLM provider selection")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List providers and key configuration status")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show preferred provider and detected model count")
    p_show.set_defaults(func=cmd_show)

    p_models = sub.add_parser("models", help="Auto-detect models for preferred provider")
    p_models.add_argument("provider", nargs="?", help="Provider slug (default: preferred)")
    p_models.add_argument("--refresh", action="store_true", help="Bypass live model cache")
    p_models.add_argument(
        "--all",
        action="store_true",
        help="Include static catalog models not in the live list",
    )
    p_models.add_argument(
        "--autopick",
        action="store_true",
        default=True,
        help="Save first detected model when AI_PREFERRED_MODEL is unset (default: on)",
    )
    p_models.add_argument(
        "--no-autopick",
        dest="autopick",
        action="store_false",
        help="Do not auto-save a default model",
    )
    p_models.set_defaults(func=cmd_models)

    p_set = sub.add_parser("set", help="Set preferred provider (optional --model)")
    p_set.add_argument("provider", help="Provider slug or 'clear'")
    p_set.add_argument("--model", "-m", help="Optional model id")
    p_set.add_argument("--refresh", action="store_true", help="Refresh live model list before autodetect")
    p_set.set_defaults(func=cmd_set)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
