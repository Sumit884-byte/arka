"""Discover hackathons and turn one into a reviewable build plan."""
from __future__ import annotations

import argparse
import json
from typing import Any


def find(topic: str, *, limit: int = 8) -> list[dict[str, str]]:
    from arka.agent.chat import duckduckgo_search

    rows: list[dict[str, str]] = []
    for item in duckduckgo_search(f"hackathon {topic}", max_results=max(1, min(limit, 20))):
        url = str(item.get("url") or item.get("href") or "").strip()
        if not url:
            continue
        rows.append({"name": str(item.get("title") or "Hackathon"), "url": url, "summary": str(item.get("snippet") or item.get("body") or "")})
    return rows


def plan(topic: str, *, hours: int = 24, event: str = "") -> dict[str, Any]:
    hours = max(1, min(hours, 720))
    return {
        "topic": topic,
        "event": event or "user-selected hackathon",
        "idea": f"A focused, demo-first project solving one measurable problem in {topic}.",
        "schedule_hours": hours,
        "milestones": [
            {"hours": max(1, hours // 12), "name": "scope and acceptance criteria"},
            {"hours": max(2, hours // 4), "name": "working vertical slice"},
            {"hours": max(3, hours // 2), "name": "integration, data, and error states"},
            {"hours": max(1, hours - max(3, hours // 2)), "name": "testing, demo polish, and submission review"},
        ],
        "guardrails": ["keep credentials local", "verify judging criteria", "do not submit or register without explicit approval"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka hackathon")
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("find", aliases=["give", "list"])
    search.add_argument("topic", nargs="+")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--json", action="store_true")
    make = sub.add_parser("plan", aliases=["participate"])
    make.add_argument("topic", nargs="+")
    make.add_argument("--hours", type=int, default=24)
    make.add_argument("--event", default="")
    make.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    topic = " ".join(args.topic)
    if args.command in {"find", "give", "list"}:
        result = find(topic, limit=args.limit)
        print(json.dumps(result, indent=2) if args.json else "\n".join(f"{row['name']}\n  {row['url']}\n  {row['summary']}" for row in result))
        return 0
    result = plan(topic, hours=args.hours, event=args.event)
    print(json.dumps(result, indent=2) if args.json else "Hackathon plan\n" + "\n".join(f"- {m['name']} ({m['hours']}h)" for m in result["milestones"]))
    return 0
