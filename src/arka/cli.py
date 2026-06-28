"""Arka CLI — cross-platform entry point (macOS, Windows, Linux)."""

from __future__ import annotations

import argparse
import subprocess
import sys

from arka import __version__
from arka.dispatch import run_fish_skill, run_script, run_skill
from arka.env import load_env
from arka.fish_bridge import delegate_subcommand, delegate_to_fish
from arka.paths import (
    arka_home,
    bundled_dir,
    cache_dir,
    checkout_root,
    config_dir,
    ensure_layout,
    env_file,
    fish_config,
    package_dir,
)
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

    if args[0] in ("refetch", "update", "sync"):
        return _cmd_refetch(args[1:])

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


def _cmd_refetch(extra: list[str]) -> int:
    """Pull latest git + sync src/arka/bundled + optional pip reinstall."""
    pull = "--no-pull" not in extra
    do_install = "--install" in extra or "-i" in extra

    root = checkout_root()
    if root is None:
        print("Not inside an Arka git clone.", file=sys.stderr)
        print("Use: git clone https://github.com/Sumit884-byte/arka && cd arka && arka refetch --install", file=sys.stderr)
        return 1

    if pull and (root / ".git").is_dir():
        print("→ git pull")
        r = subprocess.run(["git", "pull", "--ff-only"], cwd=root)
        if r.returncode != 0:
            print("git pull failed (fix conflicts or use: arka refetch --no-pull)", file=sys.stderr)
            return r.returncode

    sync = root / "scripts" / "sync_bundled.py"
    if sync.is_file():
        print("→ sync bundled scripts")
        r = subprocess.run([sys.executable, str(sync)], cwd=root)
        if r.returncode != 0:
            return r.returncode
    else:
        print(f"Missing {sync}", file=sys.stderr)
        return 1

    if do_install:
        print("→ pip install -e '.[chat]'")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", f"{root}[chat]"],
            cwd=root,
        )
        if r.returncode != 0:
            return r.returncode

    ensure_layout()
    print(f"✓ Refetch complete — bundle: {bundled_dir()}")
    print("  arka doctor")
    return 0


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
    print(f"Arka setup complete ({system()})")
    print(f"  Scripts: (package) {home}")
    print(f"  Config:  {config_dir()}")
    print(f"  Cache:   {cache_dir()}")
    print(f"  Env:     {env_file()}")
    if not env_file().is_file():
        print("  Edit .env and add GEMINI_API_KEY or GROQ_API_KEY")
    print("\nNext: pip install 'arka-agent[chat]'  then  arka ask \"what is Python?\"")
    return 0


def _cmd_doctor() -> int:
    print(f"arka {__version__} — {system()}")
    bundled = bundled_dir()
    print(f"  Package bundle: {bundled}")
    print(f"  ARKA_HOME:      {arka_home()}")
    print(f"  Config:         {config_dir()}")
    print(f"  Cache:          {cache_dir()}")
    print(f"  arka_chat.py:   {('ok' if (arka_home() / 'arka_chat.py').is_file() else 'missing — run: python scripts/sync_bundled.py')}")
    print(f"  Fish agent:     {('yes — ' + str(fish_config())) if has_full_fish_agent() else 'no (portable Python mode)'}")
    return 0


def _cmd_help() -> int:
    print(
        """Arka — cross-platform AI agent

Install:
  pip install arka-agent          # core
  pip install 'arka-agent[chat]'  # web answers, calc, weather
  arka setup                      # create ~/.config/arka + .env (scripts live in package)
  arka refetch [--install]        # git pull + sync bundled (after clone or on another PC)

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
