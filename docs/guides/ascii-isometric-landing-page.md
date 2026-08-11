# ASCII Isometric Tech Landing Page Design System

A design specification and component guide for creating modern, developer-focused web interfaces featuring floating pill navigation, multi-column segmented cards, and isometric ASCII/halftone graphic art.

Use with the [frontend content guide](./frontend-content-guide.md) for copy and the [Google DESIGN.md guide](./google-design.md) for general token discipline.

---

## 1. Visual Philosophy & Core Aesthetics

- **Developer & AI resonance:** Combines retro terminal culture (ASCII characters, code textures) with modern high-end SaaS UI (clean typography, generous whitespace, rounded borders).
- **Key components:**
  1. **Floating pill header** — Centered, floating navigation bar with rounded edges and high-contrast branding.
  2. **Hero / section title** — Large, crisp, centered headings with high letter clarity.
  3. **Segmented feature container** — One enclosed white card containing equal vertical columns separated by subtle full-height dividers.
  4. **Isometric ASCII graphics** — Clean 3D wireframe illustrations rendered via ASCII text density, color-coded per column (Emerald, Coral, Violet).

---

## 2. Color Palette & Typography Tokens

### Color palette

```css
:root {
  /* Canvas & backgrounds */
  --bg-canvas: #fafafa;
  --bg-card: #ffffff;
  --bg-pill: #ffffff;

  /* Text */
  --text-primary: #111827;
  --text-secondary: #4b5563;
  --text-muted: #6b7280;

  /* Borders & dividers */
  --border-light: #e5e7eb;
  --border-subtle: #f3f4f6;

  /* Isometric ASCII accent colors */
  --accent-green: #10b981;
  --accent-coral: #f97316;
  --accent-purple: #8b5cf6;

  /* Shadows */
  --shadow-pill: 0 1px 2px rgba(0, 0, 0, 0.06), 0 8px 24px rgba(0, 0, 0, 0.06);
  --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.04), 0 12px 32px rgba(0, 0, 0, 0.04);
}
```

### Typography

```css
:root {
  --font-sans: "Inter", "SF Pro Text", system-ui, -apple-system, sans-serif;
  --font-mono: "JetBrains Mono", "SF Mono", ui-monospace, monospace;

  --text-hero: clamp(2.5rem, 5vw, 3.75rem);
  --text-section: clamp(1.75rem, 3vw, 2.25rem);
  --text-body: 1rem;
  --text-small: 0.875rem;

  --leading-tight: 1.1;
  --leading-normal: 1.5;
  --tracking-tight: -0.02em;
}
```

| Role | Size | Weight | Notes |
|------|------|--------|-------|
| Hero title | `--text-hero` | 600–700 | Centered, `--tracking-tight` |
| Section title | `--text-section` | 600 | One idea per section |
| Body | `--text-body` | 400 | `--text-secondary` for supporting copy |
| Nav links | `--text-small` | 500 | `--text-muted`, darken on hover |
| ASCII art | 10–12px mono | 400 | Preserve `white-space: pre`, line-height 1.1 |

---

## 3. Layout Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  bg: --bg-canvas, min-height 100vh, padding-top for pill    │
│                                                             │
│              ┌─────────────────────────┐                    │
│              │   floating pill nav     │  sticky / fixed    │
│              └─────────────────────────┘                    │
│                                                             │
│                    Hero headline                            │
│                 Supporting subcopy                          │
│                   [ Primary CTA ]                           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  segmented card (--bg-card, --shadow-card)          │   │
│  │  ┌──────────┬──────────┬──────────┐                   │   │
│  │  │ col 1    │ col 2    │ col 3    │  vertical       │   │
│  │  │ ASCII    │ ASCII    │ ASCII    │  dividers       │   │
│  │  │ green    │ coral    │ purple   │                 │   │
│  │  │ title    │ title    │ title    │                 │   │
│  │  │ body     │ body     │ body     │                 │   │
│  │  └──────────┴──────────┴──────────┘                   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Spacing scale

Use an 8px base: `8, 16, 24, 32, 48, 64, 96`. Section vertical rhythm: `96px` between major blocks on desktop, `64px` on mobile.

### Breakpoints

| Token | Width | Behavior |
|-------|-------|----------|
| `sm` | 640px | Stack segmented columns |
| `md` | 768px | Reduce hero size one step |
| `lg` | 1024px | Full 3-column segmented card |
| `xl` | 1280px | Max content width ~1120px |

---

## 4. Components

### 4.1 Floating pill navigation

- Centered horizontally; `top: 16–24px` from viewport.
- Background `--bg-pill`, border `1px solid --border-light`, `--shadow-pill`.
- Border-radius: `9999px` (full pill).
- Inner padding: `8px 8px 8px 20px` (logo left, links center/right).
- Logo: wordmark or monogram, `--text-primary`, no heavy gradients.
- Links: `--text-small`, `--text-muted`; active link `--text-primary` + subtle underline or dot.
- CTA inside pill: filled button with `--text-primary` on white or inverted dark chip.

