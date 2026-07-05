#!/usr/bin/env python3
"""Curated source registries per profession domain — fetch first, synthesize second."""

from __future__ import annotations

import re
from dataclasses import dataclass
try:
    from arka.stock.predictions import fetch_rss_headlines
except ImportError:

    def fetch_rss_headlines(feed_url: str, *, limit: int = 8) -> list[str]:
        try:
            import feedparser
        except ImportError:
            return []
        try:
            feed = feedparser.parse(feed_url)
            return [
                (entry.get("title") or "").strip()
                for entry in feed.entries[:limit]
                if (entry.get("title") or "").strip()
            ]
        except Exception:
            return []

_FEEDPARSER_WARNED = False


def _rss_available() -> bool:
    try:
        import feedparser  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass(frozen=True)
class RssSource:
    id: str
    label: str
    url: str
    limit: int = 6


@dataclass(frozen=True)
class DomainSources:
    """Trusted inputs for a domain — not role-play prompts."""

    domain_id: str
    rss: tuple[RssSource, ...] = ()
    search_bias: str = ""
    codebase_artifact: str | None = None
    bridge: str | None = None  # predictions-stocks | predictions-strategy | stock-bridge


SOURCE_REGISTRY: dict[str, DomainSources] = {
    "health": DomainSources(
        "health",
        rss=(
            RssSource("cdc", "CDC Media", "https://tools.cdc.gov/api/v2/resources/media/403372.rss"),
            RssSource("nih", "NIH News", "https://www.nih.gov/news-events/news-releases/rss.xml"),
            RssSource("who", "WHO News", "https://www.who.int/rss-feeds/news-english.xml"),
        ),
        search_bias="evidence-based clinical guidance site:cdc.gov OR site:nih.gov OR site:who.int",
    ),
    "nutrition": DomainSources(
        "nutrition",
        rss=(
            RssSource(
                "usda",
                "USDA Nutrition",
                "https://www.usda.gov/media/press-releases/rss.xml",
                limit=5,
            ),
            RssSource(
                "harvard-nutrition",
                "Harvard Nutrition Source",
                "https://www.hsph.harvard.edu/nutritionsource/feed/",
                limit=5,
            ),
        ),
        search_bias="dietary guidelines evidence-based nutrition site:hsph.harvard.edu OR site:usda.gov",
        codebase_artifact="codebase-nutrition",
    ),
    "startup": DomainSources(
        "startup",
        rss=(
            RssSource(
                "techcrunch-startups",
                "TechCrunch Startups",
                "https://techcrunch.com/category/startups/feed/",
                limit=6,
            ),
            RssSource(
                "yc-news",
                "Y Combinator Blog",
                "https://www.ycombinator.com/blog/rss/",
                limit=5,
            ),
        ),
        search_bias="startup founder playbook product-market fit fundraising",
        codebase_artifact="codebase-startup",
        bridge="predictions-strategy",
    ),
    "investor": DomainSources(
        "investor",
        rss=(
            RssSource(
                "markets",
                "Market headlines",
                "https://news.google.com/rss/search?q=stock+market+outlook&hl=en-US&gl=US&ceid=US:en",
            ),
            RssSource(
                "strategy",
                "Investment strategy",
                "https://news.google.com/rss/search?q=investment+strategy+outlook&hl=en-US&gl=US&ceid=US:en",
            ),
        ),
        search_bias="investment due diligence market analysis fundamentals",
        codebase_artifact="codebase-investor",
        bridge="predictions-stocks",
    ),
    "teacher": DomainSources(
        "teacher",
        rss=(
            RssSource(
                "edutopia",
                "Edutopia Teaching",
                "https://www.edutopia.org/rss.xml",
                limit=6,
            ),
            RssSource(
                "unesco-edu",
                "UNESCO Education",
                "https://www.unesco.org/en/rss.xml",
                limit=4,
            ),
        ),
        search_bias="lesson plan pedagogy curriculum evidence-based teaching site:edutopia.org OR site:unesco.org",
    ),
    "legal": DomainSources(
        "legal",
        rss=(
            RssSource(
                "law360",
                "Law360 Headlines",
                "https://www.law360.com/rss",
                limit=5,
            ),
            RssSource(
                "cornell-lii",
                "Cornell LII",
                "https://www.law.cornell.edu/rss/latest.xml",
                limit=5,
            ),
        ),
        search_bias="legal overview statute regulation traffic violation fine penalty (general information not legal advice)",
    ),
    "engineer": DomainSources(
        "engineer",
        search_bias="software engineering system design architecture best practices site:developer.mozilla.org OR site:docs.rs",
        codebase_artifact="codebase-engineer",
    ),
    "journalism": DomainSources(
        "journalism",
        rss=(
            RssSource(
                "reuters",
                "Reuters World",
                "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best",
                limit=6,
            ),
            RssSource(
                "bbc",
                "BBC News",
                "http://feeds.bbci.co.uk/news/rss.xml",
                limit=6,
            ),
            RssSource(
                "ap",
                "AP Top News",
                "https://apnews.com/apf-topnews?output=rss",
                limit=6,
            ),
            RssSource(
                "npr",
                "NPR News",
                "https://feeds.npr.org/1001/rss.xml",
                limit=5,
            ),
        ),
        search_bias="journalism broadcast writing ethics fact-check site:reuters.com OR site:apnews.com OR site:bbc.com",
    ),
    "marketing": DomainSources(
        "marketing",
        rss=(
            RssSource(
                "hubspot",
                "HubSpot Marketing",
                "https://blog.hubspot.com/marketing/rss.xml",
                limit=5,
            ),
            RssSource(
                "sej",
                "Search Engine Journal",
                "https://www.searchenginejournal.com/feed/",
                limit=5,
            ),
        ),
        search_bias="marketing strategy seo conversion copywriting site:hubspot.com OR site:searchenginejournal.com",
    ),
    "finance": DomainSources(
        "finance",
        rss=(
            RssSource(
                "sec",
                "SEC News",
                "https://www.sec.gov/news/pressreleases.rss",
                limit=5,
            ),
            RssSource(
                "irs",
                "IRS News",
                "https://www.irs.gov/newsroom/rss/news-releases",
                limit=5,
            ),
        ),
        search_bias="accounting gaap financial reporting site:sec.gov OR site:irs.gov OR site:fasb.org",
    ),
    "counselor": DomainSources(
        "counselor",
        rss=(
            RssSource(
                "nimh",
                "NIMH Science News",
                "https://www.nimh.nih.gov/rss/news.xml",
                limit=5,
            ),
            RssSource(
                "apa",
                "APA News",
                "https://www.apa.org/news/press/releases/rss",
                limit=5,
            ),
        ),
        search_bias="evidence-based mental health therapy site:nimh.nih.gov OR site:apa.org",
    ),
    "chef": DomainSources(
        "chef",
        rss=(
            RssSource(
                "usda-recipes",
                "USDA Recipes",
                "https://www.usda.gov/media/blog/rss.xml",
                limit=4,
            ),
            RssSource(
                "fda-food",
                "FDA Food Safety",
                "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/food-safety/rss.xml",
                limit=4,
            ),
        ),
        search_bias="culinary technique recipe food safety site:fda.gov OR site:usda.gov OR site:seriouseats.com",
    ),
}


