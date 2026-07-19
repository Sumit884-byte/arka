"""Deterministic word and text statistics; content stays local."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def count_text(text: str) -> dict[str, int | float]:
    words = re.findall(r"[\w’'-]+", text, flags=re.UNICODE)
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
    sentence_count = len(sentences)
    return {"words": len(words), "unique_words": len({word.casefold() for word in words}), "characters": len(text), "characters_no_spaces": len(re.sub(r"\s", "", text)), "lines": len(text.splitlines()), "sentences": sentence_count, "sentence_word_estimate": sentence_count * 15, "reading_minutes": round(len(words) / 200, 2)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka word-counter")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--file")
    source.add_argument("--stdin", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        text = args.text if args.text is not None else Path(args.file).expanduser().read_text(encoding="utf-8") if args.file else sys.stdin.read()
    except OSError as exc:
        parser.error(str(exc))
    result = {"source": args.file or "text" if not args.stdin else "stdin", **count_text(text)}
    print(json.dumps(result, indent=2) if args.json else f"{result['words']} words, {result['characters']} characters ({result['reading_minutes']} min read)")
    return 0
