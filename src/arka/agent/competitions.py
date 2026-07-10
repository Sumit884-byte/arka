#!/usr/bin/env python3
"""Search hackathons and ML competitions across curated data sources."""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

try:
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass


@dataclass(frozen=True)
class CompetitionSource:
    source_id: str
    label: str
    site_bias: str
    homepage: str


COMPETITION_SOURCES: dict[str, CompetitionSource] = {
    "kaggle": CompetitionSource(
        "kaggle",
        "Kaggle",
        "site:kaggle.com/competitions",
        "https://www.kaggle.com/competitions",
    ),
    "devpost": CompetitionSource(
        "devpost",
        "Devpost",
        "site:devpost.com",
        "https://devpost.com/hackathons",
    ),
    "wemakedevs": CompetitionSource(
        "wemakedevs",
        "WeMakeDevs",
        "site:wemakedevs.org/hackathons",
        "https://www.wemakedevs.org/hackathons",
    ),
    "mlh": CompetitionSource(
        "mlh",
        "MLH",
        "site:mlh.io",
        "https://mlh.io",
    ),
    "hackerearth": CompetitionSource(
        "hackerearth",
        "HackerEarth",
        "site:hackerearth.com/challenges",
        "https://www.hackerearth.com/challenges/",
    ),
    "drivendata": CompetitionSource(
        "drivendata",
        "DrivenData",
        "site:drivendata.co/competitions",
        "https://www.drivendata.co/competitions/",
    ),
    "zindi": CompetitionSource(
        "zindi",
        "Zindi",
        "site:zindi.africa/competitions",
        "https://zindi.africa/competitions",
    ),
    "aicrowd": CompetitionSource(
        "aicrowd",
        "AIcrowd",
        "site:aicrowd.com/challenges",
        "https://www.aicrowd.com/challenges",
    ),
    "topcoder": CompetitionSource(
        "topcoder",
        "Topcoder",
        "site:topcoder.com/challenges",
        "https://www.topcoder.com/challenges",
    ),
    "codalab": CompetitionSource(
        "codalab",
        "Codalab",
        "site:codabench.org",
        "https://www.codabench.org/",
    ),
}

_COMPETITIONS_TRIGGER = re.compile(
    r"(?i)\b("
    r"competitions?|hackathons?|kaggle\s+competitions?|"
    r"data\s+science\s+contests?|ml\s+contests?|coding\s+contests?|"
    r"competetions?"
    r")\b"
)
_STOCK_COMPETITION = re.compile(
    r"(?i)(?:^stock\s+competition\b|^competition\s+(?:peers?|rivals?|[A-Z][A-Z0-9.-]{1,12})\b)"
)
_SOURCE_ALIASES: dict[str, str] = {
    "kaggle": "kaggle",
    "devpost": "devpost",
    "wemakedevs": "wemakedevs",
    "we make devs": "wemakedevs",
    "wemakedev": "wemakedevs",
    "mlh": "mlh",
    "major league hacking": "mlh",
    "hackerearth": "hackerearth",
    "hacker earth": "hackerearth",
    "drivendata": "drivendata",
    "driven data": "drivendata",
    "zindi": "zindi",
    "aicrowd": "aicrowd",
    "ai crowd": "aicrowd",
    "topcoder": "topcoder",
    "top coder": "topcoder",
    "codalab": "codalab",
    "codabench": "codalab",
}


def _duckduckgo_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    try:
        try:
            from ddgs import DDGS  # type: ignore
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore
    except ImportError:
        return []

    rows: list[dict[str, str]] = []
    try:
        with DDGS() as client:
            for row in client.text(query, max_results=max_results):
                rows.append(
                    {
                        "title": str(row.get("title") or "").strip(),
                        "link": str(row.get("href") or "").strip(),
                        "snippet": str(row.get("body") or "").strip(),
                    }
                )
    except Exception as exc:
        print(f"Search error: {exc}", file=sys.stderr)
    return rows


def list_sources_text() -> str:
    lines = ["Competition data sources:", ""]
    for src in COMPETITION_SOURCES.values():
        lines.append(f"- {src.label} ({src.source_id}) — {src.homepage}")
    lines.append("")
    lines.append("Search all: competitions search <topic>")
    lines.append("One source: competitions search <topic> --source kaggle")
    return "\n".join(lines)


def detect_sources(text: str) -> list[str]:
    lower = (text or "").lower()
    hits: list[tuple[int, str]] = []
    for alias, source_id in _SOURCE_ALIASES.items():
        pos = lower.find(alias)
        if pos >= 0:
            hits.append((pos, source_id))
    seen: set[str] = set()
    found: list[str] = []
    for _pos, source_id in sorted(hits, key=lambda item: item[0]):
        if source_id not in seen:
            seen.add(source_id)
            found.append(source_id)
    return found


