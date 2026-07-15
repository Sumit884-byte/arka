"""Bounded web data collection and cleaning workflow."""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Any


def duration_seconds(value: str) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|m|min|mins|h|hr|hrs)?\s*", value.lower())
    if not match:
        raise ValueError("duration must look like 30s, 5m, or 1h")
    amount = float(match.group(1))
    return amount * {"s": 1, "sec": 1, "secs": 1, "m": 60, "min": 60, "mins": 60, "h": 3600, "hr": 3600, "hrs": 3600, None: 60}[match.group(2)]


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", value or "")).strip()


def collect(topic: str, *, duration: str = "1m", limit: int = 10, output: str | None = None, fmt: str = "jsonl") -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + duration_seconds(duration)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        from arka.agent.chat import duckduckgo_search, scrape_url
    except ImportError as exc:
        raise RuntimeError("web collection dependencies are unavailable") from exc
    results = duckduckgo_search(topic, max_results=max(1, min(limit, 100)))
    for item in results:
        if time.monotonic() >= deadline or len(rows) >= limit:
            break
        url = str(item.get("url") or item.get("href") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        text = clean_text(str(item.get("snippet") or item.get("body") or ""))
        try:
            scraped = scrape_url(url, timeout=max(1, min(12, int(deadline - time.monotonic()))))
            text = clean_text(scraped) or text
        except Exception:
            pass
        if text:
            rows.append({"topic": topic, "title": clean_text(str(item.get("title") or "")), "url": url, "text": text, "source": "web"})
    result = {"topic": topic, "rows": len(rows), "duration_seconds": round(time.monotonic() - started, 2), "data": rows, "truncated": len(rows) >= limit or time.monotonic() >= deadline}
    if output:
        path = Path(output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=("topic", "title", "url", "text", "source"))
                writer.writeheader()
                writer.writerows(rows)
        else:
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        result["output"] = str(path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka data collect")
    parser.add_argument("topic", nargs="+")
    parser.add_argument("--for", dest="duration", default="1m")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output")
    parser.add_argument("--format", choices=("jsonl", "json", "csv"), default="jsonl")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = collect(" ".join(args.topic), duration=args.duration, limit=args.limit, output=args.output, fmt=args.format)
    except (ValueError, RuntimeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"collected {result['rows']} cleaned records")
    return 0
