# ASCII Isometric Tech Landing Page Design System

आधुनिक, developer-focused web interfaces बनाने के लिए एक design specification और component guide, जिसमें floating pill navigation, multi-column segmented cards, और isometric ASCII/halftone graphic art शामिल हैं।

Copy के लिए [frontend content guide](./frontend-content-guide.md) और सामान्य token discipline के लिए [Google DESIGN.md guide](./google-design.md) के साथ इसका उपयोग करें।

---

## 1. Visual दर्शन और मूल सौंदर्यशास्त्र

- **Developer & AI resonance:** Retro terminal culture (ASCII characters, code textures) को आधुनिक high-end SaaS UI (साफ़ typography, भरपूर whitespace, rounded borders) के साथ जोड़ता है।
- **मुख्य components:**
  1. **Floating pill header** — Rounded edges और high-contrast branding वाला centered, floating navigation bar।
  2. **Hero / section title** — उच्च अक्षर-स्पष्टता वाले बड़े, स्पष्ट, centered headings।
  3. **Segmented feature container** — एक बंद white card, जिसमें बराबर vertical columns हों जो हल्के full-height dividers से अलग किए गए हों।
  4. **Isometric ASCII graphics** — ASCII text density के ज़रिए render किए गए साफ़ 3D wireframe illustrations, हर column के लिए अलग color (Emerald, Coral, Violet)।

---

## 2. Color Palette और Typography Tokens

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

| भूमिका | Size | Weight | टिप्पणियाँ |
|------|------|--------|-------|
| Hero title | `--text-hero` | 600–700 | Centered, `--tracking-tight` |
| Section title | `--text-section` | 600 | हर section में एक विचार |
| Body | `--text-body` | 400 | Supporting copy के लिए `--text-secondary` |
| Nav links | `--text-small` | 500 | `--text-muted`, hover पर गहरा करें |
| ASCII art | 10–12px mono | 400 | `white-space: pre` बनाए रखें, line-height 1.1 |

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

8px base का उपयोग करें: `8, 16, 24, 32, 48, 64, 96`। Section vertical rhythm: desktop पर मुख्य blocks के बीच `96px`, mobile पर `64px`।

### Breakpoints

| Token | Width | व्यवहार |
|-------|-------|----------|
| `sm` | 640px | Segmented columns को stack करें |
| `md` | 768px | Hero size को एक step कम करें |
| `lg` | 1024px | पूरा 3-column segmented card |
| `xl` | 1280px | अधिकतम content width ~1120px |

---

## 4. Components

### 4.1 Floating pill navigation

- Horizontally centered; viewport से `top: 16–24px`।
- Background `--bg-pill`, border `1px solid --border-light`, `--shadow-pill`।
- Border-radius: `9999px` (पूरा pill)।
- Inner padding: `8px 8px 8px 20px` (logo बाएँ, links center/दाएँ)।
- Logo: wordmark या monogram, `--text-primary`, भारी gradients नहीं।
- Links: `--text-small`, `--text-muted`; active link `--text-primary` + हल्का underline या dot।
- Pill के अंदर CTA: white पर `--text-primary` वाला filled button या inverted dark chip।

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

- Center-aligned text; max-width ~720px।
- Headline: `--text-hero`, `--text-primary`, `--leading-tight`।
- Subcopy: `--text-body`, `--text-secondary`, desktop पर अधिकतम 2 पंक्तियाँ।
- एक ही primary CTA; वैकल्पिक secondary ghost link।
- वैकल्पिक: hero के पीछे 4–8% opacity पर हल्का ASCII halftone watermark।

### 4.3 Segmented feature card

- एक outer card: `--bg-card`, `border-radius: 16–24px`, `--shadow-card`, `1px solid --border-subtle`।
- अंदर: `lg+` पर CSS grid `repeat(3, 1fr)`; mobile पर stack करें।
- Column dividers: `border-right: 1px solid --border-light` (अंतिम column / stacked होने पर हटा दें)।
- हर column: ऊपर ASCII art, title, 2–3 पंक्तियों का body, वैकल्पिक text link।
- बराबर column padding: `32–40px`।

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

**नियम:**

- Monospace `<pre>` blocks का उपयोग करें; OG images के लिए export करने के अलावा कभी rasterize न करें।
- Density: हर column graphic 12–18 पंक्तियाँ ऊँचा, 28–40 characters चौड़ा।
- `/`, `\`, `|`, `_`, और shaded blocks (`#`, `%`, `.`) से isometric depth simulate करें।
- हर column में एक accent color; एक ही graphic के अंदर rainbow gradients नहीं।
- Art को abstract रखें (cubes, stacks, terminals, pipelines) — photorealistic नहीं।
- Decorative ASCII पर `aria-hidden="true"`; अर्थ column title से मिलता है।

**उदाहरण (green — data pipeline):**

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

Colors केवल `.ascii-art` पर CSS `color` के ज़रिए assign करें, हर character पर inline styles से नहीं।

---

## 5. Page checklist

इस system में कोई page ship करने से पहले:

- [ ] Canvas `--bg-canvas` है; cards/pill के अलावा कोई pure `#fff` full-page bleed नहीं
- [ ] Pill nav shadow के साथ content के ऊपर float करता है, full-width bar नहीं है
- [ ] Hero एक primary CTA के साथ centered है
- [ ] Features एक **ही** segmented card में हैं, तीन अलग cards में नहीं
- [ ] ASCII art monospace, preformatted, और हर column के अनुसार color-coded है
- [ ] Copy frontend content guide का पालन करती है (outcomes, stack names नहीं)
- [ ] Mobile: columns stack होते हैं; pill nav उपयोग योग्य रहता है (scroll या compact links)
- [ ] सभी interactive elements पर focus states दिखाई देते हैं

---

## 6. Arka integration

### Environment

`~/.config/arka/.env` में:

```bash
ASCII_ISOMETRIC_DESIGN_GUIDE=1              # default on
ASCII_ISOMETRIC_DESIGN_GUIDE_MODE=auto      # auto | always | off
```

### CLI & MCP

```bash
arka md_doc read ascii-isometric-landing-page
arka md_doc context ascii-isometric-landing-page
```

MCP: `action=read`, `path=ascii-isometric-landing-page` के साथ `arka_markdown`।

Natural language:

```text
use ascii isometric landing page design
follow ascii-isometric-landing-page guide
```

Developer landing pages, isometric ASCII UI, या pill-nav layouts बनाते समय यह frontend content और Google DESIGN guides के साथ अपने-आप inject होता है।
