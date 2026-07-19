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


def reported_total_from_rows(rows: list[dict[str, Any]]) -> int | None:
    """Extract a count only when a result states it explicitly; never estimate."""
    for row in rows:
        text = clean_text(f"{row.get('title', '')} {row.get('text', '')}")
        match = re.search(r"\b(?:total|数量|count)\D{0,20}(\d[\d,]*)\b|\b(\d[\d,]*)\s+(?:items|entries|aircraft|vehicles)\b", text, re.I)
        if match:
            value = next((group for group in match.groups() if group), None)
            if value:
                return int(value.replace(",", ""))
    return None


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


def collect_catalog(topic: str, *, duration: str = "5m", limit: int = 100, output: str | None = None, fmt: str = "jsonl") -> dict[str, Any]:
    """Collect a category in bounded pages and report coverage, never inventing totals."""
    clean_topic = clean_text(topic)
    if not clean_topic:
        raise ValueError("catalog topic is required")
    started = time.monotonic()
    deadline = started + duration_seconds(duration)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    count_rows: list[dict[str, Any]] = []
    if time.monotonic() < deadline:
        count_result = collect(f"{clean_topic} authoritative total count", duration=f"{max(1, min(5, int(deadline - time.monotonic())))}s", limit=5)
        count_rows = list(count_result.get("data") or [])
    page = 0
    while time.monotonic() < deadline and len(rows) < limit:
        page += 1
        page_result = collect(
            f"{clean_topic} authoritative catalog page {page}",
            duration=f"{max(1, int(deadline - time.monotonic()))}s",
            limit=min(25, limit - len(rows)),
            output=None,
        )
        added = 0
        for row in page_result.get("data") or []:
            url = str(row.get("url") or "")
            if url and url not in seen:
                seen.add(url)
                rows.append(row)
                added += 1
        if added == 0:
            break
    result = {
        "topic": clean_topic,
        "rows": len(rows),
        "pages": page,
        "duration_seconds": round(time.monotonic() - started, 2),
        "data": rows,
        "reported_total": reported_total_from_rows(count_rows),
        "count_query": f"{clean_topic} authoritative total count",
        "coverage": "partial unless an authoritative source reports completeness",
        "truncated": len(rows) >= limit or time.monotonic() >= deadline,
    }
    if output:
        saved = Path(output).expanduser()
        saved.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "jsonl":
            saved.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        elif fmt == "json":
            saved.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            with saved.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=("topic", "title", "url", "text", "source"))
                writer.writeheader()
                writer.writerows(rows)
        result["output"] = str(saved)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka data collect")
    parser.add_argument("topic", nargs="+")
    parser.add_argument("--for", dest="duration", default="1m")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output")
    parser.add_argument("--format", choices=("jsonl", "json", "csv"), default="jsonl")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--catalog", action="store_true", help="Paginate a category and report sourced coverage")
    args = parser.parse_args(argv)
    try:
        fn = collect_catalog if args.catalog else collect
        result = fn(" ".join(args.topic), duration=args.duration, limit=args.limit, output=args.output, fmt=args.format)
    except (ValueError, RuntimeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"collected {result['rows']} cleaned records")
    return 0
