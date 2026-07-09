"""Retail source targets for live product price lookup."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date

# (id, label, site bias fragment)
INDIA_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("apple_in", "Apple India", "site:apple.com/in"),
    ("amazon_in", "Amazon India", "site:amazon.in"),
    ("flipkart", "Flipkart", "site:flipkart.com"),
)

US_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("apple_us", "Apple US", "site:apple.com"),
    ("amazon_us", "Amazon US", "site:amazon.com"),
    ("bestbuy", "Best Buy", "site:bestbuy.com"),
)

_REGION_SOURCES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "india": INDIA_SOURCES,
    "us": US_SOURCES,
}

_PRICE_EXCLUDE_RE = re.compile(
    r"(?i)\b(?:stock|crypto|bitcoin|ethereum|btc|eth|solana|share|ticker|"
    r"price\s+target|price\s+action|price\s+alert|house\s+price|rent|"
    r"gas\s+price|oil\s+price|gold\s+price|silver\s+price)\b"
)

_REGION_IN_RE = re.compile(
    r"(?i)\b(?:in\s+india|india|indian|inr|₹|rupees?)\b"
)
_REGION_US_RE = re.compile(
    r"(?i)\b(?:in\s+(?:the\s+)?(?:us|usa|america)|united\s+states|usd|\$|dollars?)\b"
)

_EXTRACT_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"(?i)^price_check\s+(.+)$"), 1),
    (re.compile(r"(?i)^(?:what(?:'s| is)\s+)?(?:the\s+)?price\s+of\s+(.+)$"), 1),
    (re.compile(r"(?i)^cost\s+of\s+(?:the\s+)?(.+)$"), 1),
    (re.compile(r"(?i)^how\s+much\s+(?:is|are|does)\s+(?:the\s+)?(.+?)(?:\s+cost)?$"), 1),
    (re.compile(r"(?i)^how\s+much\s+(?:for|to\s+get)\s+(?:a\s+)?(.+)$"), 1),
    (re.compile(r"(?i)^(.+?)\s+price\s+right\s+now$"), 1),
    (re.compile(r"(?i)^(.+?)\s+price\s+in\s+(?:india|us|usa|america)$"), 1),
    (re.compile(r"(?i)^(.+?)\s+price$"), 1),
)

_TRAILING_NOISE_RE = re.compile(
    r"(?i)\s+(?:right\s+now|today|currently|now|please|thanks?|"
    r"in\s+(?:india|us|usa|america|the\s+us)|india|usa)\s*$"
)


@dataclass(frozen=True)
class PriceSearchQuery:
    source_id: str
    label: str
    query: str


def is_price_check_query(cmd: str) -> bool:
    """True when the user wants a retail product price lookup."""
    text = cmd.strip()
    if not text:
        return False
    if _PRICE_EXCLUDE_RE.search(text):
        return False
    if re.match(r"(?i)^price_check\b", text):
        return True
    triggers = (
        r"(?i)\b(?:price\s+of|cost\s+of|what(?:'s| is)\s+the\s+price\s+of)\s+",
        r"(?i)\bhow\s+much\s+(?:is|are|does|for)\s+(?:the\s+)?(?:a\s+)?",
        r"(?i)\b.+\s+price\s+(?:right\s+now|in\s+(?:india|us|usa))\b",
        r"(?i)\b.+\s+price\s*$",
    )
    return any(re.search(pat, text) for pat in triggers)


def detect_price_region(query: str) -> str:
    """Return 'india' or 'us' from explicit region hints in the query."""
    if _REGION_IN_RE.search(query):
        return "india"
    if _REGION_US_RE.search(query):
        return "us"
    env = os.environ.get("ARKA_PRICE_REGION", "").strip().lower()
    if env in ("india", "in"):
        return "india"
    if env in ("us", "usa"):
        return "us"
    return "india"


def extract_product_name(query: str) -> str:
    """Strip price-intent phrasing and return the product name."""
    text = query.strip()
    if not text:
        return ""
    text = re.sub(r"(?i)^price_check\s+", "", text).strip()
    for pat, group in _EXTRACT_PATTERNS:
        m = pat.match(text)
        if m:
            product = m.group(group).strip()
            product = _TRAILING_NOISE_RE.sub("", product).strip(" ?.,!")
            if product:
                return product
    return _TRAILING_NOISE_RE.sub("", text).strip(" ?.,!")


def parse_price_query(query: str) -> tuple[str, str]:
    """Return (product_name, region) for a price lookup query."""
    product = extract_product_name(query)
    region = detect_price_region(query)
    return product, region


def sources_for_region(region: str) -> list[tuple[str, str, str]]:
    return list(_REGION_SOURCES.get(region, INDIA_SOURCES))


def list_price_sources(region: str | None = None) -> list[tuple[str, str]]:
    reg = region or "india"
    return [(s[0], s[1]) for s in sources_for_region(reg)]


def build_price_search_queries(product: str, *, region: str) -> list[PriceSearchQuery]:
    """Build targeted search queries for retail price pages."""
    text = product.strip()
    if not text:
        return []
    sources = sources_for_region(region)
    out: list[PriceSearchQuery] = []

    site_bias = " OR ".join(s[2] for s in sources)
    out.append(
        PriceSearchQuery("combined", f"Retail ({region})", f"{site_bias} {text} price buy")
    )

    for sid, label, bias in sources:
        out.append(PriceSearchQuery(sid, label, f"{bias} {text} price"))

    out.append(PriceSearchQuery("general", "General retail", f"{text} price {region} buy"))
    return out


def fetch_price_web_context(product: str, *, region: str, deep: bool) -> tuple[str, list[str]]:
    """Scrape retail sources; return (context, labels consulted)."""
    try:
        from arka.agent.chat import scrape_search_results, snippet_lookup
    except ImportError:
        return "", []

    searches = build_price_search_queries(product, region=region)
    if not searches:
        return "", []

    min_words = 700 if deep else 400
    pages_per_query = 6 if deep else 4
    max_queries = 5 if deep else 3

    parts: list[str] = []
    labels: list[str] = []
    seen_labels: set[str] = set()

    snip = snippet_lookup(searches[0].query)
    if snip:
        parts.append(snip)

    for item in searches[:max_queries]:
        web = scrape_search_results(
            item.query,
            min_words=min_words // max_queries,
            hard_limit=pages_per_query,
        )
        if web:
            parts.append(f"[{item.label}]\n{web}")
            if item.label not in seen_labels:
                labels.append(item.label)
                seen_labels.add(item.label)
        if len(" ".join(parts).split()) >= min_words:
            break

    if not parts:
        return "", labels
    return "\n\n".join(parts)[:12000], labels


def price_check_prompt(
    product: str,
    region: str,
    web_ctx: str,
    source_labels: list[str],
    *,
    retrieved_on: str | None = None,
) -> tuple[str, str]:
    """Return (system, user) prompts constrained to scraped snippet prices."""
    today = retrieved_on or date.today().isoformat()
    labels = ", ".join(source_labels) if source_labels else "retail sites"
    system = (
        "You are a product price lookup assistant. "
        "Use ONLY prices and model names explicitly present in the provided scraped snippets. "
        "Do NOT invent, estimate, or recall prices from memory. "
        "If a price is not in the snippets, do not include it. "
        "Format each found price on its own line as: "
        "Model | Price | Source | URL "
        "Use the retailer name for Source and include the page URL when available in snippets. "
        "If no concrete prices appear in the snippets, say clearly that live prices could not be fetched "
        f"and list which sources were searched ({labels}). "
        f"Always end with: Date retrieved: {today}"
    )
    user = (
        f"Product: {product}\n"
        f"Region: {region}\n"
        f"Sources searched: {labels}\n\n"
        f"Scraped snippets:\n\n{web_ctx}\n\n"
        "List every price you can verify from the snippets above. "
        "Do not add prices that are not in the snippets."
    )
    return system, user
