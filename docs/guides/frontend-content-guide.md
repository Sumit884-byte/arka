# Frontend content guide

Use this when designing or reviewing any user-facing screen, landing page, or in-app copy.
The frontend is for **people using the product**, not for documenting how it was built.

---

## Golden rule

**Show outcomes, actions, and trust signals. Hide implementation, org structure, and ops.**

If a sentence would only make sense to an engineer, a founder filling out a grant form, or someone reading the repo — it does not belong in the default UI.

---

## Show on the frontend

| Category | Examples |
|----------|----------|
| **What the product does** | One-line value prop, feature benefits in plain language |
| **What the user can do next** | Primary CTA, empty states with a clear next step |
| **Status that affects the user** | “Message sent”, “Syncing…”, “Upload failed — try again” |
| **Inputs the user must provide** | Email, password, preferences, content they own |
| **Trust & safety (user-relevant)** | Privacy summary, data retention in plain terms, support contact |
| **Pricing (when you sell)** | Plans, limits, trial length — only what changes what they pay or get |
| **Accessibility** | Labels, errors tied to fields, focus order, contrast — not optional |

### Good patterns

- “Connect your LinkedIn account to send messages from one place.”
- “We store your credentials locally on this device.”
- “3 messages scheduled for today.”

---

## Do not show on the frontend

| Category | Why it stays internal |
|----------|------------------------|
| **Tech stack** | React, Next.js, Python, Selenium, Ollama, Postgres — users do not choose these |
| **Profit vs non-profit status** | Org tax status is irrelevant unless the product *is* fundraising or grants |
| **Internal tools** | Arka, Cursor, PrivateGPT, SigNoz, CI, Docker, `.env` |
| **Architecture & APIs** | Microservices, webhooks, queue names, model IDs, provider fallbacks |
| **Dev / ops health banners** | “Database connected”, “API healthy”, “Redis up”, “8 posts loaded” — infra checks belong in logs, not chrome |
| **Business classification** | “B2B”, “hackathon project”, “side project”, revenue model for investors |
| **Raw errors & stack traces** | Log IDs ok in support flows; never stack traces on main UI |
| **Security internals** | Key names, vault paths, OAuth client secrets, token rotation policy |
| **Compliance boilerplate (unfiltered)** | Full legal entity names, DUNS, internal policy IDs — link out instead |

### Bad patterns (remove or move to docs/admin)

- “Powered by Selenium + Groq + Arka agent hub.”
- “This is a non-profit research prototype.”
- “Backend: FastAPI on Railway, frontend: Vite.”
- “ROUTE_MODE=symbolic, LLM fallback enabled.”
- “Database connected · API healthy · 8 posts loaded”
- “Postgres OK · Prisma connected · cache warm”

**Use instead (or hide entirely unless the user must act):**

- “8 posts ready”
- “ResearchFeed is online — browse the latest posts.”
- On failure only: “Couldn’t load posts. Try again in a moment.”

---

## Gray area — show only when intentional

| Topic | When it may appear |
|-------|-------------------|
| **Open source / license** | Footer or About if you distribute code; one short line, link to LICENSE |
| **AI / automation** | If users must know content is AI-generated (disclosure laws, trust) — one clear sentence, not model names |
| **Integrations** | “Sign in with Google” (user action), not “Google OAuth client ID configured” |
| **Non-profit / mission** | Marketing site **About** page if mission is the product; not in app chrome or error toasts |
| **Tech details** | Developer docs, `/docs`, README, admin console — never default dashboard |

---

## Screen-by-screen checklist

Before shipping a page or modal, confirm:

- [ ] Every visible label answers “what can *I* do?” or “what happened to *my* stuff?”
- [ ] No framework, library, or infra names unless the user explicitly opted into a developer view
- [ ] No profit / non-profit / funding / hackathon language unless that page is **About** or **Pricing**
- [ ] Errors are actionable (“Check your password”) not diagnostic (“401 from `/api/v1/auth`”)
- [ ] Settings expose **user choices** (language, notifications), not **deploy config** (API base URL)
- [ ] Empty states teach the first action, not how the system works internally
- [ ] Footer/legal: links to Privacy & Terms, not internal runbooks
- [ ] No dev-status strip (database/API/queue health, “N records loaded”) unless the page is an admin console

---

## Copy templates

### Hero / landing

**Do:** “Send personalized LinkedIn messages without switching tabs.”  
**Don’t:** “A Python automation stack for outbound growth (non-profit MVP).”

### Settings

**Do:** “LinkedIn account”, “Daily send limit”, “Pause automation”.  
**Don’t:** “LINKEDIN_USERNAME env var”, “ChromeDriver path”, “Arka routing mode”.

### Errors

**Do:** “Couldn’t sign in. Check your email and password.”  
**Don’t:** “WebDriverException: chrome not reachable (Arka coding-tui baseline).”

### About (optional page)

**Do:** Mission in one paragraph; link to privacy; contact support.  
**Don’t:** Full tech appendix unless the audience is developers and the page is labeled **For developers**.

### Status / health pages

**Do:** “ResearchFeed is online”, “Feed and sign-in are available”, “8 posts ready to read”.  
**Don’t:** “Database connected · API healthy · 8 posts loaded” — log connection checks; show user outcomes only.

---

## For agents and builders

Arka loads this guide **automatically** for frontend/UI work, coding-tui plans, and
`frontend_loop` screenshot reviews (`FRONTEND_CONTENT_GUIDE=1` by default). Pair with
the [Google DESIGN.md guide](./google-design.md) for visual tokens and layout.

Optional overrides in `~/.config/arka/.env`:

```bash
FRONTEND_CONTENT_GUIDE=1              # default on
FRONTEND_CONTENT_GUIDE_MODE=auto      # auto | always | off
```

Manual read when needed:

```bash
arka md_doc read docs/guides/frontend-content-guide.md
```

Via MCP, `arka_markdown` accepts the alias `frontend-content-guide` (bundled copy policy).

When implementing UI:

1. Do not paste tech stack, profit/non-profit status, or internal tool names into user-visible copy.
2. Put technical notes in code comments, README, or internal docs — not in buttons or toasts.
3. If unsure, show less on screen; link out for depth.
4. Run `arka ui-copy .` after UI changes to catch duplicate labels.

---

## Quick reference

| Show | Hide |
|------|------|
| User goals & results | Stack & infrastructure |
| Actionable errors | Stack traces & env keys |
| Plan limits users hit | Profit / non-profit / funding story |
| Plain privacy summary | Internal tool names |
| CTAs & progress | Architecture diagrams in main app flow |
