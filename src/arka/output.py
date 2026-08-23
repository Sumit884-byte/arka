"""Consistent terminal blocks for Arka CLI output."""

from __future__ import annotations

import re
import time

_BLOCK_RE = re.compile(r"^━━━\s+(.+?)\s+━━━$")

_LAST_ANSWER_DURATION_MS: float | None = None


def set_answer_duration_ms(ms: float | None) -> None:
    global _LAST_ANSWER_DURATION_MS
    _LAST_ANSWER_DURATION_MS = ms


def answer_duration_ms() -> float | None:
    return _LAST_ANSWER_DURATION_MS


def _format_duration(ms: float | None) -> str:
    if ms is None or ms < 0:
        return ""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def active_model_label(*, prefer_last: bool = True) -> str | None:
    try:
        from arka.llm.fallback import llm_last_model, model_label

        if not show_model_enabled():
            return None
        row = llm_last_model()
        if row:
            return f"{row[0]}/{row[1]}"
        return model_label(prefer_last=prefer_last, task="chat")
    except Exception:
        pass
    return None


def response_duration_ms() -> float | None:
    """Prefer total answer wall time; fall back to last LLM call duration."""
    if _LAST_ANSWER_DURATION_MS is not None:
        return _LAST_ANSWER_DURATION_MS
    try:
        from arka.llm.fallback import llm_last_duration_ms

        return llm_last_duration_ms()
    except Exception:
        return None


def format_model_footer(*, model: str | None = None, duration_ms: float | None = None) -> str:
    label = (model or active_model_label() or "").strip()
    if not label:
        return ""
    ms = duration_ms if duration_ms is not None else response_duration_ms()
    timing = _format_duration(ms)
    if timing:
        return f"{label} · {timing}"
    return label


def format_metrics_footer() -> str:
    """Timing + optional judge quality line for answer footers."""
    try:
        from arka.core.output_verify import format_output_metrics_footer

        return format_output_metrics_footer()
    except ImportError:
        return ""


def is_model_identity_question(text: str) -> bool:
    clean = " ".join((text or "").split()).strip().lower()
    if not clean:
        return False
    patterns = (
        r"(?i)\b(which|what)\s+model\s+(are\s+you|is\s+(this|arka|active|it|running)|am\s+i\s+using|do\s+you\s+use)\b",
        r"(?i)\bwhat\s+llm\s+(are\s+you|is\s+(this|active)|am\s+i\s+using)\b",
        r"(?i)\b(which|what)\s+(ai|llm)\s+(model|provider)\s+(are\s+you|is\s+this|am\s+i\s+using)\b",
        r"(?i)^(?:what|which)\s+model\s*\??$",
        r"(?i)\bwho\s+are\s+you\b.*\bmodel\b",
        r"(?i)\bmodel\s+name\s*\??$",
    )
    return any(re.search(p, clean) for p in patterns)


def model_identity_answer() -> str:
    preferred = active_model_label(prefer_last=False)
    last = active_model_label(prefer_last=True)
    lines = [
        "[FROM MEMORY]",
        "",
        "I'm **Arka**, your local AI agent — not a single fixed model.",
    ]
    if last and preferred and last != preferred:
        lines.append(f"- **Last answer:** {last}")
        lines.append(f"- **Preferred (chat):** {preferred}")
    elif last or preferred:
        lines.append(f"- **Model:** {last or preferred}")
    else:
        lines.append("- **Model:** none configured — set `AI_PREFERRED_PROVIDER` and `GEMINI_API_KEY` in `.env`.")
    lines.append("- Change with `arka provider set gemini` or edit `.env`.")
    lines.append("- List models: `arka ai-models`")
    return "\n".join(lines)


