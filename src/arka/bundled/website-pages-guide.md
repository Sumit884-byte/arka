# Website page organization guide

Models often dump everything on one page or split arbitrarily. Use this guide to divide content into pages with clear jobs, navigation, and URLs.

## Golden rule

**One primary job per page.** A visitor should know within 3 seconds why this page exists and what to do next.

If a page tries to do two unrelated jobs (e.g. sell the product AND host full API reference), split it.

## Workflow (always follow)

1. **Inventory** — List every topic, feature, audience, and action the site must support.
2. **Cluster by intent** — Group items that share the same visitor goal (learn, compare, buy, configure, get help).
3. **Assign page types** — Map each cluster to a page type (see below).
4. **Split or merge** — Apply the split/combine rules.
5. **Define navigation** — Primary nav (5–7 items max), secondary/footer, in-page anchors only when one page stays long.
6. **Output sitemap** — URL, title, purpose, main sections, links to/from other pages.

Do not write page copy until the sitemap is agreed.

## Page types

| Type | Job | Typical sections | When to use |
|------|-----|------------------|-------------|
| **Home** | Orient + route | Hero, value prop, social proof, primary CTAs, teaser links | Every marketing site; not a dump of all content |
| **Product / Features** | Explain what it does | Problem → solution, feature groups, screenshots, comparison | More than 3 features or multiple personas |
| **Pricing** | Compare plans + convert | Plans table, FAQ, enterprise CTA | Any paid product |
| **About** | Build trust | Story, team, mission, contact | Company or personal brand sites |
| **Docs — hub** | Route learners | Getting started, guides index, API index, search | Documentation sites |
| **Docs — guide** | Teach one task end-to-end | Prerequisites, steps, troubleshooting, next steps | One workflow (install, deploy, integrate) |
| **Docs — reference** | Lookup facts | Parameters, types, errors, examples | API, CLI, config keys — never mix with narrative guides |
| **Blog — index** | Browse posts | Filters, recent, categories | 5+ articles |
| **Blog — post** | One idea in depth | Title, date, body, related links | Single article |
| **Legal** | Compliance | Terms, privacy, cookies | Required for SaaS/commerce |
| **Auth** | Sign in/up/reset | Forms only; minimal chrome | Separate from marketing pages |
| **App / Dashboard view** | Task inside product | One screen = one primary task; use tabs/sub-routes for related panels | Web apps, not marketing |

## Split vs combine

**Split into a new page when:**

- Content exceeds ~800–1200 words of scannable sections AND serves a different intent.
- A section has its own SEO keyword or audience (e.g. "Pricing for teams" vs "Pricing for individuals").
- Navigation would hide the content more than 2 clicks deep without a hub page.
- Reference material (API, props, config) would bury a tutorial.

**Keep on one page when:**

- Sections are steps of the same task (short guide with anchors).
- Content is under ~600 words and one intent.
- Splitting would orphan content with no clear nav parent.

**Use a hub + detail pattern when:**

- Many similar items (blog posts, doc guides, product modules) — hub lists; each item gets its own URL.

## Navigation rules

- **Primary nav:** 5–7 top-level items. More → group under a "More" menu or footer.
- **Order by visitor journey:** Product → Pricing → Docs → About → Sign in (not alphabetical).
- **Footer:** Legal, contact, social, secondary links (changelog, status, careers).
- **Breadcrumbs:** Use on docs and e-commerce when depth > 2.
- **Don't duplicate:** Same link in nav and hero CTA is fine; same page linked 5 times in nav is not.

## URL conventions

- Lowercase, hyphenated: `/pricing`, `/docs/getting-started`, `/blog/my-post-slug`
- Stable paths: `/docs/api/authentication` not `/docs/page-3`
- Marketing at root; docs under `/docs`; blog under `/blog`; app under `/app` or subdomain
- One canonical URL per page; trailing slashes consistent

## Content per page template

For each page in the sitemap, specify:

```
Page: /pricing
Title: Pricing
Job: Help visitor pick a plan and start trial
Audience: Evaluating buyer
Sections:
  - Plan comparison table
  - Feature matrix (link to /features for detail)
  - FAQ (billing, limits)
  - Enterprise CTA
Primary CTA: Start free trial → /signup
Internal links: /features, /docs/getting-started, /contact
Do NOT include: Full API reference, long company history
```

## Common mistakes (avoid)

- **Kitchen-sink homepage** — Move features, pricing details, and docs to dedicated pages; home teases and links.
- **Mega-menu everything** — Deep trees without hub pages; fix with hubs and clearer IA.
- **Tutorial + reference on one URL** — Split guide (narrative) from reference (lookup).
- **One page per heading** — Over-splitting creates click fatigue; combine small related sections.
- **Orphan pages** — Every page reachable from nav, hub, or inline link within 2 clicks.
- **Duplicate pages** — `/contact` and `/about#contact` serving the same job; pick one canonical page.

## Site archetypes (starting sitemaps)

**Marketing SaaS (minimal):**
`/`, `/features`, `/pricing`, `/docs`, `/blog`, `/about`, `/login`, `/legal/privacy`, `/legal/terms`

**Documentation site:**
`/docs`, `/docs/getting-started`, `/docs/guides/*`, `/docs/reference/*`, `/changelog`

**Portfolio:**
`/`, `/work`, `/work/{slug}`, `/about`, `/contact`

**Web app (authenticated):**
Marketing shell at root; app routes under `/app/dashboard`, `/app/settings`, `/app/{resource}/{id}` — each route one primary task.

## Output format for plans

When asked to organize pages, respond with:

1. **Assumptions** (site type, audience) if not stated
2. **Sitemap table** — URL | Page type | One-line job | Nav placement
3. **Per-page outlines** — Sections + CTAs + what stays off the page
4. **Split/merge notes** — What you combined or separated and why
5. **Next step** — e.g. "Approve sitemap, then wire routes"
