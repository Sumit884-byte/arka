"""Stock photo search — Unsplash, Pexels, Pixabay, Openverse, web with unified fallback."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from arka.media.unsplash import UnsplashPhoto, access_key as unsplash_key, download_photo as unsplash_download
from arka.media.unsplash import search_photos as unsplash_search
from arka.media.unsplash import setup_hint as unsplash_setup_hint
from arka.media.unsplash import trigger_download as unsplash_trigger


_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "in",
        "on",
        "for",
        "with",
        "to",
        "at",
        "by",
        "from",
        "into",
        "about",
        "over",
        "under",
        "via",
        "what",
        "when",
        "where",
        "which",
        "that",
        "this",
        "your",
        "their",
        "have",
        "has",
        "will",
        "should",
        "would",
        "could",
        "also",
        "more",
        "most",
        "very",
        "make",
        "made",
        "buy",
        "best",
        "good",
        "better",
        "versus",
        "vs",
        "tech",
        "technology",
        "decision",
        "making",
        "ultimate",
        "showdown",
        "advantages",
        "advantage",
        "power",
        "value",
        "upgrade",
        "upgrades",
        "upgrading",
        "components",
        "component",
        "setup",
        "things",
        "thing",
        "using",
        "used",
        "use",
        "need",
        "needs",
        "help",
        "video",
        "guide",
        "tips",
        "overview",
        "introduction",
        "explainer",
    }
)

_VISUAL_NOUNS = frozenset(
    {
        "desktop",
        "laptop",
        "computer",
        "monitor",
        "keyboard",
        "office",
        "workspace",
        "gaming",
        "server",
        "cloud",
        "data",
        "network",
        "robot",
        "factory",
        "city",
        "phone",
        "tablet",
        "chip",
        "circuit",
        "brain",
        "chart",
        "graph",
        "code",
        "developer",
        "programmer",
        "tower",
        "pc",
        "macbook",
        "notebook",
        "hardware",
        "software",
        "coding",
        "screen",
        "display",
    }
)

_SCENIC_TERMS = frozenset(
    {
        "sunset",
        "sunrise",
        "mountain",
        "mountains",
        "beach",
        "ocean",
        "sea",
        "forest",
        "landscape",
        "nature",
        "flower",
        "flowers",
        "sky",
        "lake",
        "river",
        "waterfall",
        "scenic",
        "wilderness",
        "meadow",
        "valley",
        "coast",
        "island",
        "tropical",
        "snow",
        "wildlife",
        "bird",
        "tree",
        "trees",
        "garden",
        "field",
        "horizon",
        "clouds",
        "aerial",
        "countryside",
        "park",
        "trail",
        "hiking",
        "sunlight",
        "golden hour",
    }
)

_TECH_TERMS = frozenset(
    {
        "computer",
        "laptop",
        "desktop",
        "monitor",
        "keyboard",
        "office",
        "desk",
        "workspace",
        "code",
        "coding",
        "developer",
        "programmer",
        "server",
        "data",
        "network",
        "hardware",
        "software",
        "screen",
        "display",
        "pc",
        "macbook",
        "notebook",
        "tablet",
        "phone",
        "chip",
        "circuit",
        "robot",
        "factory",
        "business",
        "meeting",
        "work",
    }
)

_IRRELEVANT_TERMS = frozenset(
    {
        "child",
        "children",
        "kid",
        "kids",
        "baby",
        "toddler",
        "wedding",
        "birthday",
        "party",
        "graduation",
        "portrait",
        "selfie",
        "food",
        "recipe",
        "pet",
        "dog",
        "cat",
    }
)

_QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "desktop": (
        "desktop monitor office",
        "gaming pc setup desk",
        "computer tower workspace",
        "dual monitor desk",
        "PC hardware motherboard",
    ),
    "laptop": (
        "macbook desk coffee",
        "laptop office portable",
        "thinkpad workspace",
        "notebook computer cafe",
        "dell laptop desk",
    ),
    "computer": (
        "computer desk office",
        "desktop workstation monitor",
        "laptop keyboard typing",
        "programmer coding screen",
        "office computer setup",
    ),
    "choice": (
        "shopping electronics store",
        "comparing laptops store",
        "tech retail display",
    ),
    "buy": (
        "electronics store shopping",
        "computer shop display",
        "retail tech products",
    ),
    "gaming": (
        "gaming desk setup",
        "gaming pc rgb monitor",
        "mechanical keyboard desk",
    ),
    "performance": (
        "cpu chip hardware",
        "server rack datacenter",
        "computer benchmark screen",
    ),
    "portable": (
        "laptop coffee shop",
        "remote work laptop",
        "notebook travel desk",
    ),
    "office": (
        "office desk computer",
        "workspace monitor keyboard",
        "business laptop meeting",
    ),
    "software": (
        "code screen developer",
        "programming laptop screen",
        "software dashboard monitor",
    ),
    "upgrade": (
        "computer hardware upgrade",
        "PC components desk",
        "installing RAM motherboard",
    ),
    "monitor": (
        "dual monitor desk",
        "ultrawide monitor office",
        "computer screen workspace",
    ),
    "keyboard": (
        "mechanical keyboard desk",
        "typing laptop office",
    ),
    "work": (
        "remote work laptop",
        "home office desk",
        "coworking laptop",
    ),
    "travel": (
        "laptop airport travel",
        "portable notebook cafe",
    ),
}


@dataclass(frozen=True)
class StockPhoto:
    id: str
    url: str
    download_url: str
    photographer: str
    photographer_url: str
    description: str
    source: str
    title: str = ""
    alt_text: str = ""
    tags: tuple[str, ...] = ()
    category: str = ""
    width: int = 0
    height: int = 0


def _split_tags(raw: object) -> tuple[str, ...]:
    if isinstance(raw, list):
        names: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("title") or "").strip().lower()
                if name and name not in {"none", "null"}:
                    names.append(name)
            else:
                text = str(item).strip().lower()
                if text and not text.startswith("{"):
                    names.append(text)
        return tuple(dict.fromkeys(names))
    if isinstance(raw, str):
        parts = re.split(r"[,;|/]+", raw)
        return tuple(dict.fromkeys(part.strip().lower() for part in parts if part.strip()))
    return ()


def _make_stock_photo(
    *,
    id: str,
    url: str,
    download_url: str,
    photographer: str,
    photographer_url: str,
    description: str,
    source: str,
    title: str = "",
    alt_text: str = "",
    tags: object = (),
    category: str = "",
    width: int = 0,
    height: int = 0,
) -> StockPhoto:
    tag_tuple = _split_tags(tags)
    desc = (description or alt_text or title or " ".join(tag_tuple)).strip()
    return StockPhoto(
        id=id,
        url=url,
        download_url=download_url,
        photographer=photographer,
        photographer_url=photographer_url,
        description=desc,
        source=source,
        title=title.strip(),
        alt_text=alt_text.strip(),
        tags=tag_tuple,
        category=category.strip(),
        width=int(width or 0),
        height=int(height or 0),
    )


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def pexels_key() -> str:
    for name in ("PEXELS_API_KEY", "PEXELS_KEY"):
        val = _env(name)
        if val:
            return val
    return ""


def pixabay_key() -> str:
    for name in ("PIXABAY_API_KEY", "PIXABAY_KEY"):
        val = _env(name)
        if val:
            return val
    return ""


def configured_sources() -> list[str]:
    raw = _env("VIDEO_PHOTO_SOURCES", "unsplash,pexels,pixabay,openverse,web")
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def compact_photo_query(query: str, *, max_words: int = 3) -> str:
    """Reduce NL/LLM phrases to short stock-photo search terms."""
    text = re.sub(r"[^\w\s'-]", " ", (query or "").strip())
    words = [w for w in re.findall(r"[A-Za-z']+", text) if w]
    if not words:
        return "technology"
    if len(words) <= max_words:
        cleaned = [w.lower() for w in words if w.lower() not in _QUERY_STOPWORDS]
        if cleaned:
            return " ".join(cleaned[:max_words])

    scored: list[tuple[int, str]] = []
    for word in words:
        lw = word.lower()
        if len(lw) < 3 or lw in _QUERY_STOPWORDS:
            continue
        score = len(lw) + (3 if lw in _VISUAL_NOUNS else 0)
        scored.append((score, lw))
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked = [word for _, word in scored[:max_words]]
    if not picked:
        picked = [w.lower() for w in words[:max_words] if w.lower() not in _QUERY_STOPWORDS]
    if not picked:
        return "technology"
    return " ".join(picked)


def stock_search_query(query: str) -> str:
    """Bias searches toward subject photos, not generic scenic art."""
    compact = compact_photo_query(query)
    words = compact.split()
    if compact == "technology":
        return "computer desk office"
    if len(words) >= 2 and not (set(words) & {"office", "desk", "workspace", "studio", "indoor"}):
        return f"{compact} office"
    if words and words[0] in _VISUAL_NOUNS and "office" not in compact:
        return f"{compact} desk"
    return compact


def photo_query_variants(query: str) -> list[str]:
    base = stock_search_query(query)
    words = base.split()
    variants = [base, compact_photo_query(query)]
    variants.extend(diverse_photo_queries(query, limit=6))
    if len(words) >= 2:
        variants.append(" ".join(words[:2]))
    if words:
        variants.append(words[0])
    out: list[str] = []
    seen: set[str] = set()
    for item in variants:
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def diverse_photo_queries(query: str, *, limit: int = 8) -> list[str]:
    """Expand a topic keyword into varied stock-photo searches for B-roll diversity."""
    base = stock_search_query(query)
    expanded: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        normalized = stock_search_query(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            expanded.append(normalized)

    add(base)
    for word in re.findall(r"[a-z']+", f"{query} {base}".lower()):
        if word in _QUERY_STOPWORDS or len(word) < 3:
            continue
        for variant in _QUERY_EXPANSIONS.get(word, ()):
            add(variant)
        if len(expanded) >= limit:
            break
    return expanded[:limit] or [base]


def _query_terms(query: str, *, context_terms: list[str] | None = None) -> set[str]:
    terms: set[str] = set()
    chunks = [query, compact_photo_query(query), stock_search_query(query)]
    if context_terms:
        chunks.extend(context_terms)
    for chunk in chunks:
        for word in re.findall(r"[a-z']+", str(chunk).lower()):
            if len(word) >= 3 and word not in _QUERY_STOPWORDS:
                terms.add(word)
    return terms


def photo_metadata_text(photo: StockPhoto) -> str:
    chunks = [photo.description, photo.title, photo.alt_text, photo.category, " ".join(photo.tags)]
    return " ".join(chunk for chunk in chunks if chunk).lower()


def photo_metadata_terms(photo: StockPhoto) -> set[str]:
    terms: set[str] = set()
    for chunk in (photo.description, photo.title, photo.alt_text, photo.category, *photo.tags):
        for word in re.findall(r"[a-z']+", str(chunk).lower()):
            if len(word) >= 3 and word not in _QUERY_STOPWORDS:
                terms.add(word)
    return terms


def _photo_text(photo: StockPhoto) -> str:
    return photo_metadata_text(photo)


def score_photo_relevance(
    photo: StockPhoto,
    query: str,
    *,
    context_terms: list[str] | None = None,
) -> int:
    terms = _query_terms(query, context_terms=context_terms)
    text = photo_metadata_text(photo)
    meta_terms = photo_metadata_terms(photo)
    if not text and not meta_terms:
        return 0

    score = 0
    for term in terms:
        if term in photo.tags:
            score += 22
        elif any(term in tag.split() for tag in photo.tags):
            score += 16
        if term in photo.title.lower():
            score += 14
        if term in photo.alt_text.lower():
            score += 12
        if re.search(rf"\b{re.escape(term)}\b", text):
            score += 10
        elif term in text:
            score += 6
        if term in meta_terms:
            score += 8

    overlap = len(terms & meta_terms)
    if overlap >= 2:
        score += overlap * 6

    category = photo.category.lower()
    if category and any(term in category for term in terms):
        score += 12

    scenic_hits = sum(1 for term in _SCENIC_TERMS if term in text or term in photo.tags)
    tech_hits = sum(1 for term in _TECH_TERMS if term in text or term in photo.tags)

    specific_query = bool(terms & _VISUAL_NOUNS) or bool(terms & _TECH_TERMS) or len(terms) >= 2
    if specific_query:
        score -= scenic_hits * 10
        score += tech_hits * 5
    elif terms == {"technology"} or not terms:
        score -= scenic_hits * 8
        score += tech_hits * 5

    if terms & (_TECH_TERMS | _VISUAL_NOUNS):
        bad_hits = sum(1 for term in _IRRELEVANT_TERMS if term in text or term in photo.tags)
        score -= bad_hits * 18

    return score


def _photo_debug_hint(photo: StockPhoto, query: str, *, context_terms: list[str] | None = None) -> str:
    score = score_photo_relevance(photo, query, context_terms=context_terms)
    bits: list[str] = [f"score={score}"]
    if photo.tags:
        bits.append(f"tags={','.join(photo.tags[:4])}")
    if photo.title:
        bits.append(f"title={photo.title[:40]}")
    if photo.category:
        bits.append(f"category={photo.category[:24]}")
    return " ".join(bits)


def rank_photos(
    photos: list[StockPhoto],
    query: str,
    *,
    context_terms: list[str] | None = None,
) -> list[StockPhoto]:
    if not photos:
        return []
    ranked = sorted(
        photos,
        key=lambda photo: score_photo_relevance(photo, query, context_terms=context_terms),
        reverse=True,
    )
    best = score_photo_relevance(ranked[0], query, context_terms=context_terms)
    if best <= 0:
        return ranked
    threshold = max(1, best - 8)
    good = [
        photo
        for photo in ranked
        if score_photo_relevance(photo, query, context_terms=context_terms) >= threshold
    ]
    return good or ranked


def photos_are_relevant(
    photos: list[StockPhoto],
    query: str,
    *,
    min_score: int = 1,
    context_terms: list[str] | None = None,
) -> bool:
    if not photos:
        return False
    ranked = rank_photos(photos, query, context_terms=context_terms)
    return score_photo_relevance(ranked[0], query, context_terms=context_terms) >= min_score


def any_source_available() -> bool:
    for source in configured_sources():
        if source in {"openverse", "web"}:
            return True
        if source == "unsplash" and unsplash_key():
            return True
        if source == "pexels" and pexels_key():
            return True
        if source == "pixabay" and pixabay_key():
            return True
    return False


def setup_hint(context: str = "compose_video") -> str:
    return (
        f"Stock photo API key required for {context}.\n"
        "Configure at least one in ~/.config/arka/.env:\n"
        "  UNSPLASH_ACCESS_KEY=...   https://unsplash.com/developers\n"
        "  PEXELS_API_KEY=...        https://www.pexels.com/api/\n"
        "  PIXABAY_API_KEY=...       https://pixabay.com/api/docs/\n"
        "Openverse and web image search need no key (always tried as fallback).\n"
        "Optional: VIDEO_PHOTO_SOURCES=unsplash,pexels,pixabay,openverse,web"
    )


def _from_unsplash(photo: UnsplashPhoto) -> StockPhoto:
    return _make_stock_photo(
        id=photo.id,
        url=photo.url,
        download_url=photo.download_url,
        photographer=photo.photographer,
        photographer_url=photo.photographer_url,
        description=photo.description,
        source="unsplash",
        alt_text=photo.alt_description,
        tags=photo.tags,
    )


def _search_pexels(query: str, *, count: int, orientation: str) -> list[StockPhoto]:
    key = pexels_key()
    if not key:
        return []
    params = urllib.parse.urlencode(
        {
            "query": query.strip() or "technology",
            "per_page": max(1, min(count, 30)),
            "orientation": orientation if orientation in {"landscape", "portrait", "square"} else "landscape",
        }
    )
    req = urllib.request.Request(
        f"https://api.pexels.com/v1/search?{params}",
        headers={"Authorization": key, "User-Agent": "arka-compose-video/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    out: list[StockPhoto] = []
    for row in payload.get("photos") or []:
        src = row.get("src") or {}
        url = src.get("large2x") or src.get("large") or src.get("original") or ""
        if not url:
            continue
        out.append(
            _make_stock_photo(
                id=str(row.get("id") or ""),
                url=url,
                download_url=url,
                photographer=str((row.get("photographer") or "Unknown")),
                photographer_url=str(row.get("photographer_url") or "https://www.pexels.com"),
                description=str(row.get("alt") or query),
                source="pexels",
                title=str(row.get("alt") or ""),
                alt_text=str(row.get("alt") or ""),
                width=int(row.get("width") or 0),
                height=int(row.get("height") or 0),
            )
        )
    return out


def _search_pixabay(query: str, *, count: int, orientation: str) -> list[StockPhoto]:
    key = pixabay_key()
    if not key:
        return []
    params = urllib.parse.urlencode(
        {
            "key": key,
            "q": query.strip() or "technology",
            "image_type": "photo",
            "orientation": "horizontal" if orientation != "portrait" else "vertical",
            "per_page": max(3, min(count, 30)),
            "safesearch": "true",
        }
    )
    req = urllib.request.Request(
        f"https://pixabay.com/api/?{params}",
        headers={"User-Agent": "arka-compose-video/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    out: list[StockPhoto] = []
    for row in payload.get("hits") or []:
        url = str(row.get("largeImageURL") or row.get("webformatURL") or "")
        if not url:
            continue
        out.append(
            _make_stock_photo(
                id=str(row.get("id") or ""),
                url=url,
                download_url=url,
                photographer=str(row.get("user") or "Pixabay"),
                photographer_url=str(row.get("pageURL") or "https://pixabay.com"),
                description=str(row.get("tags") or query),
                source="pixabay",
                title=str(row.get("tags") or ""),
                tags=row.get("tags") or "",
                category=str(row.get("type") or "photo"),
                width=int(row.get("imageWidth") or 0),
                height=int(row.get("imageHeight") or 0),
            )
        )
    return out


def _search_openverse(query: str, *, count: int, orientation: str) -> list[StockPhoto]:
    params = urllib.parse.urlencode(
        {
            "q": query.strip() or "technology",
            "page_size": max(1, min(count, 20)),
            "license_type": "commercial,modification",
        }
    )
    req = urllib.request.Request(
        f"https://api.openverse.org/v1/images/?{params}",
        headers={"User-Agent": "arka-compose-video/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    out: list[StockPhoto] = []
    for row in payload.get("results") or []:
        url = str(row.get("url") or row.get("thumbnail") or "")
        if not url:
            continue
        if orientation == "portrait" and (row.get("height") or 0) < (row.get("width") or 1):
            continue
        if orientation == "landscape" and (row.get("width") or 0) < (row.get("height") or 1):
            continue
        out.append(
            _make_stock_photo(
                id=str(row.get("id") or row.get("identifier") or url),
                url=url,
                download_url=url,
                photographer=str(row.get("creator") or row.get("source") or "Openverse"),
                photographer_url=str(row.get("foreign_landing_url") or "https://openverse.org"),
                description=str(row.get("title") or query),
                source="openverse",
                title=str(row.get("title") or ""),
                alt_text=str(row.get("title") or ""),
                tags=row.get("tags") or [],
                category=str(row.get("category") or ""),
                width=int(row.get("width") or 0),
                height=int(row.get("height") or 0),
            )
        )
        if len(out) >= count:
            break
    return out


def _search_web_images(query: str, *, count: int, orientation: str) -> list[StockPhoto]:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore
    except ImportError:
        return []

    compact = stock_search_query(query)
    out: list[StockPhoto] = []
    try:
        with DDGS() as client:
            rows = client.images(
                compact,
                max_results=max(8, min(count, 24)),
                safesearch="moderate",
            )
            for row in rows or []:
                url = str(row.get("image") or row.get("thumbnail") or "")
                if not url:
                    continue
                width = int(row.get("width") or 0)
                height = int(row.get("height") or 0)
                if orientation == "portrait" and width and height and width > height:
                    continue
                if orientation == "landscape" and width and height and height > width:
                    continue
                out.append(
                    _make_stock_photo(
                        id=url,
                        url=url,
                        download_url=url,
                        photographer=str(row.get("source") or "web"),
                        photographer_url=str(row.get("url") or "https://duckduckgo.com"),
                        description=str(row.get("title") or compact),
                        source="web",
                        title=str(row.get("title") or ""),
                        alt_text=str(row.get("title") or ""),
                        category=str(row.get("source") or "web"),
                        width=width,
                        height=height,
                    )
                )
                if len(out) >= count:
                    break
    except Exception as exc:
        raise RuntimeError(f"web image search failed: {exc}") from exc
    return out


def _search_source(
    source: str,
    query: str,
    *,
    count: int,
    orientation: str,
) -> list[StockPhoto]:
    if source == "unsplash" and unsplash_key():
        return [_from_unsplash(p) for p in unsplash_search(query, count=count, orientation=orientation)]
    if source == "pexels" and pexels_key():
        return _search_pexels(query, count=count, orientation=orientation)
    if source == "pixabay" and pixabay_key():
        return _search_pixabay(query, count=count, orientation=orientation)
    if source == "openverse":
        return _search_openverse(query, count=count, orientation=orientation)
    if source == "web":
        return _search_web_images(query, count=count, orientation=orientation)
    return []


def search_stock_photos(
    query: str,
    *,
    count: int = 1,
    orientation: str = "landscape",
    context_terms: list[str] | None = None,
    exclude_ids: set[str] | None = None,
) -> list[StockPhoto]:
    errors: list[str] = []
    variants = photo_query_variants(query)
    fetch_count = max(count * 5, 20)
    context = [term for term in (context_terms or []) if term.strip()]
    excluded = exclude_ids or set()
    for variant in variants:
        search_q = stock_search_query(variant)
        for source in configured_sources():
            try:
                photos = _search_source(source, search_q, count=fetch_count, orientation=orientation)
                if not photos:
                    continue
                ranked = rank_photos(photos, variant, context_terms=context)
                if excluded:
                    fresh = [photo for photo in ranked if photo_uid(photo) not in excluded]
                    if not fresh:
                        continue
                    ranked = fresh
                if not photos_are_relevant(ranked, variant, context_terms=context):
                    print(
                        f"  Photo source {source}: metadata mismatch for {search_q!r}, trying next …",
                        file=sys.stderr,
                    )
                    continue
                picked = ranked[:count]
                hint = _photo_debug_hint(picked[0], variant, context_terms=context)
                print(f"  Photos: {source} ({search_q!r}) — {hint}", file=sys.stderr)
                return picked
            except Exception as exc:
                msg = str(exc)
                if source == "unsplash" and "403" in msg:
                    msg = "Unsplash HTTP 403 — check UNSPLASH_ACCESS_KEY or use openverse/web fallback"
                errors.append(f"{source}: {msg}")
                print(f"  Photo source {source} failed: {msg}", file=sys.stderr)
    if not any_source_available():
        raise SystemExit(setup_hint())
    detail = "; ".join(errors[-4:]) if errors else "no results"
    raise SystemExit(f"No stock photos found for {query!r} (tried {variants!r}; {detail})")


def photo_uid(photo: StockPhoto) -> str:
    return f"{photo.source}:{photo.id}"


def download_stock_photo(photo: StockPhoto, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if photo.source == "unsplash":
        unsplash = UnsplashPhoto(
            id=photo.id,
            url=photo.url,
            download_url=photo.download_url,
            photographer=photo.photographer,
            photographer_url=photo.photographer_url,
            description=photo.description,
        )
        unsplash_trigger(unsplash)
        return unsplash_download(unsplash, dest)
    req = urllib.request.Request(photo.url, headers={"User-Agent": "arka-compose-video/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())
    return dest