def _source_pack(domain_id: str) -> DomainSources | None:
    pack = SOURCE_REGISTRY.get(domain_id)
    if pack is not None:
        return pack
    try:
        from arka.agent.profession_plugins import plugin_sources

        return plugin_sources().get(domain_id)
    except ImportError:
        return None


def list_sources(domain_id: str) -> list[tuple[str, str]]:
    """Return (source_id, human label) for a domain."""
    pack = _source_pack(domain_id)
    if not pack:
        return []
    out: list[tuple[str, str]] = []
    for feed in pack.rss:
        out.append((feed.id, f"RSS: {feed.label}"))
    if pack.search_bias:
        out.append(("web", "Web search (biased to trusted domains)"))
    if pack.codebase_artifact:
        out.append((pack.codebase_artifact, f"Local codebase index ({pack.codebase_artifact})"))
    if pack.bridge:
        out.append((pack.bridge, f"Data bridge ({pack.bridge})"))
    out.append(("memory", "User memory (facts you saved)"))
    return out


def _build_search_query(query: str, domain_id: str, search_bias: str) -> str:
    q = query.strip()
    if domain_id == "legal" and re.search(
        r"(?i)\b(fine|penalty|traffic|violation|ticket|speeding|dui|dwi|infraction|motor vehicle|sentencing)\b",
        q,
    ):
        try:
            from arka.agent.chat import get_live_location, ground_search_query

            ctx = get_live_location()
            city = str(ctx.get("city") or "").strip()
            if city and city.lower() not in ("unknown",) and city.lower() not in q.lower():
                q = f"{q} {city}"
            return ground_search_query(q)
        except ImportError:
            return q
    if search_bias:
        return f"{search_bias} {q}".strip()
    return q


