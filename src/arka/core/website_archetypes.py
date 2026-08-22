"""Cached blueprints for common website/app types — instant sitemap without LLM."""

from __future__ import annotations

import os
import re
from typing import Any

_BUILD_VERB_RE = re.compile(
    r"(?i)\b(?:build|create|make|design|scaffold|plan|start|launch)\b"
)
_SHORT_PROMPT_WORDS = 8


def _enabled() -> bool:
    return os.environ.get("WEBSITE_ARCHETYPE_CACHE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


ARCHETYPES: list[dict[str, Any]] = [
    {
        "id": "recipe_app",
        "title": "Recipe app",
        "site_type": "app",
        "aliases": [
            "recipe app",
            "recipes app",
            "recipe website",
            "cooking app",
            "meal planner",
            "recipe book",
            "food recipe",
            "recipe platform",
        ],
        "templates": ["landing", "dashboard", "data-table", "form"],
        "plan": """## Assumptions
- Web app for discovering, saving, and cooking recipes
- Audience: home cooks; mobile-friendly UI

## Sitemap
| URL | Type | Job | Nav |
|-----|------|-----|-----|
| / | Home | Browse featured recipes + search | Primary |
| /recipes | Hub | Filterable recipe catalog | Primary |
| /recipes/:slug | Detail | Ingredients, steps, cook mode | — |
| /collections | Hub | Saved lists / meal plans | Primary |
| /collections/:id | Detail | Curated recipe set | — |
| /create | Form | Add or import a recipe | Primary |
| /profile | Settings | Account, dietary prefs, saved items | Account |
| /about | Marketing | Brand story + contact | Footer |

## Page outlines
**/** — Hero search, trending recipes, category chips (breakfast, vegan, 30-min), CTA to sign up.

**/recipes** — Grid/list toggle, filters (diet, time, cuisine), sort, pagination.

**/recipes/:slug** — Hero image, servings scaler, ingredient checklist, numbered steps, timer hooks, save button.

**/collections** — User meal plans and favorites; empty state with CTA to browse.

**/create** — Multi-step form: basics → ingredients → steps → photo; preview before publish.

## Split/merge notes
- Keep blog/how-to content off recipe detail URLs (link to /guides hub if needed later).
- Do not combine catalog filters with account settings.

## Next steps
1. Approve sitemap → scaffold `landing` + `data-table` templates
2. Wire `/recipes` list and `/recipes/:slug` detail routes
3. Add auth later on `/profile` and `/create`""",
    },
    {
        "id": "food_restaurant",
        "title": "Food / restaurant website",
        "site_type": "marketing",
        "aliases": [
            "food website",
            "restaurant website",
            "restaurant site",
            "cafe website",
            "menu website",
            "food business site",
            "bakery website",
        ],
        "templates": ["landing", "data-table", "form"],
        "plan": """## Assumptions
- Restaurant or food brand marketing site with menu and reservations
- Primary conversion: visit, order, or book a table

## Sitemap
| URL | Type | Job | Nav |
|-----|------|-----|-----|
| / | Home | Brand impression + route to menu/order | Primary |
| /menu | Hub | Full menu by category | Primary |
| /menu/:item | Detail | Dish photo, allergens, price (optional) | — |
| /order | App link | Online ordering or delivery CTA | Primary |
| /reservations | Form | Table booking | Primary |
| /about | Story | Chef, sourcing, hours | Primary |
| /location | Info | Map, hours, parking | Footer |
| /contact | Form | Catering inquiries | Footer |

## Page outlines
**/** — Hero dish photography, hours strip, “View menu” + “Book a table” CTAs, social proof.

**/menu** — Categories (starters, mains, desserts, drinks); dietary tags; prices.

**/reservations** — Date, time, party size, contact fields; confirmation message pattern.

## Next steps
1. Scaffold `landing` for home and `form` for reservations
2. Build menu as static JSON or CMS-backed `/menu` hub
3. Add `/order` outbound link or embed when ready""",
    },
    {
        "id": "saas",
        "title": "SaaS marketing site",
        "site_type": "saas",
        "aliases": [
            "saas website",
            "saas site",
            "b2b saas",
            "devtools website",
            "startup landing",
            "software product site",
        ],
        "templates": ["landing", "dashboard", "form", "login"],
        "plan": """## Assumptions
- B2B SaaS with self-serve signup and docs linked from marketing

## Sitemap
| URL | Type | Job | Nav |
|-----|------|-----|-----|
| / | Home | Value prop + demo CTA | Primary |
| /features | Marketing | Capability breakdown | Primary |
| /pricing | Conversion | Plans + FAQ | Primary |
| /docs | Hub | Documentation entry | Primary |
| /blog | Hub | SEO + product updates | Secondary |
| /login | Auth | Sign in | Utility |
| /signup | Auth | Registration | CTA |
| /legal/privacy | Legal | Privacy policy | Footer |

## Next steps
1. Scaffold `landing` + `login`
2. Split tutorials (docs) from reference (API) under `/docs`
3. Keep primary nav ≤7 items""",
    },
    {
        "id": "docs",
        "title": "Documentation site",
        "site_type": "docs",
        "aliases": [
            "docs site",
            "documentation site",
            "api docs",
            "developer docs",
            "knowledge base",
            "help center",
        ],
        "templates": ["landing", "dashboard", "empty-state"],
        "plan": """## Assumptions
- Product documentation with guides + reference split

## Sitemap
| URL | Type | Job | Nav |
|-----|------|-----|-----|
| /docs | Hub | Doc home + search | Primary |
| /docs/guides | Hub | Tutorials and how-tos | Sidebar |
| /docs/guides/:slug | Guide | Step-by-step task | — |
| /docs/reference | Hub | API / CLI reference | Sidebar |
| /docs/reference/:slug | Reference | Field-level detail | — |
| /changelog | List | Release notes | Footer |

## Split/merge notes
- Never mix tutorial prose with reference tables on one URL.

## Next steps
1. Hub + detail pattern for guides and reference
2. Add search and version selector on `/docs`""",
    },
    {
        "id": "portfolio",
        "title": "Portfolio site",
        "site_type": "portfolio",
        "aliases": [
            "portfolio website",
            "portfolio site",
            "personal website",
            "freelancer site",
            "designer portfolio",
            "developer portfolio",
        ],
        "templates": ["landing", "data-table"],
        "plan": """## Sitemap
| URL | Type | Job | Nav |
|-----|------|-----|-----|
| / | Home | Intro + featured work | Primary |
| /work | Hub | Project grid | Primary |
| /work/:slug | Case study | Problem, role, outcome | — |
| /about | Bio | Story + skills | Primary |
| /contact | Form | Hire / collaborate | Primary |

## Next steps
1. Scaffold `landing`; use project cards on `/work`
2. One case study page per flagship project""",
    },
    {
        "id": "ecommerce",
        "title": "E-commerce shop",
        "site_type": "shop",
        "aliases": [
            "ecommerce",
            "e-commerce",
            "online shop",
            "online store",
            "shop website",
            "store website",
        ],
        "templates": ["landing", "data-table", "form", "dashboard"],
        "plan": """## Sitemap
| URL | Type | Job | Nav |
|-----|------|-----|-----|
| / | Home | Featured products + categories | Primary |
| /shop | Hub | Catalog + filters | Primary |
| /shop/:slug | Product | Gallery, variants, add to cart | — |
| /cart | Flow | Line items + checkout CTA | Utility |
| /checkout | Form | Shipping + payment | Flow |
| /account | Dashboard | Orders, addresses | Account |

## Next steps
1. Hub + detail for products; keep checkout separate from catalog filters""",
    },
    {
        "id": "blog",
        "title": "Blog / content site",
        "site_type": "blog",
        "aliases": [
            "blog website",
            "blog site",
            "magazine site",
            "content site",
            "newsletter site",
        ],
        "templates": ["landing", "data-table"],
        "plan": """## Sitemap
| URL | Type | Job | Nav |
|-----|------|-----|-----|
| / | Home | Latest posts + featured | Primary |
| /posts | Hub | Archive + tags | Primary |
| /posts/:slug | Article | Long-form content | — |
| /about | Static | Author / publication | Footer |
| /subscribe | Form | Email capture | CTA |

## Next steps
1. Hub + detail for posts; tag pages optional later""",
    },
    {
        "id": "dashboard_app",
        "title": "Dashboard / admin app",
        "site_type": "app",
        "aliases": [
            "admin dashboard",
            "analytics dashboard",
            "internal tool",
            "admin panel",
            "crm app",
            "management app",
        ],
        "templates": ["login", "dashboard", "data-table", "settings", "form"],
        "plan": """## Sitemap
| URL | Type | Job | Nav |
|-----|------|-----|-----|
| /login | Auth | Sign in | — |
| / | Dashboard | KPIs + recent activity | Primary |
| /records | Hub | Searchable table | Primary |
| /records/:id | Detail | View / edit entity | — |
| /settings | Settings | Profile, team, billing tabs | Account |

## Next steps
1. Scaffold `login` + `dashboard` + `data-table`
2. One primary job per screen; modals for quick edits only""",
    },
]

_BY_ID = {a["id"]: a for a in ARCHETYPES}
_BY_SITE_TYPE = {a["site_type"]: a for a in ARCHETYPES}


def list_archetypes() -> list[dict[str, Any]]:
    return [
        {
            "id": a["id"],
            "title": a["title"],
            "site_type": a["site_type"],
            "aliases": list(a["aliases"]),
            "templates": list(a.get("templates") or []),
        }
        for a in ARCHETYPES
    ]


def match_archetype(text: str) -> dict[str, Any] | None:
    clean = _normalize(text)
    if not clean:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    for arch in ARCHETYPES:
        for alias in arch["aliases"]:
            alias_norm = _normalize(alias)
            if alias_norm in clean:
                score = len(alias_norm)
                if score > best_score:
                    best_score = score
                    best = arch
    return best


def wants_cached_archetype(text: str) -> bool:
    """True when a bundled blueprint should be returned without LLM."""
    if not _enabled() or not match_archetype(text):
        return False
    clean = _normalize(text)
    if _BUILD_VERB_RE.search(clean):
        return True
    try:
        from arka.core.website_pages import wants_page_plan

        if wants_page_plan(text):
            return True
    except ImportError:
        pass
    return len(clean.split()) <= _SHORT_PROMPT_WORDS


def _templates_block(arch: dict[str, Any]) -> str:
    names = arch.get("templates") or []
    if not names:
        return ""
    lines = ["## Suggested UI scaffolds (cached)", "Start from Arka web templates:"]
    for name in names:
        lines.append(f"- `arka web template scaffold {name} --output ./site/`")
    lines.append("- MCP: `arka_web_template` with `action=scaffold`")
    return "\n".join(lines) + "\n"


def cached_plan(text: str, *, site_type: str | None = None) -> str | None:
    """Return a cached sitemap blueprint when the prompt matches a known archetype."""
    if not _enabled():
        return None
    arch = match_archetype(text)
    if arch is None and site_type:
        arch = _BY_SITE_TYPE.get(site_type.strip().lower()) or _BY_ID.get(site_type.strip().lower())
    if arch is None:
        return None
    prompt = " ".join((text or "").split()).strip()
    header = (
        f"## Request\n{prompt or arch['title']}\n\n"
        f"## Archetype\n**{arch['title']}** (`{arch['id']}`) — cached blueprint, no LLM wait\n\n"
    )
    body = str(arch.get("plan") or "").strip()
    footer = _templates_block(arch)
    return f"{header}{body}\n\n{footer}".strip()


def context_for(text: str, *, limit_chars: int = 2400) -> str:
    """Compact inject for agents when an archetype matches."""
    arch = match_archetype(text)
    if not arch:
        return ""
    templates = ", ".join(arch.get("templates") or [])
    block = (
        f"Matched website archetype: {arch['title']} ({arch['id']}). "
        f"Prefer cached sitemap via website_pages plan or archetype cache. "
        f"Suggested templates: {templates or 'landing, dashboard'}."
    )
    if len(block) > limit_chars:
        return block[:limit_chars].rstrip() + "…"
    return block


def status() -> dict[str, object]:
    return {
        "enabled": _enabled(),
        "count": len(ARCHETYPES),
        "ids": [a["id"] for a in ARCHETYPES],
    }
