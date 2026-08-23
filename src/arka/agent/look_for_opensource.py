"""Find open-source projects, alternatives, and self-hosted tools."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

try:
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass


_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"look\s+for\s+open[- ]?source|"
    r"find\s+open[- ]?source|"
    r"search\s+(?:for\s+)?open[- ]?source|"
    r"open[- ]?source\s+(?:alternatives?|options?|tools?|projects?|repos?)|"
    r"(?:any\s+)?open[- ]?source\s+(?:for|to|that)|"
    r"self[- ]hosted\s+open[- ]?source\b|"
    r"self[- ]hosted\s+(?:open[- ]?source\s+)?(?:alternative|option|tool|for)|"
    r"foss\s+(?:alternative|option|tool|for)|"
    r"free\s+and\s+open[- ]?source\s+(?:alternative|tool|for)"
    r")\b"
)

_EXPLICIT_SKILL = re.compile(r"(?i)^look_for_opensource\b")

_TOPIC_NOISE = re.compile(
    r"(?i)\b("
    r"look\s+for|find|search\s+for|search|opensource|open[- ]source|"
    r"alternatives?|options?|tools?|projects?|repos?|self[- ]hosted|foss|"
    r"free\s+and|for|about|please|thanks?|me|some|any|good|best"
    r")\b"
)

_GITHUB_HOSTS = frozenset({"github.com", "www.github.com", "raw.githubusercontent.com"})


@dataclass(frozen=True)
class SearchPlan:
    label: str
    query: str


def wants_look_for_opensource(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if _EXPLICIT_SKILL.search(clean):
        return True
    return bool(_TRIGGER_RE.search(clean))


def _extract_topic(text: str) -> str:
    raw = (text or "").strip()
    raw = re.sub(r"(?i)^look_for_opensource\s+", "", raw)
    raw = re.sub(
        r"(?i)\b(?:look\s+for|find|search\s+for|search)\s+open[- ]?source\s+(?:projects?|tools?|alternatives?|options?)?\s*",
        "",
        raw,
    )
    raw = re.sub(
        r"(?i)\bopen[- ]?source\s+(?:alternatives?|options?|tools?|projects?|repos?)\s+(?:for|to)\s*",
        "",
        raw,
    )
    raw = re.sub(
        r"(?i)\b(?:self[- ]hosted|foss|free\s+and\s+open[- ]?source)\s+(?:alternative|option|tool)s?\s+(?:for|to)\s*",
        "",
        raw,
    )
    raw = re.sub(r"(?i)\b(?:for|about|on)\s*$", "", raw).strip(" ,:-")
    cleaned = _TOPIC_NOISE.sub(" ", raw)
    cleaned = re.sub(r"(?i)^to\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,:-")
    return cleaned or raw.strip()


def parse_request(text: str) -> dict[str, Any] | None:
    if not wants_look_for_opensource(text):
        return None
    topic = _extract_topic(text)
    if not topic:
        return None
    return {"query": topic}


def build_argv_from_nl(text: str) -> list[str] | None:
    parsed = parse_request(text)
    if not parsed:
        return None
    return ["search", parsed["query"]]


def route_command(text: str) -> str | None:
    argv = build_argv_from_nl(text)
    if not argv:
        return None
    return "look_for_opensource " + " ".join(shlex.quote(a) for a in argv)


def build_search_plans(topic: str) -> list[SearchPlan]:
    text = (topic or "").strip()
    if not text:
        return []
    return [
        SearchPlan("GitHub repos", f"site:github.com {text} open source"),
        SearchPlan("Awesome lists", f"awesome {text} open source github"),
        SearchPlan("Self-hosted", f"self-hosted open source {text}"),
        SearchPlan("Alternatives", f"open source alternative to {text}"),
    ]


def _host(link: str) -> str:
    try:
        host = urlparse(link).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _github_repo_from_link(link: str) -> str | None:
    host = _host(link)
    if host not in _GITHUB_HOSTS:
        return None
    try:
        parts = [p for p in urlparse(link).path.strip("/").split("/") if p]
    except Exception:
        return None
    if len(parts) >= 2 and parts[0] not in {"topics", "search", "collections", "trending"}:
        repo = parts[1].removesuffix(".git")
        return f"{parts[0]}/{repo}"
    return None


def _score_result(topic: str, title: str, snippet: str, link: str) -> float:
    words = {w for w in re.findall(r"[a-z0-9+#.-]{3,}", topic.lower()) if len(w) > 2}
    text = f"{title} {snippet} {link}".lower()
    score = 0.1
    if words:
        hits = sum(1 for w in words if w in text)
        score += min(0.45, hits / max(1, len(words)) * 0.45)
    if _github_repo_from_link(link):
        score += 0.25
    if "awesome-" in text or "awesome/" in text:
        score += 0.12
    if re.search(r"(?i)\b(mit|apache|gpl|bsd|open source|self-hosted|foss)\b", text):
        score += 0.08
    if re.search(r"(?i)\b(stars?|forks?|maintained|active)\b", text):
        score += 0.05
    return round(min(1.0, score), 3)


def _duckduckgo_search(query: str, *, max_results: int = 6) -> list[dict[str, Any]]:
    try:
        from arka.agent.chat import duckduckgo_search

        return duckduckgo_search(query, max_results=max_results)
    except ImportError:
        return []


def lookup_payload(
    query: str,
    *,
    limit: int = 8,
    max_queries: int = 3,
) -> dict[str, Any]:
    topic = (query or "").strip()
    if not topic:
        raise ValueError("query is required")

    limit = max(1, min(int(limit), 20))
    max_queries = max(1, min(int(max_queries), len(build_search_plans(topic))))

    merged: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    for plan in build_search_plans(topic)[:max_queries]:
        for row in _duckduckgo_search(plan.query, max_results=limit):
            link = str(row.get("link") or "").strip()
            if not link or link in seen_links:
                continue
            title = str(row.get("title") or "").strip()
            snippet = str(row.get("snippet") or "").strip()
            if not title and not snippet:
                continue
            seen_links.add(link)
            merged.append({
                "source": plan.label,
                "title": title,
                "snippet": snippet,
                "link": link,
                "repo": _github_repo_from_link(link),
                "relevance_score": _score_result(topic, title, snippet, link),
            })

    merged.sort(key=lambda r: r["relevance_score"], reverse=True)
    results = merged[:limit]
    return {
        "ok": True,
        "query": topic,
        "count": len(results),
        "results": results,
    }


def format_payload_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Open-source lookup: {payload.get('query', '')}",
        "",
    ]
    results = payload.get("results") or []
    if not results:
        lines.append("No open-source matches found. Try a narrower topic or add context (e.g. self-hosted notes app).")
        return "\n".join(lines)

    for idx, row in enumerate(results, 1):
        repo = row.get("repo")
        title = row.get("title") or row.get("link") or "result"
        source = row.get("source") or "web"
        score = row.get("relevance_score", 0)
        lines.append(f"{idx}. {title}")
        if repo:
            lines.append(f"   Repo: {repo}")
        lines.append(f"   Source: {source} · score {score}")
        snippet = str(row.get("snippet") or "").strip()
        if snippet:
            lines.append(f"   {snippet[:220]}")
        lines.append(f"   {row.get('link', '')}")
        lines.append("")

    lines.append("Tip: say `look for opensource <topic>` again with more detail, or open a repo link to inspect.")
    return "\n".join(lines).rstrip()


def cmd_search(args: argparse.Namespace) -> int:
    topic = " ".join(args.query).strip()
    payload = lookup_payload(topic, limit=max(1, int(args.limit)))
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_payload_text(payload))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find open-source projects and alternatives")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to look_for_opensource command")
    p_route.add_argument("text", nargs="+")

    p_is = sub.add_parser("is-request", help="True if text is an open-source lookup request")
    p_is.add_argument("text", nargs="+")

    p_search = sub.add_parser("search", help="Search for open-source projects")
    p_search.add_argument("query", nargs="+")
    p_search.add_argument("--limit", type=int, default=8)
    p_search.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    text = " ".join(getattr(args, "text", []) or []).strip()

    if args.cmd == "route":
        hit = route_command(text)
        if hit:
            print(hit)
        return 0
    if args.cmd == "is-request":
        print("yes" if wants_look_for_opensource(text) else "no")
        return 0
    if args.cmd == "search":
        return cmd_search(args)
    if args.cmd in (None, "show"):
        print("Usage: look_for_opensource search <topic>")
        print("Example: look_for_opensource search observability platform")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