def show_model_enabled() -> bool:
    """True unless SHOW_MODEL is explicitly disabled (default on)."""
    import os

    raw = os.environ.get("SHOW_MODEL", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def active_context7_label() -> str | None:
    try:
        from arka.integrations.context7_mcp import context7_usage_label, show_context7_enabled

        if not show_context7_enabled():
            return None
        return context7_usage_label()
    except Exception:
        pass
    return None


def print_section(title: str) -> None:
    """Section header matching print_block style (title only)."""
    print(f"━━━ {(title or 'Arka').strip()} ━━━")
    print()


def show_model_info() -> int:
    """Print which LLM Arka uses (deterministic — no LLM call)."""
    start = time.perf_counter()
    body = model_identity_answer()
    set_answer_duration_ms((time.perf_counter() - start) * 1000)
    print_block("Answer", body)
    return 0


def show_capabilities() -> int:
    """Print a deterministic Arka skills/capabilities summary (no LLM)."""
    from arka.core.capability_router import default_router

    router = default_router()
    names = router.available_skills()
    print_section("Arka Skills")
    print(f"  {len(names)} skills available without fish (bash/zsh/PowerShell).")
    sample = ", ".join(names[:12])
    if sample:
        print(f"  Examples: {sample}")
    print(
        "  I'm Arka. Try: weather, search the web, check repo health, "
        "generate a password, or ask me anything."
    )
    model = active_model_label()
    if model:
        print()
        print(f"  Model for answers: {model}")
    print()
    print("  Full list: arka help")
    return 0


def show_help() -> int:
    """Print full Arka CLI help (commands, categories, setup)."""
    print_section("Arka Help")
    print("Cross-platform AI agent — route plain English to 70+ local skills.")
    print()
    print_section("Install & setup")
    print(
        """  pip install 'arka-agent[chat]'  # web answers, calc, weather
  arka setup                      # config dirs + venv-arka + chat deps
  arka doctor                     # verify install + API keys
  arka refetch [--install]        # git pull + sync bundled (dev checkout)
  arka platform [detect|show]     # cache OS profile (~/.config/arka/platform.json)
  arka reload [--listen] [--dev]  # re-source fish config; --listen restarts mic"""
    )
    print()
    print_section("Everyday usage")
    print(
        """  arka <request>                  # natural language → best skill
  arka capabilities               # voice-friendly skill summary
  arka ask <question>             # web + AI answer
  arka goal <goal>                # autonomous multi-step agent
  arka council "should I learn Rust?"  # multi-persona deliberation
  arka route <request>            # preview routing (no run)
  arka mode [ask|plan|agent|debug]  # operation mode (default: agent)
  arka remind in 30m stretch      # reminder at time"""
    )
    print()
    print_section("LLM & routing")
    print(
        """  arka provider list              # providers with keys configured
  arka provider set openrouter    # set preferred provider + model
  arka ai-models                  # list LLM providers and models
  arka credits usage               # provider keys + token savings summary
  arka tokens usage                # local token ledger + estimated savings
  arka ai-skill-model profiles    # per-skill model choices
  arka route learn "phrase" "skill"  # teach NL → CLI mapping
  arka self improve [target] [--apply]  # analyze + plan codebase fixes"""
    )
    print()
    print_section("Integrations")
    print(
        """  arka google setup | login | gmail --unread | calendar --today
  arka gemini <prompt>            # Google Gemini CLI
  arka fugu <prompt>              # Sakana Fugu multi-agent orchestrator
  arka youtube research <query>   # YouTube search + transcript digest
  arka download <id-or-url>       # YouTube playlist or video
  arka password save|get|set <name>
  arka integration list|status       # show configured providers
  arka hybrid status                 # inspect local + hosted model routes
  arka hybrid run "prompt" --policy parallel
  arka hybrid config local-first      # persist the default policy
  arka integration setup <provider>  # securely configure an integration
  arka connect <provider> --key ...  # short setup alias
  arka integration doctor [--fix]    # diagnose credentials, CLIs, permissions
  arka integration init --config-dir .  # generate project .env.example
  arka code init <folder>         # scoped coding workspace
  arka benchmark run|show|apply   # compare models on sample tasks"""
    )
    print()
    print_section("Platforms")
    print(
        """  Any shell      55+ Python-native skills (bash/zsh/PowerShell — no fish required)
  Fish extras     optional mic/TTS/service loops (listen, speak, wifi)
  Install fish:   macOS brew install fish | Linux apt install fish | Windows scoop install fish

  Docs: https://arka-agent.mintlify.site
  Full command list: README.md in ARKA_HOME"""
    )
    return 0


def _print_indented_body(text: str) -> None:
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped:
            print(f"  {stripped}")
        else:
            print()


def print_block(title: str, body: str, *, model: str | None = None) -> None:
    """Standard answer block: green-style header, indented body, optional model footer."""
    title = (title or "Answer").strip()
    text = (body or "").strip()
    print(f"━━━ {title} ━━━")
    print()
    if text:
        try:
            from arka.core.markdown_style import maybe_style_markdown

            styled = maybe_style_markdown(text)
            if styled != text:
                print(styled)
            else:
                _print_indented_body(text)
        except ImportError:
            _print_indented_body(text)
    label = model if model is not None else format_model_footer()
    metrics = format_metrics_footer()
    docs = active_context7_label()
    if label or metrics or docs:
        print()
    if label:
        print(f"  Model: {label}")
    if metrics:
        print(f"  Quality: {metrics}")
    if docs:
        print(f"  Docs: {docs}")


def parse_block(text: str) -> tuple[str, str] | None:
    """Return (title, body) if text starts with a ━━━ header block."""
    lines = text.splitlines()
    if not lines:
        return None
    m = _BLOCK_RE.match(lines[0].strip())
    if not m:
        return None
    body = "\n".join(lines[1:]).strip()
    body = re.sub(r"^\s{2}", "", body, flags=re.MULTILINE)
    body = re.sub(r"\n\s*Model:.*$", "", body, flags=re.S).strip()
    body = re.sub(r"\n\s*Quality:.*$", "", body, flags=re.S).strip()
    body = re.sub(r"\n\s*Docs:.*$", "", body, flags=re.S).strip()
    return m.group(1).strip(), body


def unwrap_block(text: str) -> str:
    """Return answer body when *text* is print_block output; otherwise return text unchanged."""
    parsed = parse_block((text or "").strip())
    if parsed:
        return parsed[1]
    return (text or "").strip()
