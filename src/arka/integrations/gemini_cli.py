#!/usr/bin/env python3
"""Google Gemini CLI wrapper — arka gemini | gemini_cli."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys

GEMINI_NPM_PKG = "@google/gemini-cli"
GEMINI_SUBCOMMANDS = frozenset(
    {"mcp", "extensions", "extension", "skills", "skill", "hooks", "hook", "gemma"}
)
INSTALL_HINT = (
    "Google Gemini CLI not found.\n"
    "  npm install -g @google/gemini-cli   # Node.js 18+\n"
    "  npx @google/gemini-cli              # one-shot, no install\n"
    "Auth: run `gemini` once and sign in with Google, or set GEMINI_API_KEY in .env"
)


def gemini_exec_prefix() -> list[str] | None:
    """Return argv prefix to invoke the Gemini CLI."""
    override = os.environ.get("GEMINI_CLI", "").strip()
    if override:
        return [override]
    path = shutil.which("gemini")
    if path:
        return [path]
    if shutil.which("npx"):
        return ["npx", GEMINI_NPM_PKG]
    return None


def gemini_cli_available() -> bool:
    return gemini_exec_prefix() is not None


def _looks_like_passthrough(argv: list[str]) -> bool:
    if not argv:
        return True
    if argv[0] == "--":
        return True
    if argv[0].startswith("-"):
        return True
    return argv[0] in GEMINI_SUBCOMMANDS


def build_gemini_argv(argv: list[str]) -> list[str]:
    """Map arka gemini args to native gemini CLI argv."""
    if not argv:
        return []
    if argv[0] == "--":
        return argv[1:]
    if _looks_like_passthrough(argv):
        return argv
    prompt = " ".join(argv).strip()
    if not prompt:
        return []
    # Headless -p runs require workspace trust (see geminicli.com trusted-folders docs).
    return ["--skip-trust", "-p", prompt]


_GEMINI_IMAGE_RE = re.compile(
    r"(?i)\b(?:generate|create|make|draw|paint|sketch|render|produce|thumbnail|video|"
    r"image|picture|photo|art|illustration|portrait|landscape|flash-image)\b"
)


def wants_gemini_cli(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if re.match(r"(?i)^(?:arka\s+)?gemini(?:_cli)?(?:\s+status|\s+help|\s+--help)?$", clean):
        return True
    if re.match(r"(?i)^gemini_cli\b", clean):
        return True
    if re.match(r"(?i)^gemini\s+\S", clean) and not _GEMINI_IMAGE_RE.search(clean):
        return True
    if re.search(r"(?i)\b(?:ask|use|run)\s+gemini\b", clean) and not _GEMINI_IMAGE_RE.search(clean):
        return True
    return False


def route_command(text: str) -> str:
    if not wants_gemini_cli(text):
        return ""
    clean = (text or "").strip()
    if re.match(r"(?i)^(?:arka\s+)?gemini(?:_cli)?\s+status$", clean):
        return "gemini_cli status"
    m = re.match(r"(?i)^(?:arka\s+)?(?:gemini_cli|gemini)\s+(.+)$", clean)
    if m:
        rest = m.group(1).strip()
        if rest:
            return "gemini_cli " + shlex.quote(rest)
    m = re.search(r"(?i)\b(?:ask|use|run)\s+gemini\s+(?:to\s+)?(.+)$", clean)
    if m:
        return "gemini_cli " + shlex.quote(m.group(1).strip())
    return "gemini_cli " + shlex.quote(clean)


def nl_to_argv(text: str) -> list[str] | None:
    route = route_command(text)
    if not route:
        return None
    return shlex.split(route)[1:]


def run_gemini_cli(argv: list[str], *, inherit_stdio: bool = True) -> int:
    prefix = gemini_exec_prefix()
    if not prefix:
        print(INSTALL_HINT, file=sys.stderr)
        return 127

    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    cmd = prefix + argv
    if inherit_stdio:
        return subprocess.call(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode


def cmd_status(_args: argparse.Namespace) -> int:
    prefix = gemini_exec_prefix()
    if not prefix:
        print("gemini_cli\tnot_available")
        print(f"hint\t{INSTALL_HINT.replace(chr(10), ' ')}")
        return 1

    print("gemini_cli\tavailable")
    print(f"invoke\t{' '.join(prefix)}")
    if os.environ.get("GEMINI_API_KEY", "").strip():
        print("auth\tGEMINI_API_KEY set")
    else:
        print("auth\tGEMINI_API_KEY not set (use Google sign-in on first run)")

    rc = run_gemini_cli(["--version"], inherit_stdio=False)
    return 0 if rc == 0 else 0


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])

    if raw and raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    if raw and raw[0] == "status":
        return cmd_status(argparse.Namespace())

    gemini_argv = build_gemini_argv(raw)
    return run_gemini_cli(gemini_argv)


def _print_help() -> None:
    print(
        """Google Gemini CLI for Arka

Usage:
  arka gemini                         Interactive Gemini CLI session
  arka gemini <prompt>                One-shot prompt (wraps: gemini -p "...")
  arka gemini -p "prompt"             Pass native gemini flags through
  arka gemini -m gemini-2.5-flash     Choose model (native flag)
  arka gemini mcp                     Gemini CLI subcommands (passthrough)
  arka gemini status                  Check install + auth hints
  arka gemini -- <args>               Explicit passthrough to gemini

Fish:
  gemini_cli <prompt>                 Same from an Arka fish shell

Install (Node.js 18+):
  npm install -g @google/gemini-cli
  npx @google/gemini-cli

Auth:
  Run `gemini` once and sign in with Google, or set GEMINI_API_KEY in .env
  (Arka already uses GEMINI_API_KEY for built-in LLM calls.)

Override binary:
  GEMINI_CLI=/path/to/gemini arka gemini status
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
