"""Search code snippets and discussions on social/developer platforms."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

try:
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    site_query: str
    hostnames: frozenset[str]


PLATFORMS: dict[str, PlatformSpec] = {
    "twitter": PlatformSpec(
        key="twitter",
        label="X/Twitter",
        site_query="site:twitter.com OR site:x.com",
        hostnames=frozenset({"twitter.com", "x.com", "mobile.twitter.com"}),
    ),
    "reddit": PlatformSpec(
        key="reddit",
        label="Reddit",
        site_query="site:reddit.com",
        hostnames=frozenset({"reddit.com", "old.reddit.com", "www.reddit.com"}),
    ),
    "github": PlatformSpec(
        key="github",
        label="GitHub",
        site_query="site:github.com",
        hostnames=frozenset({"github.com", "www.github.com"}),
    ),
    "devto": PlatformSpec(
        key="devto",
        label="Dev.to",
        site_query="site:dev.to",
        hostnames=frozenset({"dev.to", "www.dev.to"}),
    ),
    "hackernews": PlatformSpec(
        key="hackernews",
        label="Hacker News",
        site_query="site:news.ycombinator.com",
        hostnames=frozenset({"news.ycombinator.com"}),
    ),
    "stackoverflow": PlatformSpec(
        key="stackoverflow",
        label="Stack Overflow",
        site_query="site:stackoverflow.com",
        hostnames=frozenset({"stackoverflow.com", "www.stackoverflow.com"}),
    ),
}

DEFAULT_PLATFORMS: tuple[str, ...] = tuple(PLATFORMS.keys())

_PLATFORM_ALIASES: dict[str, str] = {
    "twitter": "twitter",
    "x": "twitter",
    "reddit": "reddit",
    "github": "github",
    "dev.to": "devto",
    "devto": "devto",
    "dev": "devto",
    "hacker news": "hackernews",
    "hackernews": "hackernews",
    "hn": "hackernews",
    "stack overflow": "stackoverflow",
    "stackoverflow": "stackoverflow",
    "so": "stackoverflow",
}

_SOCIAL_CODE_TRIGGER = re.compile(
    r"(?i)\b("
    r"find\s+(?:code|examples?|snippets?)\s+(?:on|from|in)\s+"
    r"(?:twitter|x|reddit|github|dev\.?to|hacker\s*news|hn|stack\s*overflow)|"
    r"search\s+(?:twitter|x|reddit|github|dev\.?to|hacker\s*news|hn|stack\s*overflow)\s+for|"
    r"social\s+(?:media\s+)?code\s+lookup|"
    r"(?:what\s+are\s+)?people\s+(?:saying|discussing|talking)\s+about\s+.+\s+on\s+"
    r"(?:twitter|x|reddit|github|dev\.?to|stack\s*overflow)|"
    r"code\s+(?:lookup|search)\s+(?:on\s+)?(?:twitter|x|reddit|github|social|dev\.?to)|"
    r"(?:twitter|x|reddit|github|dev\.?to|stackoverflow|hacker\s*news|hn)\s+"
    r"(?:code|examples?|snippets?)\s+(?:for|about)|"
    r"stackoverflow\s+code\s+examples?\s+for"
    r")\b"
)

_PLATFORM_IN_TEXT = re.compile(
    r"(?i)\b(?:on|from|in|via)\s+(twitter|x|reddit|github|dev\.?to|hacker\s*news|hn|stack\s*overflow|so)\b"
    r"|\b(?:search|find)\s+(twitter|x|reddit|github|dev\.?to|hacker\s*news|hn|stack\s*overflow|so)\s+for\b"
    r"|\b(twitter|x|reddit|github|dev\.?to|hacker\s*news|hn|stack\s*overflow|so)\s+(?:code|examples?)\b"
)

_CODE_HINTS = re.compile(
    r"(?i)(```|`\w|`|\bdef\b|\bclass\b|\bfunction\b|\bimport\b|\basync\b|\berror\b|\bexception\b|"
    r"\bconst\b|\blet\b|\bvar\b|\bfn\b|\bimpl\b|\btrait\b|\bstruct\b|\benum\b|\bpackage\b|\bmodule\b)"
)

_QUERY_NOISE = re.compile(
    r"(?i)\b("
    r"find|search|lookup|look\s+up|code|snippet|snippets|social|media|"
    r"on|from|in|via|for|about|what|are|people|saying|discussing|talking|please|thanks?"
    r")\b"
)


def wants_social_code_lookup(text: str) -> bool:
    return bool(_SOCIAL_CODE_TRIGGER.search(text or ""))


def _normalize_platform_name(raw: str) -> str | None:
    key = (raw or "").strip().casefold().replace("  ", " ")
    key = key.replace("dev to", "dev.to")
    return _PLATFORM_ALIASES.get(key)


def parse_platforms(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _PLATFORM_IN_TEXT.finditer(text or ""):
        for group in match.groups():
            if not group:
                continue
            norm = _normalize_platform_name(group)
            if norm and norm not in seen:
                seen.add(norm)
                found.append(norm)
    return found


def _extract_topic(text: str, platforms: list[str]) -> str:
    raw = (text or "").strip()
    raw = re.sub(
        r"(?i)^(?:social\s+(?:media\s+)?code\s+lookup|code\s+(?:lookup|search))\s*[:,-]?\s*",
        "",
        raw,
    )
    raw = re.sub(
        r"(?i)\b(?:find|search|lookup|look\s+up)\s+(?:code|examples?|snippets?)\s+(?:on|from|in)\s+"
        r"(?:twitter|x|reddit|github|dev\.?to|hacker\s*news|hn|stack\s*overflow)\s+(?:for|about)\s*",
        "",
        raw,
    )
    raw = re.sub(
        r"(?i)\b(?:search|find)\s+(?:twitter|x|reddit|github|dev\.?to|hacker\s*news|hn|stack\s*overflow|so)\s+for\s*",
        "",
        raw,
    )
    raw = re.sub(
        r"(?i)\b(?:what\s+are\s+)?people\s+(?:saying|discussing|talking)\s+about\s+",
        "",
        raw,
    )
    raw = re.sub(
        r"(?i)\s+on\s+(?:twitter|x|reddit|github|dev\.?to|stack\s*overflow|hacker\s*news|hn)\s*$",
        "",
        raw,
    )
    for plat in platforms:
        for alias, norm in _PLATFORM_ALIASES.items():
            if norm == plat:
                raw = re.sub(rf"(?i)\b{re.escape(alias)}\b", " ", raw)
    cleaned = _QUERY_NOISE.sub(" ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,:-")
    return cleaned or text.strip()


def parse_social_code_lookup_request(text: str) -> dict[str, Any] | None:
    if not wants_social_code_lookup(text):
        return None
    platforms = parse_platforms(text) or list(DEFAULT_PLATFORMS)
    topic = _extract_topic(text, platforms)
    if not topic:
        return None
    return {"query": topic, "platforms": platforms}


def build_social_code_lookup_argv_from_nl(text: str) -> list[str] | None:
    parsed = parse_social_code_lookup_request(text)
    if not parsed:
        return None
    argv = ["search", parsed["query"]]
    if parsed["platforms"] and parsed["platforms"] != list(DEFAULT_PLATFORMS):
        argv.extend(["--platform", ",".join(parsed["platforms"])])
    return argv


def route_command(text: str) -> str:
    argv = build_social_code_lookup_argv_from_nl(text)
    if not argv:
        return ""
    return "social_code_lookup " + " ".join(shlex.quote(a) for a in argv)


def _host_from_link(link: str) -> str:
    try:
        host = urllib.parse.urlparse(link).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _platform_for_link(link: str) -> str | None:
    host = _host_from_link(link)
    if not host:
        return None
    for spec in PLATFORMS.values():
        if any(host == h or host.endswith(f".{h}") for h in spec.hostnames):
            return spec.key
    return None


def _author_from_link(link: str, platform: str | None) -> str:
    try:
        path = urllib.parse.urlparse(link).path.strip("/")
    except Exception:
        return ""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return ""
    if platform == "twitter" and parts:
        if parts[0] not in {"i", "intent", "search", "hashtag"}:
            return f"@{parts[0]}"
    if platform == "reddit":
        if len(parts) >= 2 and parts[0] == "r":
            return f"r/{parts[1]}"
        if parts[0].startswith("u_") or parts[0].startswith("user"):
            return f"u/{parts[-1]}"
    if platform == "github" and len(parts) >= 1:
        return parts[0]
    if platform == "devto" and parts:
        return parts[0]
    if platform == "stackoverflow" and "users" in parts:
        idx = parts.index("users")
        if idx + 1 < len(parts):
            return f"user/{parts[idx + 1]}"
    if platform == "hackernews":
        return "hn"
    return ""


def _score_result(query: str, title: str, snippet: str, platform: str | None) -> float:
    q_words = {w for w in re.findall(r"[a-z0-9_+#.-]{3,}", query.lower()) if w not in {"the", "and", "for"}}
    text = f"{title} {snippet}".lower()
    score = 0.0
    if q_words:
        hits = sum(1 for w in q_words if w in text)
        score += min(0.5, hits / max(1, len(q_words)) * 0.5)
    code_hits = len(_CODE_HINTS.findall(text))
    score += min(0.35, code_hits * 0.08)
    if platform:
        score += 0.05
    if "issue" in text or "discussion" in text or "comment" in text:
        score += 0.05
    return round(min(1.0, max(0.05, score)), 3)


def _duckduckgo_search(query: str, *, max_results: int = 8) -> list[dict[str, Any]]:
    try:
        from arka.agent.chat import duckduckgo_search

        return duckduckgo_search(query, max_results=max_results)
    except ImportError:
        return []


def _brightdata_search(query: str, *, max_results: int = 8) -> list[dict[str, Any]]:
    try:
        from arka.media.stock_brightdata import _extract_json, _results_list, _serp_request, is_configured
    except ImportError:
        return []
    if not is_configured():
        return []
    url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query, "num": str(max_results)})
    try:
        raw = _serp_request(url)
        data = _extract_json(raw)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for item in _results_list(data):
        link = str(item.get("link") or item.get("url") or item.get("href") or "").strip()
        if not link.startswith("http"):
            continue
        rows.append({
            "link": link,
            "title": str(item.get("title") or item.get("name") or "").strip(),
            "snippet": str(item.get("snippet") or item.get("description") or item.get("body") or "").strip(),
        })
        if len(rows) >= max_results:
            break
    return rows


def _search_platform(
    topic: str,
    platform_key: str,
    *,
    limit: int,
    search_fn: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    spec = PLATFORMS.get(platform_key)
    if not spec:
        return []
    query = f"{spec.site_query} {topic}"
    if platform_key == "reddit":
        query = f"{query} (programming OR python OR rust OR javascript OR golang OR devops)"
    fetch = search_fn or (lambda q, n: _duckduckgo_search(q, max_results=n))
    raw_results = fetch(query, limit)
    structured: list[dict[str, Any]] = []
    for row in raw_results:
        link = str(row.get("link") or "").strip()
        if not link:
            continue
        detected = _platform_for_link(link)
        if detected and detected != platform_key:
            continue
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("snippet") or "").strip()
        if not snippet and not title:
            continue
        platform = detected or platform_key
        structured.append({
            "platform": platform,
            "author": _author_from_link(link, platform),
            "snippet": snippet or title,
            "link": link,
            "relevance_score": _score_result(topic, title, snippet, platform),
        })
    structured.sort(key=lambda r: r["relevance_score"], reverse=True)
    return structured[:limit]


def lookup_payload(
    query: str,
    *,
    platforms: list[str] | None = None,
    limit: int = 5,
    use_cache: bool = True,
    search_fn: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    topic = (query or "").strip()
    if not topic:
        raise ValueError("query is required")
    selected = [p for p in (platforms or list(DEFAULT_PLATFORMS)) if p in PLATFORMS]
    if not selected:
        selected = list(DEFAULT_PLATFORMS)

    if use_cache:
        try:
            from arka.core.social_code_cache import get_cached_payload

            cached = get_cached_payload(topic, selected)
            if cached:
                return cached
        except ImportError:
            pass

    per_platform = max(1, min(limit, 10))
    merged: list[dict[str, Any]] = []
    for platform_key in selected:
        merged.extend(
            _search_platform(topic, platform_key, limit=per_platform, search_fn=search_fn)
        )
    merged.sort(key=lambda r: r["relevance_score"], reverse=True)
    results = merged[: max(1, min(limit, 30))]

    payload: dict[str, Any] = {
        "ok": True,
        "query": topic,
        "platforms": selected,
        "count": len(results),
        "cached": False,
        "results": results,
    }

    if use_cache and results:
        try:
            from arka.core.social_code_cache import set_cached_payload

            set_cached_payload(topic, payload, selected)
        except ImportError:
            pass

    return payload


def format_payload_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Social code lookup: {payload.get('query', '')}",
        f"Platforms: {', '.join(payload.get('platforms') or [])}",
    ]
    if payload.get("cached"):
        lines.append("(cached)")
    lines.append("")
    for idx, row in enumerate(payload.get("results") or [], 1):
        platform = row.get("platform") or "unknown"
        label = PLATFORMS.get(platform, PlatformSpec(platform, platform, "", frozenset())).label
        author = row.get("author") or "unknown"
        score = row.get("relevance_score", 0)
        lines.append(f"{idx}. [{label}] {author} (score {score})")
        lines.append(f"   {row.get('snippet', '')[:240]}")
        lines.append(f"   {row.get('link', '')}")
        lines.append("")
    if not payload.get("results"):
        lines.append("No results found.")
    return "\n".join(lines).rstrip()


def _parse_platform_arg(raw: str) -> list[str]:
    out: list[str] = []
    for part in (raw or "").split(","):
        norm = _normalize_platform_name(part.strip())
        if norm and norm not in out:
            out.append(norm)
    return out


def cmd_search(args: argparse.Namespace) -> int:
    platforms = _parse_platform_arg(args.platform) if args.platform else list(DEFAULT_PLATFORMS)
    payload = lookup_payload(
        " ".join(args.query),
        platforms=platforms,
        limit=max(1, int(args.limit)),
        use_cache=not args.no_cache,
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_payload_text(payload))
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    text = " ".join(args.text)
    routed = route_command(text)
    print(routed)
    return 0 if routed else 1


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Find code snippets and discussions on social platforms")
    sub = parser.add_subparsers(dest="cmd")

    p_search = sub.add_parser("search", help="Search social platforms for code discussions")
    p_search.add_argument("query", nargs="+", help="Topic or code query")
    p_search.add_argument(
        "--platform",
        help="Comma-separated platforms: twitter,reddit,github,devto,hackernews,stackoverflow",
    )
    p_search.add_argument("--limit", type=int, default=8)
    p_search.add_argument("--json", action="store_true")
    p_search.add_argument("--no-cache", action="store_true")
    p_search.set_defaults(func=cmd_search)

    p_route = sub.add_parser("route", help="Map NL text to social_code_lookup command")
    p_route.add_argument("text", nargs="+")
    p_route.set_defaults(func=cmd_route)

    args = parser.parse_args(argv)
    if args.cmd is None:
        if not argv:
            parser.print_help()
            return 1
        args = parser.parse_args(["search", *argv])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
