"""Safe argv splitting for skill lines that contain apostrophes and unmatched quotes."""

from __future__ import annotations

import argparse
import os
import shlex
import sys


def split_skill_argv(cmd: str) -> list[str]:
    """Split a skill command line without raising on natural-language apostrophes.

    ``shlex.split`` treats ``I'll`` as an unclosed quote. Study prompts and WebUI
    text hit that constantly, so fall back to ``skill + remainder`` instead of crashing.
    """
    text = (cmd or "").strip()
    if not text:
        return []
    try:
        tokens = shlex.split(text, posix=True)
        if tokens:
            return tokens
    except ValueError:
        pass
    parts = text.split(None, 1)
    return [part for part in parts if part]


def fish_hear_argv() -> list[str]:
    """fish argv that reads the user phrase from ``ARKA_HEAR_TEXT`` — never interpolates it."""
    return ["fish", "-ic", 'agent_hear "$ARKA_HEAR_TEXT"']


def fish_hear_env(text: str, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base if base is not None else os.environ)
    env["ARKA_HEAR_TEXT"] = text
    env.setdefault("AGENT_SPEAK", "0")
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Split a skill line for fish dispatch")
    parser.add_argument("text", nargs="?", default="", help="Skill line (or set ARKA_SHLEX)")
    args = parser.parse_args(argv)
    text = args.text or os.environ.get("ARKA_SHLEX", "")
    sys.stdout.write("\n".join(split_skill_argv(text)))
    if text.strip():
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