def _fetch_web(query: str, search_bias: str, *, deep: bool, domain_id: str = "") -> tuple[str, str]:
    import concurrent.futures

    def _inner() -> tuple[str, str]:
        try:
            from arka.agent.chat import scrape_search_results, snippet_lookup
        except ImportError:
            return "", ""
        search_q = _build_search_query(query, domain_id, search_bias)
        snip = snippet_lookup(search_q)
        min_words = 500 if deep else 200
        limit = 8 if deep else 4
        web = scrape_search_results(search_q, min_words=min_words, hard_limit=limit)
        parts: list[str] = []
        if snip:
            parts.append(snip)
        if web:
            parts.append(web[:8000 if deep else 5000])
        if not parts:
            return "", ""
        return "\n\n".join(parts), "web"

    timeout = 90 if deep else 45
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_inner)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            import sys

            print(f"Web source timed out after {timeout}s — continuing with other sources.", file=sys.stderr)
            return "", ""


def _fetch_codebase(query: str, artifact: str) -> tuple[str, str]:
    import concurrent.futures

    def _inner() -> tuple[str, str]:
        try:
            from arka.stock.turboquant_rag import search_documents, use_turboquant

            if not use_turboquant():
                return _local_project_fallback(artifact, query)
            code, ctx = search_documents(query, artifact=artifact, max_chars=9000)
            if code == 0 and ctx.strip():
                return ctx.strip(), artifact
        except Exception:
            pass
        return _local_project_fallback(artifact, query)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_inner)
        try:
            return fut.result(timeout=20)
        except concurrent.futures.TimeoutError:
            return _local_project_fallback(artifact, query)


def _local_project_fallback(artifact: str, query: str) -> tuple[str, str]:
    """README + manifest path when TurboQuant index is missing."""
    m = re.match(r"codebase-(\w+)", artifact)
    if not m:
        return "", ""
    domain_id = m.group(1)
    root = None
    try:
        from arka.agent.profession_plugins import plugin_project_path

        root = plugin_project_path(domain_id)
    except ImportError:
        pass
    if not root:
        try:
            from arka.agent.profession_projects import profession_project_path

            root = profession_project_path(domain_id)
        except ImportError:
            return "", ""
    if not root or not root.is_dir():
        return "", ""
    parts = [f"Project path: {root}"]
    readme = root / "README.md"
    if readme.is_file():
        parts.append(readme.read_text(encoding="utf-8", errors="replace")[:4000])
    return "\n\n".join(parts), f"local-{domain_id}"


def _fetch_bridge(bridge: str, query: str, *, deep: bool) -> tuple[str, list[str]]:
    sources: list[str] = []
    blocks: list[str] = []

    if bridge == "predictions-stocks":
        try:
            from arka.stock.predictions import gather_context

            ctx, srcs = gather_context(query, "stocks", deep=deep, amount=None)
            if ctx.strip():
                blocks.append(ctx)
                sources.extend(srcs)
        except Exception:
            pass
        try:
            from arka.stock.bridge import gather_context as stock_ctx

            proj = stock_ctx(include_ml=deep)
            if proj.strip():
                blocks.append(f"[Stock analysis project]\n{proj[:6000]}")
                sources.append("stock_analysis")
        except Exception:
            pass
        return "\n\n".join(blocks), sources

    if bridge == "predictions-strategy":
        try:
            from arka.stock.predictions import gather_context

            ctx, srcs = gather_context(query, "strategy", deep=deep, amount=None)
            if ctx.strip():
                blocks.append(ctx)
                sources.extend(srcs)
        except Exception:
            pass
        return "\n\n".join(blocks), sources

    if bridge == "stock-bridge":
        try:
            from arka.stock.bridge import gather_context as stock_ctx

            proj = stock_ctx(include_ml=deep)
            if proj.strip():
                return proj[:6000], ["stock_analysis"]
        except Exception:
            pass
    return "", []


