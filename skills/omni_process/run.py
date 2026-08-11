#!/usr/bin/env python3
"""Arka skill entry point for Omni article processing."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent


def _bootstrap() -> Path:
    """Resolve Omni project root and add src/ to sys.path."""
    if env := os.environ.get("OMNI_ROOT", "").strip():
        root = Path(env).expanduser()
    else:
        manifest = SKILL_DIR / "skill.json"
        if manifest.is_file():
            try:
                meta = json.loads(manifest.read_text(encoding="utf-8"))
                root = Path(
                    meta.get("metadata", {}).get("arka", {}).get("omni_root", "")
                ).expanduser()
            except (json.JSONDecodeError, OSError):
                root = Path()
        else:
            root = Path()
        if not (root / "src" / "omni").is_dir():
            root = SKILL_DIR.parent
    src = root / "src"
    if not (src / "omni").is_dir():
        raise RuntimeError(
            f"Omni source not found at {src}. "
            "Set OMNI_ROOT to your omni project path."
        )
    sys.path.insert(0, str(src))
    return root


ROOT = _bootstrap()

os.environ.setdefault("ARKA_PROMPT_COMPACT", "0")
os.environ.setdefault("SKILL_MODEL_OMNI_PROCESS", "gemini/gemini-2.0-flash")

from omni.arka_integration import jsonkit_pretty  # noqa: E402
from omni.process import process_article  # noqa: E402
from omni.validate import parse_and_validate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka omni_process",
        description="Process technical articles into Omni JSON via Arka integration.",
    )
    parser.add_argument("input", nargs="?", help="Article file or stdin")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--remember", action="store_true", help="Store in Arka memory")
    parser.add_argument("--validate", metavar="JSON")
    parser.add_argument("--bridge-env", action="store_true", help="Bridge Arka keys to .env")
    args = parser.parse_args(argv)

    if args.bridge_env:
        from omni.arka_integration import bridge_env

        print(f"Bridged {bridge_env()} env vars from Arka")
        return 0

    if args.validate:
        raw = Path(args.validate).read_text(encoding="utf-8")
        data, errors = parse_and_validate(raw)
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        print(jsonkit_pretty(data))
        return 0

    if args.input:
        article = Path(args.input).read_text(encoding="utf-8", errors="replace")
    else:
        article = sys.stdin.read()
        if not article.strip():
            parser.error("provide an input file or pipe article text via stdin")

    result = process_article(article, dry_run=args.dry_run, remember_result=args.remember)
    print(json.dumps(result, indent=2) if args.dry_run else jsonkit_pretty(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