def extract_search_query(text: str) -> str:
    topic = (text or "").strip()
    topic = re.sub(r"(?i)^(arka\s+)?", "", topic)
    topic = re.sub(
        r"(?i)^(?:show\s+me|find|search|list|what|which)\s+",
        "",
        topic,
    )
    topic = re.sub(
        r"(?i)^(?:available\s+)?(?:competitions?|hackathons?|competetions?)\s+",
        "",
        topic,
    )
    topic = re.sub(r"(?i)^(?:on|from|at|in|for)\s+", "", topic)
    topic = re.sub(
        r"(?i)\b(?:kaggle|devpost|wemakedevs|mlh|hackerearth|drivendata|zindi|aicrowd|topcoder|codalab|codabench)\b",
        "",
        topic,
    )
    topic = re.sub(r"(?i)\b(?:on|from|at|in|for)\b", "", topic)
    topic = re.sub(r"(?i)\b(?:competitions?|hackathons?|competetions?|data\s+sources?)\b", "", topic)
    topic = re.sub(r"\s+", " ", topic).strip(" .,-")
    return topic or "active machine learning"


def wants_competitions_search(text: str) -> bool:
    raw = text or ""
    if _STOCK_COMPETITION.search(raw):
        return False
    if re.search(r"(?i)\b(?:competition|data)\s+sources?\b", raw):
        return True
    if re.search(
        r"(?i)\bcompetitions?\s+search\b|\bsearch\s+(?:all\s+)?competitions?\b",
        raw,
    ):
        return True
    if _COMPETITIONS_TRIGGER.search(raw):
        return True
    if re.search(
        r"(?i)\b(show\s+me|find|search|list)\b.*\b(competitions?|hackathons?|kaggle|competetions?)\b",
        raw,
    ):
        return True
    return False


def wants_competitions_sources(text: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(?:list\s+)?(?:competition|competitions|hackathon)\s+(?:data\s+)?sources?\b",
            text or "",
        )
        or re.search(r"(?i)\bcompetitions?\s+sources?\b", text or "")
    )


def route_command(text: str) -> str:
    if not wants_competitions_search(text):
        return ""
    if wants_competitions_sources(text):
        return "competitions sources"
    query = extract_search_query(text)
    sources = detect_sources(text)
    if sources:
        src_arg = ",".join(sources)
        return f"competitions search {shlex.quote(query)} --source {src_arg}"
    return f"competitions search {shlex.quote(query)}"


def _normalize_link(link: str) -> str:
    try:
        parsed = urlparse(link)
        path = parsed.path.rstrip("/")
        return f"{parsed.netloc.lower()}{path.lower()}"
    except Exception:
        return link.lower()


def search_competitions(
    query: str,
    *,
    sources: list[str] | None = None,
    limit: int = 5,
) -> str:
    query = (query or "").strip() or "active machine learning"
    selected = sources or list(COMPETITION_SOURCES.keys())
    unknown = [s for s in selected if s not in COMPETITION_SOURCES]
    if unknown:
        return f"Unknown source(s): {', '.join(unknown)}. Run: competitions sources"

    seen_links: set[str] = set()
    blocks: list[str] = [f"Competition search: {query}", ""]

    for source_id in selected:
        src = COMPETITION_SOURCES[source_id]
        search_q = f"{src.site_bias} {query}"
        results = _duckduckgo_search(search_q, max_results=limit)
        if not results:
            blocks.append(f"## {src.label}")
            blocks.append("(no results)")
            blocks.append("")
            continue

        blocks.append(f"## {src.label}")
        count = 0
        for row in results:
            link = row.get("link") or ""
            key = _normalize_link(link)
            if key in seen_links:
                continue
            seen_links.add(key)
            title = row.get("title") or link or "Untitled"
            snippet = row.get("snippet") or ""
            blocks.append(f"- {title}")
            if link:
                blocks.append(f"  {link}")
            if snippet:
                blocks.append(f"  {snippet[:220]}")
            count += 1
            if count >= limit:
                break
        blocks.append("")

    if len(blocks) <= 2:
        return (
            "No competition results found. Install chat deps: pip install 'arka-agent[chat]' "
            "(needs ddgs). Try: competitions sources"
        )
    return "\n".join(blocks).strip()


def cmd_sources(_args: argparse.Namespace) -> int:
    print(list_sources_text())
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    sources = None
    if getattr(args, "source", None):
        sources = [s.strip().lower() for s in str(args.source).split(",") if s.strip()]
    text = search_competitions(
        " ".join(args.query).strip(),
        sources=sources,
        limit=max(1, int(args.limit)),
    )
    print(text)
    return 0 if text else 1


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Search hackathons and ML competitions")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to competitions command")
    p_route.add_argument("text", nargs="+")

    sub.add_parser("sources", help="List competition data sources").set_defaults(
        func=cmd_sources
    )

    p_search = sub.add_parser("search", help="Search competitions across sources")
    p_search.add_argument("query", nargs="+", help="Topic or keywords")
    p_search.add_argument(
        "--source",
        help="Comma-separated source ids (kaggle,devpost,...)",
    )
    p_search.add_argument("--limit", type=int, default=5, help="Max results per source")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args(argv)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
