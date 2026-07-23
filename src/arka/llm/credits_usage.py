"""Terminal report for LLM/API credit usage and provider status."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
from typing import TextIO

from arka.llm.api_keys import collect_provider_keys, iter_provider_keys, key_rotation_label, provider_has_keys, rotation_enabled
from arka.llm.fallback import EXHAUSTION, env, llm_doctor_lines, ordered_model_candidates, provider_available
from arka.llm.providers import get_provider, provider_specs

_CREDITS_USAGE_RE = re.compile(
    r"(?i)\b("
    r"(?:ai\s+)?credits?\s+usage|"
    r"usage\s+(?:of\s+)?(?:ai\s+)?credits?|"
    r"show\s+(?:my\s+)?(?:arka\s+)?(?:ai\s+)?credits?(?:\s+usage)?|"
    r"(?:llm|api)\s+credits?\s+usage|"
    r"check\s+(?:my\s+)?(?:ai\s+)?credits?\s+usage"
    r")\b"
)

_CORE_PROVIDERS = ("gemini", "groq", "openrouter", "ollama")
_NETWORK_TIMEOUT = 2.5


def is_credits_usage_request(cmd: str) -> bool:
    clean = (cmd or "").strip()
    if not clean:
        return False
    if re.search(r"(?i)^credits?\s+usage\b", clean):
        return True
    if re.search(r"(?i)^usage\s+credits?\b", clean):
        return True
    return bool(_CREDITS_USAGE_RE.search(clean))


def route_command(cmd: str) -> str | None:
    if not is_credits_usage_request(cmd):
        return None
    try:
        from arka.agent.free_credits import is_free_credits_request

        if is_free_credits_request(cmd) and not re.search(r"(?i)\busage\b", cmd):
            return None
    except ImportError:
        pass
    return "credits usage"


def _status_icon(ok: bool) -> str:
    return "✓" if ok else "○"


def _provider_configured_offline(slug: str) -> bool:
    """Key/env presence only — no live server or model-list probes."""
    slug = slug.lower()
    if slug in {"gemini", "groq", "openrouter", "openai", "anthropic"}:
        if provider_has_keys(slug):
            return True
        if slug == "gemini" and env("GOOGLE_API_KEY"):
            return True
        return False
    if slug == "ollama":
        return bool(shutil.which("ollama"))
    return provider_has_keys(slug)


def provider_key_lines(*, live: bool = False) -> list[str]:
    lines: list[str] = []
    for slug in _CORE_PROVIDERS:
        spec = next((s for s in provider_specs() if s.slug == slug), None)
        if spec is None:
            continue
        ok = provider_available(slug) if live else _provider_configured_offline(slug)
        keys = collect_provider_keys(slug) if ok else []
        if ok and len(keys) > 1:
            detail = f"{len(keys)} keys"
            if rotation_enabled():
                label = key_rotation_label(slug)
                if label:
                    detail = f"{detail}, {label}"
        elif ok:
            detail = "configured"
        else:
            detail = f"add {spec.env_keys[0]}"
        lines.append(f"  {_status_icon(ok)} {spec.display_name:<18} {detail}")
    return lines


def session_exhausted_lines() -> list[str]:
    exhausted = EXHAUSTION.list_exhausted()
    if not exhausted:
        return ["  (none — all configured models are ready this session)"]
    lines: list[str] = []
    for provider, model_id in sorted(exhausted):
        lines.append(f"  {provider}/{model_id}")
    return lines


def offline_model_candidates() -> list[tuple[str, str]]:
    """Env/catalog candidates only — no live provider APIs."""
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []

    def add(provider: str, model_id: str) -> None:
        if not provider or not model_id:
            return
        key = (provider.lower(), model_id)
        if key in seen:
            return
        seen.add(key)
        ordered.append(key)

    pref_provider = (env("AI_PREFERRED_PROVIDER") or env("LLM_PROVIDER")).lower()
    pref_model = env("AI_PREFERRED_MODEL") or env("LLM_MODEL")
    if pref_provider and pref_model:
        add(pref_provider, pref_model)

    for slug in _CORE_PROVIDERS:
        if not _provider_configured_offline(slug):
            continue
        spec = get_provider(slug)
        if spec is None:
            continue
        models = list(spec.default_models or [])
        if spec.default_model:
            models.insert(0, spec.default_model)
        for model_id in models:
            add(slug, model_id)

    for provider, model_id in EXHAUSTION.list_exhausted():
        add(provider, model_id)

    return ordered


def fallback_chain_summary(
    *,
    include_all: bool = True,
    live: bool = False,
) -> tuple[list[str], dict[str, int]]:
    counts = {"ready": 0, "exhausted": 0, "skip": 0}
    lines: list[str] = []
    candidates = ordered_model_candidates() if live else offline_model_candidates()
    configured = provider_available if live else _provider_configured_offline
    for provider, model_id in candidates:
        if not include_all:
            if not configured(provider):
                continue
            if EXHAUSTION.exhausted(provider, model_id):
                continue
        ok = configured(provider)
        mark = "ok" if ok else "skip"
        ex = "exhausted" if EXHAUSTION.exhausted(provider, model_id) else "ready"
        if mark == "skip":
            counts["skip"] += 1
        elif ex == "exhausted":
            counts["exhausted"] += 1
        else:
            counts["ready"] += 1
        lines.append(f"  {provider}\t{model_id}\t{mark}\t{ex}")
    return lines, counts


def llm_settings_lines(*, live: bool = False) -> list[str]:
    if live:
        return llm_doctor_lines()

    configured = [slug for slug in _CORE_PROVIDERS if _provider_configured_offline(slug)]
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
        lines.append(f"  Preferred:      {pref} → {pref_model}")
    elif _provider_configured_offline("openrouter") and not any(
        _provider_configured_offline(slug) for slug in ("gemini", "groq")
    ):
        spec = get_provider("openrouter")
        default = spec.default_model if spec else "meta-llama/llama-3.3-70b-instruct"
        lines.append(f"  Preferred:      openrouter → {default} (auto — only cloud key)")
    lines.append(f"  Auto failover:  {env('LLM_AUTO_FALLBACK', '1')}")
    return lines


def skill_usage_lines() -> list[str]:
    try:
        from arka.core.skill_usage import report
    except ImportError:
        return ["  (skill usage tracking unavailable)"]
    payload = report()
    if not payload["total"]:
        return ["  (no skill invocations recorded yet)"]
    lines = [f"  Total invocations: {payload['total']}"]
    for skill, count in payload["skills"][:10]:
        lines.append(f"  {skill}: {count}")
    if len(payload["skills"]) > 10:
        lines.append(f"  … and {len(payload['skills']) - 10} more")
    return lines


def fetch_openrouter_balance(*, timeout: float = _NETWORK_TIMEOUT) -> dict[str, object] | None:
    keys = iter_provider_keys("openrouter")
    if not keys:
        return None
    for key in keys:
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {key}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode())
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                return data
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            if key != keys[-1]:
                continue
    return None


def openrouter_balance_line(*, check_balance: bool) -> str | None:
    if not check_balance or not _provider_configured_offline("openrouter"):
        return None
    data = fetch_openrouter_balance()
    if not data:
        return "  OpenRouter balance: unavailable (check key or network)"
    usage = data.get("usage")
    limit = data.get("limit")
    free_tier = data.get("is_free_tier")
    parts: list[str] = []
    if usage is not None:
        parts.append(f"usage ${float(usage):.4f}")
    if limit is not None:
        parts.append(f"limit ${float(limit):.4f}")
    elif limit is None and usage is not None:
        parts.append("limit unlimited")
    if free_tier is not None:
        parts.append("free tier" if free_tier else "paid tier")
    if not parts:
        return None
    return "  OpenRouter balance: " + ", ".join(parts)


def setup_hint_lines(*, llm_configured: bool, live: bool = False) -> list[str]:
    hints: list[str] = []
    if not llm_configured:
        hints.append("arka free_credits                  # free API key setup guide")
    hints.append("arka doctor                        # full environment check")
    if not live:
        hints.append("arka credits usage --live        # live balance + full fallback chain")
        hints.append("arka credits usage --balance     # OpenRouter balance only")
    hints.append("python3 bin/arka_llm.py reset      # clear session exhaustion")
    hints.append("python3 bin/arka_llm.py models --all  # full fallback chain")
    return hints


def run_report(
    *,
    stream: TextIO | None = None,
    include_skills: bool = True,
    include_chain: bool = False,
    check_balance: bool = False,
    live: bool = False,
) -> int:
    out = stream or sys.stdout
    llm_configured = any(_provider_configured_offline(slug) for slug in _CORE_PROVIDERS)

    print("", file=out)
    print("Arka credits usage", file=out)
    print("=" * 40, file=out)

    print("\nConfigured providers", file=out)
    for line in provider_key_lines(live=live):
        print(line, file=out)

    balance_line = openrouter_balance_line(check_balance=check_balance)
    if balance_line:
        print(balance_line, file=out)

    print("\nLLM settings", file=out)
    for line in llm_settings_lines(live=live):
        print(line, file=out)

    print("\nSession-exhausted models", file=out)
    for line in session_exhausted_lines():
        print(line, file=out)

    if include_chain:
        chain_lines, counts = fallback_chain_summary(include_all=True, live=live)
        total = sum(counts.values())
        chain_label = "Fallback chain" if live else "Fallback chain (offline)"
        print(f"\n{chain_label} ({total} candidates)", file=out)
        print(
            f"  ready: {counts['ready']}  exhausted: {counts['exhausted']}  skip (no key): {counts['skip']}",
            file=out,
        )
        if chain_lines:
            print("  provider\tmodel\tconfigured\tstatus", file=out)
            for line in chain_lines[:40]:
                print(line, file=out)
            if len(chain_lines) > 40:
                suffix = " --live" if not live else ""
                print(
                    f"  … {len(chain_lines) - 40} more (run: arka credits usage --chain{suffix} "
                    "or python3 bin/arka_llm.py models --all)",
                    file=out,
                )

    if include_skills:
        print("\nSkill invocations (local counters)", file=out)
        for line in skill_usage_lines():
            print(line, file=out)

    print("\nNext steps", file=out)
    for hint in setup_hint_lines(llm_configured=llm_configured, live=live):
        print(f"  {hint}", file=out)

    return 0


def _resolve_report_flags(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="arka credits usage", description="LLM/API credits and provider status")
    parser.add_argument("--live", action="store_true", help="live API checks: balance, model lists, full chain")
    parser.add_argument("--balance", action="store_true", help="fetch OpenRouter balance (implies network)")
    parser.add_argument("--chain", action="store_true", help="show fallback chain (offline unless --live)")
    parser.add_argument("--no-skills", action="store_true", help="omit local skill invocation counters")
    parser.add_argument("--no-chain", action="store_true", help="omit fallback chain listing")
    parser.add_argument("--no-balance", action="store_true", help="skip OpenRouter balance lookup")
    args = parser.parse_args(argv)
    if args.no_balance:
        args.balance = False
    if args.live:
        args.balance = True
        args.chain = True
    return args


def main(argv: list[str] | None = None) -> int:
    args = _resolve_report_flags(argv)
    return run_report(
        include_skills=not args.no_skills,
        include_chain=(args.chain or args.live) and not args.no_chain,
        check_balance=args.balance and not args.no_balance,
        live=args.live,
    )


__all__ = [
    "fetch_openrouter_balance",
    "is_credits_usage_request",
    "llm_settings_lines",
    "main",
    "offline_model_candidates",
    "route_command",
    "run_report",
]
