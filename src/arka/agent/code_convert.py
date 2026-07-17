"""Preview-first source-language conversion with explicit verification steps."""
from __future__ import annotations

import argparse
from pathlib import Path

LANGS = ("python", "javascript", "typescript", "rust", "go", "java", "cpp", "ruby")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka code-convert")
    parser.add_argument("source", type=Path)
    parser.add_argument("target_language", choices=LANGS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    source = args.source.expanduser()
    if not source.is_file():
        print(f"source not found: {source}")
        return 1
    text = source.read_text(encoding="utf-8", errors="replace")
    from arka.llm.hybrid import complete

    prompt = f"Convert this source to {args.target_language}. Preserve behavior, error handling, input/output contracts, and security properties. Do not invent dependencies. Return only code.\n\n{text}"
    converted = complete("You are a careful code translation engineer.", prompt, task="coding", skill="code_convert", policy="local-first")
    if not args.apply or not args.output:
        print(converted)
        print("\n# Verification: run target-language formatter, tests, dependency audit, and behavior comparison.")
        return 0
    target = args.output.expanduser()
    if target.exists():
        print(f"Refusing to overwrite existing file: {target}")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(converted + "\n", encoding="utf-8")
    print(f"created\t{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