```html
<header class="site-header">
  <nav class="pill-nav" aria-label="Primary">
    <a class="pill-nav__logo" href="/">Product</a>
    <ul class="pill-nav__links">
      <li><a href="#features">Features</a></li>
      <li><a href="#docs">Docs</a></li>
      <li><a href="#pricing">Pricing</a></li>
    </ul>
    <a class="pill-nav__cta" href="#start">Get started</a>
  </nav>
</header>
```

```css
.site-header {
  position: sticky;
  top: 20px;
  z-index: 50;
  display: flex;
  justify-content: center;
  padding: 0 16px;
  pointer-events: none;
}
.pill-nav {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 8px 8px 8px 20px;
  background: var(--bg-pill);
  border: 1px solid var(--border-light);
  border-radius: 9999px;
  box-shadow: var(--shadow-pill);
}
.pill-nav__cta {
  padding: 8px 16px;
  border-radius: 9999px;
  background: var(--text-primary);
  color: #fff;
  font-size: var(--text-small);
  font-weight: 500;
  text-decoration: none;
}
```

### 4.2 Hero

- Center-aligned text; max-width ~720px.
- Headline: `--text-hero`, `--text-primary`, `--leading-tight`.
- Subcopy: `--text-body`, `--text-secondary`, max 2 lines on desktop.
- Single primary CTA; optional secondary ghost link.
- Optional: faint ASCII halftone watermark behind hero at 4–8% opacity.

### 4.3 Segmented feature card

- One outer card: `--bg-card`, `border-radius: 16–24px`, `--shadow-card`, `1px solid --border-subtle`.
- Inside: CSS grid `repeat(3, 1fr)` on `lg+`; stack on mobile.
- Column dividers: `border-right: 1px solid --border-light` (omit on last column / stacked).
- Each column: ASCII art top, title, 2–3 lines body, optional text link.
- Equal column padding: `32–40px`.

```html
<section class="segmented" id="features">
  <div class="segmented__card">
    <article class="segmented__col segmented__col--green">
      <pre class="ascii-art" aria-hidden="true">…</pre>
      <h3>Fast iteration</h3>
      <p>Ship prompts and workflows without leaving your editor.</p>
    </article>
    <article class="segmented__col segmented__col--coral">…</article>
    <article class="segmented__col segmented__col--purple">…</article>
  </div>
</section>
```

```css
.segmented__card {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 20px;
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.segmented__col {
  padding: 40px 32px;
  border-right: 1px solid var(--border-light);
}
.segmented__col:last-child { border-right: none; }
.segmented__col--green .ascii-art { color: var(--accent-green); }
.segmented__col--coral .ascii-art { color: var(--accent-coral); }
.segmented__col--purple .ascii-art { color: var(--accent-purple); }
@media (max-width: 1023px) {
  .segmented__card { grid-template-columns: 1fr; }
  .segmented__col { border-right: none; border-bottom: 1px solid var(--border-light); }
  .segmented__col:last-child { border-bottom: none; }
}
```

### 4.4 Isometric ASCII graphics

**Rules:**

- Use monospace `<pre>` blocks; never rasterize unless exporting for OG images.
- Density: 12–18 lines tall, 28–40 characters wide per column graphic.
- Simulate isometric depth with `/`, `\`, `|`, `_`, and shaded blocks (`#`, `%`, `.`).
- One accent color per column; no rainbow gradients inside a single graphic.
- Keep art abstract (cubes, stacks, terminals, pipelines) — not photorealistic.
- `aria-hidden="true"` on decorative ASCII; column title carries meaning.

**Example (green — data pipeline):**

```
      +-------+
     /       /|
    +-------+ |
    |   ### | +    <- stack / cube motif
    |  #####|/
    +-------+
       |||
    [ terminal prompt >_ ]
```

Assign colors only via CSS `color` on `.ascii-art`, not inline styles per character.

---

## 5. Page checklist

Before shipping a page in this system:

- [ ] Canvas is `--bg-canvas`; no pure `#fff` full-page bleed except cards/pill
- [ ] Pill nav floats above content with shadow, not a full-width bar
- [ ] Hero is centered with one primary CTA
- [ ] Features live in a **single** segmented card, not three separate cards
- [ ] ASCII art is monospace, preformatted, and color-coded per column
- [ ] Copy follows frontend content guide (outcomes, not stack names)
- [ ] Mobile: columns stack; pill nav remains usable (scroll or compact links)
- [ ] Focus states visible on all interactive elements

---

## 6. Arka integration

### Environment

In `~/.config/arka/.env`:

```bash
ASCII_ISOMETRIC_DESIGN_GUIDE=1              # default on
ASCII_ISOMETRIC_DESIGN_GUIDE_MODE=auto      # auto | always | off
```

### CLI & MCP

```bash
arka md_doc read ascii-isometric-landing-page
arka md_doc context ascii-isometric-landing-page
```

MCP: `arka_markdown` with `action=read`, `path=ascii-isometric-landing-page`.

Natural language:

```text
use ascii isometric landing page design
follow ascii-isometric-landing-page guide
```

Auto-injects alongside frontend content and Google DESIGN guides when building developer landing pages, isometric ASCII UI, or pill-nav layouts.