def _memory_facts() -> tuple[str, str]:
    try:
        from arka.agent.professions import MEMORY_FILE
    except ImportError:
        from arka.paths import cache_dir

        memory_file = cache_dir() / "memory.json"
    else:
        memory_file = MEMORY_FILE

    if not memory_file.is_file():
        return "", ""
    try:
        import json

        items = json.loads(memory_file.read_text(encoding="utf-8"))
    except Exception:
        return "", ""
    if not isinstance(items, list):
        return "", ""
    lines = [str(r.get("text", "")).strip() for r in items[-12:] if r.get("text")]
    relevant = [
        ln
        for ln in lines
        if re.search(
            r"(?i)profession|diet|allerg|work|prefer|health|nutrition|founder|teacher|invest|"
            r"journal|anchor|market|legal|finance|chef|counsel|therapy",
            ln,
        )
    ]
    if not relevant:
        relevant = lines[-5:]
    if not relevant:
        return "", ""
    body = "User context:\n" + "\n".join(f"- {ln}" for ln in relevant if ln)
    return body, "memory"


def gather_profession_context(
    domain_id: str,
    query: str,
    *,
    deep: bool = False,
) -> tuple[str, list[str]]:
    """Collect all curated sources for a domain. Same inputs regardless of LLM model."""
    pack = _source_pack(domain_id)
    if not pack:
        return "", []

    blocks: list[str] = []
    sources: list[str] = []

    global _FEEDPARSER_WARNED
    if pack.rss and not _rss_available() and not _FEEDPARSER_WARNED:
        import sys

        print(
            "RSS feeds skipped — install feedparser (pip install feedparser).",
            file=sys.stderr,
        )
        _FEEDPARSER_WARNED = True

    mem, mem_id = _memory_facts()
    if mem:
        blocks.append(f"[{mem_id}]\n{mem}")
        sources.append(mem_id)

    for feed in pack.rss:
        headlines = fetch_rss_headlines(feed.url, limit=feed.limit)
        if headlines:
            body = "\n".join(f"- {h}" for h in headlines)
            blocks.append(f"[{feed.id}: {feed.label}]\n{body}")
            sources.append(feed.id)

    if pack.codebase_artifact:
        ctx, src = _fetch_codebase(query, pack.codebase_artifact)
        if ctx:
            blocks.append(f"[{src}]\n{ctx}")
            sources.append(src)

    if pack.bridge:
        ctx, bridge_srcs = _fetch_bridge(pack.bridge, query, deep=deep)
        if ctx:
            blocks.append(ctx)
            sources.extend(bridge_srcs)

    web, web_id = _fetch_web(query, pack.search_bias, deep=deep, domain_id=domain_id)
    if web:
        blocks.append(f"[{web_id}]\n{web}")
        if web_id not in sources:
            sources.append(web_id)

    return "\n\n---\n\n".join(blocks), sources


def index_domain_codebase(domain_id: str) -> tuple[bool, str]:
    """Index cloned profession project for doc_ask / TurboQuant (run during setup)."""
    pack = _source_pack(domain_id)
    if not pack or not pack.codebase_artifact:
        return False, "no codebase source for domain"
    try:
        from arka.agent.profession_projects import profession_project_path
        from arka.stock.turboquant_rag import index_codebase, use_turboquant
    except ImportError as exc:
        return False, str(exc)
    if not use_turboquant():
        return False, "TurboQuant disabled"
    root = None
    try:
        from arka.agent.profession_plugins import plugin_project_path

        root = plugin_project_path(domain_id)
    except ImportError:
        pass
    if not root:
        root = profession_project_path(domain_id)
    if not root or not root.is_dir():
        return False, "project not cloned"
    name = domain_id
    files, chunks, detail = index_codebase(root, name)
    if files <= 0:
        return False, detail
    return True, f"{pack.codebase_artifact}: {detail}"
