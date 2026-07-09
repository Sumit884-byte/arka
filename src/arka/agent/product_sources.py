"""Authoritative source targets for product and ingredient research."""

from __future__ import annotations

import re
from dataclasses import dataclass

# (id, label, site bias fragment)
COSMETIC_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("incidecoder", "INCIDecoder", "site:incidecoder.com"),
    ("ewg", "EWG Skin Deep", "site:ewg.org"),
    ("paulaschoice", "Paula's Choice Ingredient Dictionary", "site:paulaschoice.com"),
    ("cosing", "EU CosIng Database", "site:ec.europa.eu/growth/tools-databases/cosing"),
)

FOOD_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("usda", "USDA FoodData Central", "site:fdc.nal.usda.gov"),
    ("openfoodfacts", "Open Food Facts", "site:openfoodfacts.org"),
    ("fda_food", "FDA Food Labeling", "site:fda.gov/food"),
)

SUPPLEMENT_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("usda", "USDA FoodData Central", "site:fdc.nal.usda.gov"),
    ("openfoodfacts", "Open Food Facts", "site:openfoodfacts.org"),
    ("fda_supplement", "FDA Dietary Supplements", "site:fda.gov/food/dietary-supplements"),
)

GENERAL_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("pubmed", "PubMed", "site:pubmed.ncbi.nlm.nih.gov"),
)

_CATEGORY_SOURCES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "cosmetics": COSMETIC_SOURCES,
    "food": FOOD_SOURCES,
    "supplement": SUPPLEMENT_SOURCES,
}

_COSMETIC_RE = re.compile(
    r"(?i)\b(sunscreen|shampoo|skincare|moisturiz|serum|lotion|cleanser|cosmetic|"
    r"paraben|niacinamide|retinol|spf|conditioner|face wash|toner|exfoliant|"
    r"makeup|lipstick|foundation|inci|dermatolog|sensitive skin|cruelty.free|"
    r"fragrance.free|hyaluronic|salicylic|benzoyl|sunscreen|moisturizer)\b"
)
_FOOD_RE = re.compile(
    r"(?i)\b(food|snack|cereal|calories|nutrition label|protein bar|chips|"
    r"beverage|drink|juice|soda|yogurt|bread|pasta sauce|frozen meal|"
    r"open food facts|fdc|usda food)\b"
)
_SUPPLEMENT_RE = re.compile(
    r"(?i)\b(supplement|vitamin|mineral|probiotic|capsule|tablet|multivitamin|"
    r"omega.3|fish oil|collagen powder|preworkout|amino acid|dietary supplement)\b"
)


@dataclass(frozen=True)
class ProductSearchQuery:
    source_id: str
    label: str
    query: str


def detect_product_category(query: str) -> str:
    """Classify query as cosmetics, food, or supplement."""
    cosmetic = bool(_COSMETIC_RE.search(query))
    food = bool(_FOOD_RE.search(query))
    supplement = bool(_SUPPLEMENT_RE.search(query))
    if supplement and not cosmetic:
        return "supplement"
    if food and not cosmetic:
        return "food"
    if cosmetic:
        return "cosmetics"
    if supplement:
        return "supplement"
    if food:
        return "food"
    return "cosmetics"


def sources_for_category(category: str) -> list[tuple[str, str, str]]:
    """Return authoritative sources for a category, plus general safety sources."""
    primary = list(_CATEGORY_SOURCES.get(category, COSMETIC_SOURCES))
    seen = {s[0] for s in primary}
    for src in GENERAL_SOURCES:
        if src[0] not in seen:
            primary.append(src)
            seen.add(src[0])
    return primary


def list_product_sources(category: str | None = None) -> list[tuple[str, str]]:
    """Return (source_id, label) for a product research category."""
    cat = category or "cosmetics"
    return [(s[0], s[1]) for s in sources_for_category(cat)]


def build_product_search_queries(query: str) -> list[ProductSearchQuery]:
    """Build targeted search queries for authoritative product/ingredient sources."""
    text = query.strip()
    if not text:
        return []
    category = detect_product_category(text)
    sources = sources_for_category(category)
    out: list[ProductSearchQuery] = []

    site_bias = " OR ".join(s[2] for s in sources)
    out.append(ProductSearchQuery("combined", "Authoritative sources", f"{site_bias} {text}"))

    for sid, label, bias in sources[:3]:
        out.append(ProductSearchQuery(sid, label, f"{bias} {text}"))

    out.append(
        ProductSearchQuery("brand", "Brand ingredient list", f"{text} official ingredient list INCI")
    )
    return out


def fetch_product_web_context(query: str, *, deep: bool) -> tuple[str, list[str]]:
    """Scrape authoritative product sources; return (context, labels consulted)."""
    try:
        from arka.agent.chat import scrape_search_results, snippet_lookup
    except ImportError:
        return "", []

    searches = build_product_search_queries(query)
    if not searches:
        return "", []

    min_words = 700 if deep else 400
    pages_per_query = 6 if deep else 4
    max_queries = 4 if deep else 2

    parts: list[str] = []
    labels: list[str] = []
    seen_labels: set[str] = set()

    snip = snippet_lookup(searches[0].query)
    if snip:
        parts.append(snip)

    for item in searches[:max_queries]:
        web = scrape_search_results(item.query, min_words=min_words // max_queries, hard_limit=pages_per_query)
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
