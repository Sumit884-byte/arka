"""Consistent terminal blocks for Arka CLI output."""

from __future__ import annotations

import re

_BLOCK_RE = re.compile(r"^━━━\s+(.+?)\s+━━━$")


def active_model_label() -> str | None:
    try:
        from arka.llm.fallback import llm_last_model

        if not show_model_enabled():
            return None
        row = llm_last_model()
        if row:
            return f"{row[0]}/{row[1]}"
    except Exception:
        pass
    return None


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


def show_capabilities() -> int:
    """Print a deterministic Arka skills/capabilities summary (no LLM)."""
    from arka.agent.voice import voice_help

    print_section("Arka Skills")
    print(f"  {voice_help()}")
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
        """  With fish       70+ skills via bundled config.fish (recommended)
  Without fish    Portable Python subset (chat, web, calc, weather, …)
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
    label = model if model is not None else active_model_label()
    docs = active_context7_label()
    if label or docs:
        print()
    if label:
        print(f"  Model: {label}")
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
    body = re.sub(r"\n\s*Docs:.*$", "", body, flags=re.S).strip()
    return m.group(1).strip(), body
