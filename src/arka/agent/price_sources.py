"""Retail source targets for live product price lookup."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import quote_plus, urlparse

PriceProductCategory = Literal["apple", "personal_care", "generic"]

# (id, label, site bias fragment)
INDIA_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("apple_in", "Apple India", "site:apple.com/in/shop OR site:apple.com/in/buy-"),
    ("amazon_in", "Amazon India", "site:amazon.in"),
    ("flipkart", "Flipkart", "site:flipkart.com"),
    ("nykaa", "Nykaa", "site:nykaa.com"),
    ("croma", "Croma", "site:croma.com"),
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
    "nykaa": re.compile(r"(?i)nykaa\.com/[\w\-/]+/p/\d+"),
    "croma": re.compile(r"(?i)croma\.com/[\w\-/]+/p/\d+"),
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
_MIN_PRICE_BY_CATEGORY: dict[PriceProductCategory, dict[str, int]] = {
    "apple": {"india": 1000, "us": 50},
    "generic": {"india": 100, "us": 10},
    "personal_care": {"india": 100, "us": 10},
}

_CATEGORY_SOURCES: dict[PriceProductCategory, dict[str, tuple[str, ...]]] = {
    "apple": {
        "india": ("apple_in", "amazon_in", "flipkart"),
        "us": ("apple_us", "amazon_us", "bestbuy"),
    },
    "generic": {
        "india": ("amazon_in", "flipkart"),
        "us": ("amazon_us", "bestbuy"),
    },
    "personal_care": {
        "india": ("nykaa", "amazon_in", "flipkart"),
        "us": ("amazon_us", "bestbuy"),
    },
}

_PERSONAL_CARE_RE = re.compile(
    r"(?i)\b(?:skincare|shampoo|conditioner|moisturiz(?:er|e|ing)?|serum|lotion|cleanser|"
    r"toothpaste|deodorant|face wash|toner|sunscreen|body wash|hair oil|"
    r"makeup|lipstick|cosmetic|face cream|body lotion|hair mask|face mask)\b"
)

_GENERIC_CONSUMER_RE = re.compile(
    r"(?i)\b(?:electric brush|toothbrush|blender|vacuum|mixer|grinder|kettle|"
    r"iron|fan|heater|purifier|microwave|refrigerator|washing machine|"
    r"dryer|trimmer|shaver|hair dryer|straightener|pressure cooker|air fryer|"
    r"coffee maker|juicer|water purifier)\b"
)

_APPLE_HINT_RE = re.compile(
    r"(?i)\b(?:macbook|iphone|ipad|airpods|apple watch|homepod|imac|mac mini|"
    r"mac studio|mac pro|apple tv)\b"
)

_USER_AGENT = "Mozilla/5.0 (compatible; arka-price-check/1.0)"

# Apple shop category pages without a model slug (e.g. /shop/buy-mac) show misleading prices.
_APPLE_CATEGORY_ONLY_RE = re.compile(
    r"(?i)/shop/buy-(?:mac|iphone|ipad|watch|airpods|homepod|appletv)/?$"
)

# Product-line resolver: (pattern, buy-path segment, display name)
_APPLE_PRODUCT_LINES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"(?i)\bmacbook\s+pro\b"), "buy-mac/macbook-pro", "MacBook Pro"),
    (re.compile(r"(?i)\bmacbook\s+air\b"), "buy-mac/macbook-air", "MacBook Air"),
    (re.compile(r"(?i)\bmac\s+mini\b"), "buy-mac/mac-mini", "Mac mini"),
    (re.compile(r"(?i)\b(?:imac|i\s*mac)\b"), "buy-mac/imac", "iMac"),
    (re.compile(r"(?i)\bmac\s+studio\b"), "buy-mac/mac-studio", "Mac Studio"),
    (re.compile(r"(?i)\bmac\s+pro\b(?!\s+\d)"), "buy-mac/mac-pro", "Mac Pro"),
    (re.compile(r"(?i)\biphone\s+16\s+pro\s+max\b"), "buy-iphone/iphone-16-pro", "iPhone 16 Pro Max"),
    (re.compile(r"(?i)\biphone\s+16\s+pro\b"), "buy-iphone/iphone-16-pro", "iPhone 16 Pro"),
    (re.compile(r"(?i)\biphone\s+16\s+plus\b"), "buy-iphone/iphone-16", "iPhone 16 Plus"),
    (re.compile(r"(?i)\biphone\s+16\b"), "buy-iphone/iphone-16", "iPhone 16"),
    (re.compile(r"(?i)\biphone\s+15\b"), "buy-iphone/iphone-15", "iPhone 15"),
    (re.compile(r"(?i)\bipad\s+pro\b"), "buy-ipad/ipad-pro", "iPad Pro"),
    (re.compile(r"(?i)\bipad\s+air\b"), "buy-ipad/ipad-air", "iPad Air"),
    (re.compile(r"(?i)\bipad\s+mini\b"), "buy-ipad/ipad-mini", "iPad mini"),
    (re.compile(r"(?i)\bipad\b"), "buy-ipad/ipad", "iPad"),
    (re.compile(r"(?i)\bairpods\s+pro\b"), "buy-airpods/airpods-pro", "AirPods Pro"),
    (re.compile(r"(?i)\bairpods\b"), "buy-airpods/airpods", "AirPods"),
    (re.compile(r"(?i)\bapple\s+watch\s+ultra\b"), "buy-watch/apple-watch-ultra", "Apple Watch Ultra"),
    (re.compile(r"(?i)\bapple\s+watch\b"), "buy-watch/apple-watch", "Apple Watch"),
)

_APPLE_SHOP_BASE: dict[str, str] = {
    "india": "https://www.apple.com/in/shop/",
    "us": "https://www.apple.com/shop/",
}

_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)

_APPLE_PRICE_KEY_RE = re.compile(
    r'"([0-9]+inch[^"]*?)":\{"comparativeDisplayPrice"[^}]*?"amount":([\d.]+)'
)

_CHIP_LABELS: dict[str, str] = {
    "m5": "M5",
    "m5pro": "M5 Pro",
    "m5max": "M5 Max",
    "m4": "M4",
    "m4pro": "M4 Pro",
    "m4max": "M4 Max",
    "m3": "M3",
    "m3pro": "M3 Pro",
    "m3max": "M3 Max",
    "m2": "M2",
    "m1": "M1",
}


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


def detect_price_product_category(product: str) -> PriceProductCategory:
    """Classify a product for retailer routing: apple, personal_care, or generic."""
    text = product.strip()
    if not text:
        return "generic"
    if resolve_apple_product_line(text) is not None or _APPLE_HINT_RE.search(text):
        return "apple"
    if _PERSONAL_CARE_RE.search(text):
        return "personal_care"
    if _GENERIC_CONSUMER_RE.search(text):
        return "generic"
    return "generic"


def sources_for_product(product: str, *, region: str) -> list[tuple[str, str, str]]:
    """Return retailer sources appropriate for the product category."""
    category = detect_price_product_category(product)
    allowed = _CATEGORY_SOURCES.get(category, _CATEGORY_SOURCES["generic"]).get(
        region, _CATEGORY_SOURCES["generic"]["india"]
    )
    return [s for s in sources_for_region(region) if s[0] in allowed]


def list_price_sources(region: str | None = None, product: str | None = None) -> list[tuple[str, str]]:
    reg = region or "india"
    if product:
        return [(s[0], s[1]) for s in sources_for_product(product, region=reg)]
    return [(s[0], s[1]) for s in sources_for_region(reg)]


def is_category_only_apple_url(url: str) -> bool:
    """True for Apple shop category pages without a product-line slug."""
    if not url:
        return False
    parsed = urlparse(url)
    path = (parsed.path or "").rstrip("/")
    if not _APPLE_CATEGORY_ONLY_RE.search(path):
        return False
    host = (parsed.netloc or "").lower()
    return "apple.com" in host


def resolve_apple_product_line(product: str) -> tuple[str, str] | None:
    """Return (shop path segment, display name) for a known Apple product line."""
    text = product.strip()
    if not text:
        return None
    for pattern, path, name in _APPLE_PRODUCT_LINES:
        if pattern.search(text):
            return path, name
    return None


def resolve_apple_shop_url(product: str, *, region: str) -> str | None:
    """Build a direct Apple shop URL for a known product line."""
    line = resolve_apple_product_line(product)
    if line is None:
        return None
    path, _ = line
    base = _APPLE_SHOP_BASE.get(region, _APPLE_SHOP_BASE["india"])
    return f"{base}{path}"


def fetch_page_html(url: str, *, timeout: int = 12) -> str:
    """Fetch raw HTML for structured price extraction."""
    headers = {"User-Agent": _USER_AGENT}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _format_retail_price(amount: float | int, *, region: str) -> str:
    value = int(round(float(amount)))
    if region == "india":
        text = str(value)
        if len(text) <= 3:
            grouped = text
        else:
            head, tail = text[:-3], text[-3:]
            parts: list[str] = []
            while head:
                parts.insert(0, head[-2:])
                head = head[:-2]
            grouped = ",".join(parts + [tail])
        return f"₹{grouped}"
    return f"${value:,}"


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def _model_from_price_key(price_key: str, product_line: str) -> str:
    """Turn an Apple priceKey like 14inch-spaceblack-standard-m5-10-10 into a label."""
    size_match = re.search(r"(\d+)inch", price_key, re.I)
    size = f'{size_match.group(1)}-inch ' if size_match else ""

    chip_label = ""
    for token in price_key.lower().split("-"):
        if token in _CHIP_LABELS:
            chip_label = _CHIP_LABELS[token]
            break

    color = ""
    if "spaceblack" in price_key.lower():
        color = " (Space Black)"
    elif "silver" in price_key.lower():
        color = " (Silver)"

    chip_part = f" {chip_label}" if chip_label else ""
    return _normalize_label(f"{size}{product_line}{chip_part}{color}")


def _filter_models_for_query(models: list[tuple[str, int]], product: str) -> list[tuple[str, int]]:
    """Keep models that match size/chip hints in the user query."""
    text = product.lower()
    size_match = re.search(r"\b(13|14|15|16)\s*(?:-?\s*inch|\"|\s+in)\b", text)
    if size_match is None:
        size_match = re.search(r"\b(13|14|15|16)\b", text)
    chip_match = re.search(r"\b(m[1-5](?:\s+pro|\s+max|pro|max)?)\b", text, re.I)

    filtered = models
    if size_match:
        size = size_match.group(1)
        filtered = [(name, price) for name, price in filtered if f"{size}-inch" in name.lower()]
    if chip_match:
        chip = chip_match.group(1).upper().replace("  ", " ")
        chip = re.sub(r"\b(M\d)PRO\b", r"\1 Pro", chip, flags=re.I)
        chip = re.sub(r"\b(M\d)MAX\b", r"\1 Max", chip, flags=re.I)
        filtered = [(name, price) for name, price in filtered if chip.lower() in name.lower()]
    return filtered or models


def extract_apple_shop_listings(
    html: str,
    *,
    url: str,
    product: str,
    region: str,
    source_label: str,
) -> list[PriceListing]:
    """Parse Apple shop HTML for JSON-LD and embedded pricing blocks."""
    if not html:
        return []

    line = resolve_apple_product_line(product)
    product_line = line[1] if line else "Product"
    models: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()

    for match in _APPLE_PRICE_KEY_RE.finditer(html):
        price_key = match.group(1)
        amount = float(match.group(2))
        if amount < _MIN_PRICE.get(region, 50):
            continue
        model = _model_from_price_key(price_key, product_line)
        key = (model, int(amount))
        if key in seen:
            continue
        seen.add(key)
        models.append(key)

    models = _filter_models_for_query(models, product)
    models.sort(key=lambda item: item[1])

    listings: list[PriceListing] = []
    if models:
        # Show distinct configs; cap to keep output readable.
        for model, amount in models[:8]:
            listings.append(
                PriceListing(
                    model=model,
                    price=_format_retail_price(amount, region=region),
                    source=source_label,
                    url=url,
                )
            )
        return listings

    # Fallback: JSON-LD AggregateOffer lowPrice on the product line page.
    for block in _JSON_LD_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "Product":
            continue
        offers = data.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list):
            continue
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            low = offer.get("lowPrice")
            if low is None:
                continue
            listings.append(
                PriceListing(
                    model=f"{product_line} (from)",
                    price=_format_retail_price(low, region=region),
                    source=source_label,
                    url=url,
                )
            )
        if listings:
            break

    return listings


def fetch_apple_shop_listings(product: str, *, region: str) -> list[PriceListing]:
    """Direct-fetch Apple shop pages for known product lines."""
    url = resolve_apple_shop_url(product, region=region)
    if not url:
        return []
    source_id = "apple_in" if region == "india" else "apple_us"
    label = _SOURCE_LABELS[source_id]
    if not check_url_reachable(url):
        return []
    html = fetch_page_html(url)
    return extract_apple_shop_listings(
        html,
        url=url,
        product=product,
        region=region,
        source_label=label,
    )


def is_excluded_retail_url(url: str) -> bool:
    """True when the URL path is a non-shop page (newsroom, support, etc.)."""
    if not url:
        return True
    if is_category_only_apple_url(url):
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


def extract_prices_from_content(
    text: str,
    *,
    region: str,
    category: PriceProductCategory | None = None,
) -> list[str]:
    """Extract normalized retail prices from scraped page text."""
    if not text:
        return []
    patterns = _INR_PRICE_PATTERNS if region == "india" else _USD_PRICE_PATTERNS
    fallback = _USD_PRICE_PATTERNS if region == "india" else _INR_PRICE_PATTERNS
    cat = category or "apple"
    min_value = _MIN_PRICE_BY_CATEGORY.get(cat, _MIN_PRICE).get(region, _MIN_PRICE.get(region, 50))

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
    category = detect_price_product_category(text)
    sources = sources_for_product(text, region=region)
    out: list[PriceSearchQuery] = []

    if category == "apple":
        out.append(PriceSearchQuery("combined", f"Retail ({region})", f"{text} price buy"))
        for sid, label, bias in sources:
            if sid.startswith("apple_"):
                out.append(
                    PriceSearchQuery(sid, label, f"{text} {bias.split()[0].replace('site:', '')} price")
                )
            else:
                site = bias.split()[0].replace("site:", "")
                out.append(PriceSearchQuery(sid, label, f"{text} price {site}"))
    else:
        for sid, label, bias in sources:
            site = bias.split()[0].replace("site:", "")
            if sid in ("amazon_in", "amazon_us"):
                out.append(PriceSearchQuery(sid, label, f"{text} price site:{site}"))
            elif sid == "flipkart":
                out.append(PriceSearchQuery(sid, label, f"{text} {site}"))
            else:
                out.append(PriceSearchQuery(sid, label, f"{text} price {site}"))

    return out


_RETAILER_TITLE_SUFFIX_RE = re.compile(
    r"(?i)\s+(?:[-–|]\s*|\s*:\s*)"
    r"(?:amazon(?:\s+india)?|flipkart|nykaa|croma|best\s+buy|"
    r"buy\s+online|online\s+shopping|price(?:\s+in\s+india)?|"
    r"free\s+delivery|prime)\b.*$"
)


def _slug_to_title(slug: str) -> str:
    text = re.sub(r"[^\w\s-]", " ", slug.replace("-", " "))
    return _normalize_label(text)


def _model_from_url(url: str) -> str | None:
    """Derive a readable product name from a retailer product URL slug."""
    if not url:
        return None
    parsed = urlparse(url)
    path = (parsed.path or "").strip("/")
    if not path:
        return None

    segments = path.split("/")
    product_slug = ""
    for idx, segment in enumerate(segments):
        lower = segment.lower()
        if lower in {"dp", "gp", "product", "p", "site"} or re.fullmatch(r"[A-Z0-9]{8,}", segment):
            if idx > 0:
                product_slug = segments[idx - 1]
            break

    if not product_slug:
        return None
    title = _slug_to_title(product_slug)
    return title if len(title) > 3 else None


def _model_from_title(title: str, product: str, *, url: str = "") -> str:
    cleaned = _RETAILER_TITLE_SUFFIX_RE.sub("", title or "").strip()
    cleaned = re.sub(r"(?i)\s+(?:price|buy|shop).*$", "", cleaned).strip()
    from_url = _model_from_url(url)

    if cleaned and len(cleaned) > 3:
        if from_url and len(from_url) > len(cleaned) + 8:
            return from_url[:120]
        return cleaned[:120]
    if from_url:
        return from_url[:120]
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


def _parse_formatted_price(price: str) -> int | None:
    """Extract integer value from a formatted retail price like ₹239,900."""
    match = re.search(r"[\d,]+(?:\.\d{2})?", price.replace(" ", ""))
    if match is None:
        return None
    return _price_to_int(match.group(0))


def _region_label(region: str) -> str:
    return "India" if region == "india" else "US"


def _format_price_range(amounts: list[int], *, region: str) -> str:
    if not amounts:
        return ""
    low, high = min(amounts), max(amounts)
    if low == high:
        return _format_retail_price(low, region=region)
    return f"{_format_retail_price(low, region=region)} – {_format_retail_price(high, region=region)}"


_CONFIG_NOTE = "Prices depend on chip, RAM, and storage configuration."
_GENERIC_CONFIG_NOTE = "Prices vary by brand and model."


def _retailer_browse_url(source_id: str, product: str, *, region: str) -> str | None:
    """Build a retailer search/browse URL for more options."""
    query = quote_plus(product.strip())
    if not query:
        return None
    if source_id == "amazon_in":
        return f"https://www.amazon.in/s?k={query}"
    if source_id == "amazon_us":
        return f"https://www.amazon.com/s?k={query}"
    if source_id == "flipkart":
        return f"https://www.flipkart.com/search?q={query}"
    if source_id == "nykaa":
        return f"https://www.nykaa.com/search/result/?q={query}"
    if source_id == "croma":
        return f"https://www.croma.com/search/?text={query}"
    if source_id == "bestbuy":
        return f"https://www.bestbuy.com/site/searchpage.jsp?st={query}"
    if source_id in ("apple_in", "apple_us"):
        return resolve_apple_shop_url(product, region=region)
    return None


def _source_id_for_label(label: str, *, region: str) -> str | None:
    for sid, src_label in list_price_sources(region):
        if src_label == label:
            return sid
    return None


def _dedupe_listings(listings: list[PriceListing]) -> list[PriceListing]:
    seen_keys: set[tuple[str, str, str]] = set()
    out: list[PriceListing] = []
    for listing in listings:
        model = _normalize_label(listing.model).lower()
        key = (model, listing.price, listing.url)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(
            PriceListing(
                model=_normalize_label(listing.model),
                price=listing.price,
                source=listing.source,
                url=listing.url,
            )
        )
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

    category = detect_price_product_category(product)
    searches = build_price_search_queries(product, region=region)
    if not searches:
        return [], []

    allowed_sources = {s[0] for s in sources_for_product(product, region=region)}
    max_results = 8 if deep else 5
    max_queries = len(searches) if deep else min(3, len(searches))

    listings: list[PriceListing] = []
    searched_labels: list[str] = []
    seen_labels: set[str] = set()
    seen_urls: set[str] = set()

    # 1. Direct Apple shop fetch for known Apple product lines only.
    apple_label = "Apple India" if region == "india" else "Apple US"
    apple_direct_urls: set[str] = set()
    if category == "apple":
        apple_listings = fetch_apple_shop_listings(product, region=region)
        if apple_listings:
            if apple_label not in seen_labels:
                searched_labels.append(apple_label)
                seen_labels.add(apple_label)
            for listing in apple_listings:
                apple_direct_urls.add(listing.url.rstrip("/"))
                if listing.url not in seen_urls:
                    seen_urls.add(listing.url)
                    listings.append(listing)

    # 2. Web search for marketplace retailers (and Apple fallback when applicable).
    for item in searches[:max_queries]:
        if item.label not in seen_labels:
            searched_labels.append(item.label)
            seen_labels.add(item.label)

        results = duckduckgo_search(item.query, max_results=max_results)
        for res in results:
            link = (res.get("link") or "").strip()
            if not link or link in seen_urls:
                continue

            if is_category_only_apple_url(link):
                continue

            retailer = retailer_for_url(link)
            if retailer is None or retailer[0] not in allowed_sources:
                continue

            seen_urls.add(link)
            if not check_url_reachable(link):
                continue

            title = res.get("title") or ""
            snippet = res.get("snippet") or ""
            _, label = retailer

            # Prefer structured Apple parsing when we land on a product-line page.
            if (
                category == "apple"
                and retailer[0] in ("apple_in", "apple_us")
                and resolve_apple_product_line(product)
                and link.rstrip("/") not in apple_direct_urls
            ):
                html = fetch_page_html(link)
                apple_from_search = extract_apple_shop_listings(
                    html,
                    url=link,
                    product=product,
                    region=region,
                    source_label=label,
                )
                if apple_from_search:
                    listings.extend(apple_from_search)
                    continue

            page = scrape_url(link)
            content = "\n".join(part for part in (title, snippet, page) if part)
            prices = extract_prices_from_content(content, region=region, category=category)
            if not prices:
                continue

            # Capture multiple prices from listing pages for range display.
            model = _model_from_title(title, product, url=link)
            for price in prices[:4]:
                listings.append(
                    PriceListing(
                        model=model,
                        price=price,
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
    category = detect_price_product_category(product)
    if not listings:
        default_labels = ", ".join(label for _, label in list_price_sources(region, product))
        searched = ", ".join(searched_labels) if searched_labels else default_labels
        return (
            f"No live prices found for {product} ({region}).\n"
            f"Searched: {searched}\n"
            f"Date retrieved: {today}\n"
            "Try a more specific model name or check retailer sites directly."
        )

    lines: list[str] = []
    region_name = _region_label(region)
    apple_line = resolve_apple_product_line(product)
    apple_shop_url = resolve_apple_shop_url(product, region=region)
    apple_source = "Apple India" if region == "india" else "Apple US"

    apple_listings: list[PriceListing] = []
    other_listings: list[PriceListing] = []
    for item in listings:
        url_match = (
            apple_shop_url is not None
            and item.url.rstrip("/") == apple_shop_url.rstrip("/")
        )
        if url_match or (apple_line is not None and item.source == apple_source):
            apple_listings.append(item)
        else:
            other_listings.append(item)

    if category != "apple":
        display_name = product.strip().title()
        all_amounts = [
            value
            for item in listings
            if (value := _parse_formatted_price(item.price)) is not None
        ]
        if all_amounts:
            lines.append(
                f" {display_name} ({region_name}): "
                f"{_format_price_range(all_amounts, region=region)}"
            )
            lines.append("")
            lines.append(f" {_GENERIC_CONFIG_NOTE}")
            lines.append("")

        by_source: dict[str, list[PriceListing]] = {}
        for item in other_listings or listings:
            by_source.setdefault(item.source, []).append(item)

        for source, items in by_source.items():
            amounts = [
                value
                for item in items
                if (value := _parse_formatted_price(item.price)) is not None
            ]
            price_text = (
                _format_price_range(amounts, region=region)
                if amounts
                else items[0].price
            )
            lines.append(f" • {source} — {price_text}")
            sid = _source_id_for_label(source, region=region)
            browse_url = _retailer_browse_url(sid, product, region=region) if sid else None
            if browse_url:
                lines.append(f"   {browse_url}")
            for item in items[:4]:
                lines.append(f"   • {item.model} — {item.price}")
                if item.url:
                    lines.append(f"     {item.url}")
            lines.append("")

        browse_labels = searched_labels or [
            label for _, label in list_price_sources(region, product)
        ]
        if browse_labels:
            lines.append(" Browse more options:")
            for label in browse_labels:
                sid = _source_id_for_label(label, region=region)
                if sid is None:
                    continue
                browse_url = _retailer_browse_url(sid, product, region=region)
                if browse_url:
                    lines.append(f" • {label}: {browse_url}")
            lines.append("")

        lines.append(f"Date retrieved: {today}")
        return "\n".join(lines)

    if apple_listings:
        display_name = apple_line[1] if apple_line else product.strip().title()
        amounts = [
            value
            for item in apple_listings
            if (value := _parse_formatted_price(item.price)) is not None
        ]
        if amounts:
            lines.append(
                f" {display_name} ({region_name}): "
                f"{_format_price_range(amounts, region=region)}"
            )
            lines.append("")
            if apple_line is not None:
                lines.append(f" {_CONFIG_NOTE}")
                lines.append("")
                if apple_shop_url:
                    lines.append(" Configure & see all options:")
                    lines.append(f" {apple_shop_url}")
                    lines.append("")
            if len(apple_listings) >= 2:
                lines.append(" Popular configurations:")
                for item in apple_listings[:5]:
                    lines.append(f" • {item.model} — {item.price}")
                    if item.url:
                        lines.append(f"   {item.url}")
                lines.append("")
        else:
            for item in apple_listings:
                lines.append(f" • {item.model} — {item.price} — {item.source}")
                lines.append(f"   {item.url}")
            lines.append("")

    if other_listings:
        if apple_listings:
            lines.append(" Also listed at other retailers:")
            lines.append("")
        for item in other_listings:
            lines.append(f" • {item.model} — {item.price} — {item.source}")
            lines.append(f"   {item.url}")
        lines.append("")

    if not apple_listings and not other_listings:
        for item in listings:
            lines.append(f" • {item.model} — {item.price} — {item.source}")
            lines.append(f"   {item.url}")
        lines.append("")

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
