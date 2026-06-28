"""Arka CLI — cross-platform entry point (macOS, Windows, Linux)."""

from __future__ import annotations

import argparse
import sys

from arka import __version__
from arka.dispatch import run_fish_skill, run_script, run_skill
from arka.env import load_env
from arka.fish_bridge import delegate_subcommand, delegate_to_fish
from arka.paths import arka_home, cache_dir, config_dir, ensure_layout, env_file, fish_config, sync_scripts_to
from arka.platform_info import has_full_fish_agent, system
from arka.router import route


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        return _cmd_help()

    if args[0] in ("-h", "--help", "help"):
        return _cmd_help()

    if args[0] in ("-V", "--version", "version"):
        print(f"arka {__version__} ({system()})")
        return 0

    if args[0] == "setup":
        return _cmd_setup()

    if args[0] == "doctor":
        return _cmd_doctor()

    if args[0] == "route":
        text = " ".join(args[1:]).strip()
        if not text:
            print("Usage: arka route <request>", file=sys.stderr)
            return 1
        return _cmd_route_preview(text)

    # Subcommands that map to Python scripts
    if args[0] == "chat":
        return run_script("arka_chat.py", args[1:])

    if args[0] == "password":
        from arka.skills import run_password

        return run_password(args[1:])

    if args[0] in ("ask", "web"):
        q = " ".join(args[1:]).strip()
        if not q:
            print("Usage: arka ask <question>", file=sys.stderr)
            return 1
        from arka.skills import run_chat_ask

        return run_chat_ask(q, deep=args[0] == "web" and "--deep" in args)

    # Fish-only service subcommands (listen, start, serve, …)
    fish_subs = {
        "listen",
        "start",
        "stop",
        "status",
        "serve",
        "speak",
        "speak-lang",
        "speak-voice",
        "brief",
        "aie",
        "yt-bulk",
        "queue",
        "wifi",
        "usage",
        "voice",
        "tts-setup",
        "autostart",
        "phone-env",
    }
    if args[0] in fish_subs and has_full_fish_agent():
        code = delegate_subcommand(args[0], args[1:])
        return code if code is not None else 1

    # Natural language: prefer full fish agent on Linux/mac when available
    text = " ".join(args).strip()
    if has_full_fish_agent():
        code = delegate_to_fish(args)
        if code is not None:
            return code

    return _run_portable(text)


def _run_portable(text: str) -> int:
    r = route(text)
    if r:
        if r.skill == "help":
            return _cmd_help()
        print(f"→ {r.skill}")
        return run_skill(r.skill)

    from arka.skills import run_chat_ask

    print("→ ask")
    return run_chat_ask(text)


def _cmd_route_preview(text: str) -> int:
    r = route(text)
    if r:
        print(f"skill: {r.skill}")
        print(f"source: {r.source}")
        return 0
    print("skill: (none — would use fish agent or LLM on full install)")
    return 0


def _cmd_setup() -> int:
    home = ensure_layout()
    copied = sync_scripts_to(home)
    print(f"Arka setup complete ({system()})")
    print(f"  Home:   {home}")
    print(f"  Config: {config_dir()}")
    print(f"  Cache:  {cache_dir()}")
    print(f"  Env:    {env_file()}")
    if copied:
        print(f"  Synced: {len(copied)} files")
    if not env_file().is_file():
        print("  Edit .env and add GEMINI_API_KEY or GROQ_API_KEY")
    print("\nNext: pip install 'arka-agent[chat]'  then  arka ask \"what is Python?\"")
    return 0


def _cmd_doctor() -> int:
    print(f"arka {__version__} — {system()}")
    print(f"  ARKA_HOME:    {arka_home()}")
    print(f"  Config:       {config_dir()}")
    print(f"  Cache:        {cache_dir()}")
    print(f"  arka_chat.py: {('ok' if (arka_home() / 'arka_chat.py').is_file() else 'missing — run: arka setup')}")
    print(f"  Fish agent:   {('yes — ' + str(fish_config())) if has_full_fish_agent() else 'no (portable Python mode)'}")
    return 0


def _cmd_help() -> int:
    print(
        """Arka — cross-platform AI agent

Install:
  pip install arka-agent          # core
  pip install 'arka-agent[chat]'  # web answers, calc, weather
  arka setup                      # create config dirs + sync scripts

Usage:
  arka <request>                  # natural language (routes to best skill)
  arka ask <question>             # web + AI answer
  arka password save wifi         # generate + store password
  arka password set wifi <secret> # store your own password
  arka password get wifi          # retrieve stored password
  arka chat calc integrate sin(x) # SymPy
  arka route <request>            # preview routing (no run)
  arka doctor                     # install diagnostics

Platforms:
  Linux + fish    Full 70+ skills via config.fish (this repo)
  macOS / Windows Portable skills via Python (chat, passwords, web)

Docs: README.md in ARKA_HOME"""
    )
    return 0
