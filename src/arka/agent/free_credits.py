"""Guide newcomers to maximize free AI credits when using Arka."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass

try:
    from arka.paths import env_file, load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def env_file():
        from pathlib import Path

        return Path.home() / ".config" / "arka" / ".env"


_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"free[- ]credits?|"
    r"free\s+(?:ai\s+)?credits?|"
    r"maximize\s+free\s+credits?|"
    r"free\s+tier\s+setup|"
    r"use\s+arka\s+without\s+pay(?:ing|ment)?|"
    r"learn\s+free\s+(?:ai\s+)?providers?|"
    r"how\s+to\s+get\s+free\s+(?:ai\s+)?credits?|"
    r"zero[- ]cost\s+(?:ai|llm)|"
    r"free\s+llm\s+(?:setup|providers?|keys?)|"
    r"setup\s+free\s+(?:ai\s+)?(?:api\s+)?keys?"
    r")\b"
)


@dataclass(frozen=True)
class ProviderGuide:
    slug: str
    label: str
    env_vars: tuple[str, ...]
    signup: str
    note: str


FREE_PROVIDERS: tuple[ProviderGuide, ...] = (
    ProviderGuide(
        "gemini",
        "Google Gemini",
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "https://aistudio.google.com/apikey",
        "Generous free tier; default failover chain starts here.",
    ),
    ProviderGuide(
        "groq",
        "Groq",
        ("GROQ_API_KEY",),
        "https://console.groq.com/keys",
        "Fast Llama models with a free tier.",
    ),
    ProviderGuide(
        "openrouter",
        "OpenRouter",
        ("OPENROUTER_API_KEY",),
        "https://openrouter.ai/keys",
        "One key unlocks many models, including :free variants.",
    ),
    ProviderGuide(
        "ollama",
        "Ollama (local)",
        ("OLLAMA_HOST",),
        "https://ollama.com — then: ollama pull llama3.2:1b",
        "Zero API cost when running models on your machine.",
    ),
)


def is_free_credits_request(cmd: str) -> bool:
    clean = (cmd or "").strip()
    if not clean:
        return False
    if re.search(r"(?i)^free_credits\b", clean):
        return True
    return bool(_TRIGGER_RE.search(clean))


def route_command(cmd: str) -> str | None:
    if is_free_credits_request(cmd):
        return "free_credits"
    return None


def _provider_configured(slug: str) -> bool:
    try:
        from arka.llm.fallback import provider_available

        return provider_available(slug)
    except ImportError:
        return False


def _key_count(slug: str) -> int:
    try:
        from arka.llm.api_keys import collect_provider_keys

        return len(collect_provider_keys(slug))
    except ImportError:
        return 0


def _env_flag(name: str, *, default: str = "") -> str:
    val = (os.environ.get(name) or default).strip()
    return val or "(not set)"


def _status_icon(ok: bool) -> str:
    return "✓" if ok else "○"


def provider_status_lines() -> list[str]:
    lines: list[str] = []
    for spec in FREE_PROVIDERS:
        ok = _provider_configured(spec.slug)
        keys = _key_count(spec.slug) if ok else 0
        if ok and keys > 1:
            detail = f"{keys} keys"
        elif ok:
            detail = "configured"
        else:
            detail = f"add {spec.env_vars[0]}"
        lines.append(f"  {_status_icon(ok)} {spec.label:<18} {detail}")
    return lines


def run_guide(*, stream=None) -> int:
    out = stream or sys.stdout
    route_mode = (os.environ.get("ROUTE_MODE") or "symbolic").strip() or "symbolic"
    pref_provider = (os.environ.get("AI_PREFERRED_PROVIDER") or os.environ.get("LLM_PROVIDER") or "").strip()
    pref_model = (os.environ.get("AI_PREFERRED_MODEL") or os.environ.get("LLM_MODEL") or "").strip()
    rotation = (os.environ.get("API_KEY_ROTATION") or "1").strip().lower() not in {"0", "false", "no", "off"}
    auto_fallback = (os.environ.get("LLM_AUTO_FALLBACK") or "1").strip().lower() not in {"0", "false", "no", "off"}
    env_path = env_file()

    print("", file=out)
    print("Free AI credits — quick setup guide", file=out)
    print("=" * 40, file=out)

    print("\nYour providers", file=out)
    for line in provider_status_lines():
        print(line, file=out)

    print("\nYour settings", file=out)
    print(f"  Config file:     {env_path}", file=out)
    print(f"  ROUTE_MODE:      {route_mode}", file=out)
    if pref_provider:
        pref = f"{pref_provider} → {pref_model}" if pref_model else pref_provider
        print(f"  Preferred LLM:   {pref}", file=out)
    print(f"  Key rotation:    {'on' if rotation else 'off'}", file=out)
    print(f"  Auto failover:   {'on' if auto_fallback else 'off'}", file=out)

    print("\n1. Get free API keys", file=out)
    for i, spec in enumerate(FREE_PROVIDERS[:3], start=1):
        print(f"   {i}. {spec.label}: {spec.signup}", file=out)
        print(f"      {spec.note}", file=out)
    print("   Local option: install Ollama and pull a small model (llama3.2:1b, qwen3:8b).", file=out)

    print("\n2. Add keys to your .env", file=out)
    print(f"   Edit: {env_path}", file=out)
    print("   Minimum (pick one or more):", file=out)
    print("     GEMINI_API_KEY=...", file=out)
    print("     GROQ_API_KEY=...", file=out)
    print("     OPENROUTER_API_KEY=...", file=out)
    print("   Stretch free quota with backup keys:", file=out)
    print("     GEMINI_API_KEYS=key2,key3", file=out)
    print("     GROQ_API_KEY_2=backup_key", file=out)

    print("\n3. Save tokens on routing", file=out)
    print("   Add to .env:", file=out)
    print("     ROUTE_MODE=symbolic", file=out)
    print("     LLM_AUTO_FALLBACK=1", file=out)
    print("     API_KEY_ROTATION=1", file=out)
    print("   symbolic routes most skills locally; the LLM only picks skill names.", file=out)

    print("\n4. Tune models for your machine", file=out)
    print("   arka select best model for my pc", file=out)
    print("   select_model --apply", file=out)
    print("   Or set: AI_PREFERRED_PROVIDER=gemini", file=out)
    print("           AI_PREFERRED_MODEL=gemini-2.0-flash", file=out)

    print("\n5. Verify setup", file=out)
    print("   arka setup          # venv + dependencies", file=out)
    print("   arka doctor         # providers, fish, venv", file=out)
    print("   arka ai-models      # live model list", file=out)

    print("\nTips", file=out)
    print("  • Failover order: Gemini Flash → Groq Llama → Ollama (see docs/concepts/llm).", file=out)
    print("  • OpenRouter free models include google/gemini-2.0-flash-exp:free.", file=out)
    print("  • Context7 (CONTEXT7_API_KEY) is optional MCP docs lookup — not your chat LLM.", file=out)
    print("  • Reset exhausted models: python3 arka_llm.py reset-exhaustion", file=out)
    print("", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Free AI credits setup guide for Arka")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to free_credits command")
    p_route.add_argument("text", nargs="+")

    p_is = sub.add_parser("is-request", help="True if text is a free-credits guide request")
    p_is.add_argument("text", nargs="+")

    sub.add_parser("show", help="Print the setup guide (default)")

    args = parser.parse_args(argv)
    text = " ".join(getattr(args, "text", []) or []).strip()

    if args.cmd == "route":
        hit = route_command(text)
        if hit:
            print(hit)
        return 0
    if args.cmd == "is-request":
        print("yes" if is_free_credits_request(text) else "no")
        return 0
    if args.cmd in (None, "show"):
        return run_guide()
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
