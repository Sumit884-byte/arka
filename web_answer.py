#!/usr/bin/env python3
"""Web snippet lookup for factual questions (DuckDuckGo instant answers)."""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request


def snippet(question: str) -> str:
    question = " ".join(question.split())
    if not question:
        return ""

    params = urllib.parse.urlencode(
        {
            "q": question,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )
    url = f"https://api.duckduckgo.com/?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "arka-web-answer/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return ""

    parts: list[str] = []
    if data.get("Answer"):
        parts.append(str(data["Answer"]))
    if data.get("AbstractText"):
        parts.append(str(data["AbstractText"]))
    for topic in data.get("RelatedTopics") or []:
        if isinstance(topic, dict) and topic.get("Text"):
            parts.append(str(topic["Text"]))
            break
        if isinstance(topic, dict) and topic.get("Topics"):
            for sub in topic["Topics"][:2]:
                if isinstance(sub, dict) and sub.get("Text"):
                    parts.append(str(sub["Text"]))
                    break
            if len(parts) >= 2:
                break

    return "\n".join(parts)[:2000]


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: web_answer.py snippet <question>", file=sys.stderr)
        return 1
    print(snippet(" ".join(sys.argv[1:])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
