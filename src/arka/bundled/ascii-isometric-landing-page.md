# ASCII Isometric Tech Landing Page Design System

A design specification and component guide for creating modern, developer-focused web interfaces featuring floating pill navigation, multi-column segmented cards, and isometric ASCII/halftone graphic art.

Use with the frontend content guide for copy and the Google DESIGN.md guide for general token discipline.

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
│              ┌─────────────────────────┐                    │
│              │   floating pill nav     │                    │
│              └─────────────────────────┘                    │
│                    Hero headline                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  segmented card (3 columns + ASCII accents)         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

Spacing: 8px base scale. Section rhythm: 96px desktop / 64px mobile. Max content width ~1120px.

---

## 4. Components

### Floating pill navigation

Centered sticky pill: `--bg-pill`, `border-radius: 9999px`, `--shadow-pill`, logo + links + CTA chip.

### Hero

Center-aligned, max-width ~720px, one primary CTA, optional faint ASCII watermark at low opacity.

### Segmented feature card

Single outer card with CSS grid columns, vertical dividers, per-column ASCII art in `--accent-green`, `--accent-coral`, `--accent-purple`.

### Isometric ASCII graphics

Monospace `<pre>`, 12–18 lines, abstract isometric cubes/stacks/terminals, one accent color per column, `aria-hidden="true"`.

---

## 5. Page checklist

- Canvas `--bg-canvas`; cards/pill white
- Pill nav floats — not full-width bar
- Features in one segmented card, not three separate cards
- ASCII art monospace + color per column
- User-facing copy per frontend content guide
- Mobile column stack + accessible focus states

---

## 6. Arka

```bash
ASCII_ISOMETRIC_DESIGN_GUIDE=1
ASCII_ISOMETRIC_DESIGN_GUIDE_MODE=auto
```

```bash
arka md_doc read ascii-isometric-landing-page
```

MCP: `arka_markdown` path `ascii-isometric-landing-page`.
