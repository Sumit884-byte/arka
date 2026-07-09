"""Retail source targets for live product price lookup."""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

# (id, label, site bias fragment)
INDIA_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("apple_in", "Apple India", "site:apple.com/in/shop OR site:apple.com/in/buy-"),
    ("amazon_in", "Amazon India", "site:amazon.in inurl:/dp/"),
    ("flipkart", "Flipkart", "site:flipkart.com inurl:/p/"),
)

US_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("apple_us", "Apple US", "site:apple.com/shop OR site:apple.com/buy-"),
    ("amazon_us", "Amazon US", "site:amazon.com inurl:/dp/"),
    ("bestbuy", "Best Buy", "site:bestbuy.com inurl:/site/"),
)

_REGION_SOURCES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "india": INDIA_SOURCES,
    "us": US_SOURCES,
}

_SOURCE_LABELS: dict[str, str] = {sid: label for sid, label, _ in INDIA_SOURCES + US_SOURCES}

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

_EXCLUDED_PATH_RE = re.compile(
    r"(?i)(?:/newsroom/|/news/|/press/|/support/|/legal/|/privacy/|/today/|/accessibility/)"
)

_RETAILER_URL_PATTERNS: dict[str, re.Pattern[str]] = {
    "apple_in": re.compile(r"(?i)apple\.com/in/(?:shop|buy-)"),
    "apple_us": re.compile(
        r"(?i)apple\.com/(?:shop|buy-)(?!.*/(?:newsroom|news|support|press)/)"
    ),
    "amazon_in": re.compile(r"(?i)amazon\.in/(?:.*/)?(?:dp|gp/product|gp/aw/d)/[A-Z0-9]{8,}"),
    "amazon_us": re.compile(r"(?i)amazon\.com/(?:.*/)?(?:dp|gp/product|gp/aw/d)/[A-Z0-9]{8,}"),
    "flipkart": re.compile(r"(?i)flipkart\.com/[\w\-]+/p/[\w\-]+"),
    "bestbuy": re.compile(r"(?i)bestbuy\.com/site/[\w\-]+/[\w\-]+\.p"),
}

_INR_PRICE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"₹\s*([\d,]+(?:\.\d{2})?)"), "₹"),
    (re.compile(r"(?i)\bINR\s*([\d,]+(?:\.\d{2})?)"), "INR"),
    (re.compile(r"(?i)\bRs\.?\s*([\d,]+(?:\.\d{2})?)"), "₹"),
)

_USD_PRICE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)"), "$"),
    (re.compile(r"(?i)\bUSD\s*([\d,]+(?:\.\d{2})?)"), "USD"),
)

_MIN_PRICE: dict[str, int] = {"india": 1000, "us": 50}

_USER_AGENT = "Mozilla/5.0 (compatible; arka-price-check/1.0)"


@dataclass(frozen=True)
class PriceSearchQuery:
    source_id: str
    label: str
    query: str


@dataclass(frozen=True)
class PriceListing:
    model: str
    price: str
    source: str
    url: str


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


def is_excluded_retail_url(url: str) -> bool:
    """True when the URL path is a non-shop page (newsroom, support, etc.)."""
    if not url:
        return True
    parsed = urlparse(url)
    path = parsed.path or ""
    if _EXCLUDED_PATH_RE.search(path):
        return True
    host = (parsed.netloc or "").lower()
    if "newsroom" in host:
        return True
    return False


def retailer_for_url(url: str) -> tuple[str, str] | None:
    """Return (source_id, label) when URL matches a known shop/product page."""
    if is_excluded_retail_url(url):
        return None
    lower = url.lower()
    if "/in/" in lower and re.search(r"apple\.com/(?:shop|buy-)", lower):
        if _RETAILER_URL_PATTERNS["apple_in"].search(url):
            return ("apple_in", "Apple India")
        return None
    for sid, pattern in _RETAILER_URL_PATTERNS.items():
        if sid == "apple_in":
            continue
        if pattern.search(url):
            return (sid, _SOURCE_LABELS[sid])
    if _RETAILER_URL_PATTERNS["apple_in"].search(url):
        return ("apple_in", "Apple India")
    return None


def is_shop_product_url(url: str, source_id: str | None = None) -> bool:
    """True when URL is a retailer shop or product listing page."""
    if is_excluded_retail_url(url):
        return False
    retailer = retailer_for_url(url)
    if retailer is None:
        return False
    if source_id is None:
        return True
    return retailer[0] == source_id


def check_url_reachable(url: str, *, timeout: int = 10) -> bool:
    """Return True when the URL responds with HTTP 2xx."""
    headers = {"User-Agent": _USER_AGENT}
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return 200 <= resp.status < 400
        except urllib.error.HTTPError as exc:
            if exc.code in (405, 501) and method == "HEAD":
                continue
            return False
        except Exception:
            if method == "HEAD":
                continue
            return False
    return False


_MONTHLY_CONTEXT_RE = re.compile(r"(?i)^\s*(?:/|per)\s*(?:month|mo)\b")


def extract_prices_from_content(text: str, *, region: str) -> list[str]:
    """Extract normalized retail prices from scraped page text."""
    if not text:
        return []
    patterns = _INR_PRICE_PATTERNS if region == "india" else _USD_PRICE_PATTERNS
    fallback = _USD_PRICE_PATTERNS if region == "india" else _INR_PRICE_PATTERNS
    min_value = _MIN_PRICE.get(region, 50)

    candidates: list[tuple[int, str]] = []
    seen_values: set[int] = set()

    for group in (patterns, fallback):
        for pat, symbol in group:
            for match in pat.finditer(text):
                amount = match.group(1)
                value = _price_to_int(amount)
                if value is None or value < min_value or value in seen_values:
                    continue
                tail = text[match.end() : match.end() + 12]
                if _MONTHLY_CONTEXT_RE.search(tail):
                    continue
                seen_values.add(value)
                if symbol in ("₹", "$"):
                    formatted = f"{symbol}{amount}"
                else:
                    formatted = f"{symbol} {amount}"
                candidates.append((value, formatted))
        if candidates:
            break

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [price for _, price in candidates]


def build_price_search_queries(product: str, *, region: str) -> list[PriceSearchQuery]:
    """Build targeted search queries for retail shop/product pages."""
    text = product.strip()
    if not text:
        return []
    sources = sources_for_region(region)
    out: list[PriceSearchQuery] = []

    site_bias = " OR ".join(f"({s[2]})" for s in sources)
    out.append(
        PriceSearchQuery("combined", f"Retail ({region})", f"({site_bias}) {text} buy price")
    )

    for sid, label, bias in sources:
        out.append(PriceSearchQuery(sid, label, f"{bias} {text}"))

    return out


def _model_from_title(title: str, product: str) -> str:
    cleaned = re.sub(r"(?i)\s*[-–|:].*$", "", title or "").strip()
    cleaned = re.sub(r"(?i)\s+(?:price|buy|shop).*$", "", cleaned).strip()
    if cleaned and len(cleaned) > 3:
        return cleaned[:120]
    return product.strip().title() or product


def _price_to_int(amount: str) -> int | None:
    normalized = amount.replace(",", "")
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]
    if not normalized.isdigit():
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def _dedupe_listings(listings: list[PriceListing]) -> list[PriceListing]:
    seen_sources: set[str] = set()
    seen_urls: set[str] = set()
    out: list[PriceListing] = []
    for listing in listings:
        if listing.source in seen_sources or listing.url in seen_urls:
            continue
        seen_sources.add(listing.source)
        seen_urls.add(listing.url)
        out.append(listing)
    return out


def fetch_price_listings(
    product: str,
    *,
    region: str,
    deep: bool = True,
) -> tuple[list[PriceListing], list[str]]:
    """Search shop pages, validate URLs, and extract prices from scraped HTML."""
    try:
        from arka.agent.chat import duckduckgo_search, scrape_url
    except ImportError:
        return [], []

    searches = build_price_search_queries(product, region=region)
    if not searches:
        return [], []

    allowed_sources = {s[0] for s in sources_for_region(region)}
    max_results = 8 if deep else 5
    max_queries = len(searches) if deep else min(3, len(searches))

    listings: list[PriceListing] = []
    searched_labels: list[str] = []
    seen_labels: set[str] = set()
    seen_urls: set[str] = set()

    for item in searches[:max_queries]:
        if item.label not in seen_labels:
            searched_labels.append(item.label)
            seen_labels.add(item.label)

        results = duckduckgo_search(item.query, max_results=max_results)
        for res in results:
            link = (res.get("link") or "").strip()
            if not link or link in seen_urls:
                continue

            retailer = retailer_for_url(link)
            if retailer is None or retailer[0] not in allowed_sources:
                continue

            seen_urls.add(link)
            if not check_url_reachable(link):
                continue

            page = scrape_url(link)
            title = res.get("title") or ""
            snippet = res.get("snippet") or ""
            content = "\n".join(part for part in (title, snippet, page) if part)
            prices = extract_prices_from_content(content, region=region)
            if not prices:
                continue

            _, label = retailer
            listings.append(
                PriceListing(
                    model=_model_from_title(title, product),
                    price=prices[0],
                    source=label,
                    url=link,
                )
            )

    return _dedupe_listings(listings), searched_labels


def format_price_check_output(
    listings: list[PriceListing],
    *,
    product: str,
    region: str,
    searched_labels: list[str],
    retrieved_on: str | None = None,
) -> str:
    """Format deterministic price-check output from validated listings."""
    today = retrieved_on or date.today().isoformat()
    if not listings:
        default_labels = ", ".join(label for _, label in list_price_sources(region))
        searched = ", ".join(searched_labels) if searched_labels else default_labels
        return (
            f"No live prices found for {product} ({region}).\n"
            f"Searched: {searched}\n"
            f"Date retrieved: {today}\n"
            "Try a more specific model name or check retailer sites directly."
        )
    lines = [f"  {item.model} | {item.price} | {item.source} | {item.url}" for item in listings]
    lines.append(f"Date retrieved: {today}")
    return "\n".join(lines)


def fetch_price_web_context(product: str, *, region: str, deep: bool) -> tuple[str, list[str]]:
    """Scrape retail sources; return (context, labels consulted)."""
    listings, labels = fetch_price_listings(product, region=region, deep=deep)
    if not listings:
        return "", labels
    parts = [
        f"{item.model} — {item.price} — {item.url}"
        for item in listings
    ]
    return "\n".join(parts), labels


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
