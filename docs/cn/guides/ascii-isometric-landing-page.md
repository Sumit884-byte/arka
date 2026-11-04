# ASCII 等距科技落地页设计系统

一份设计规范和组件指南，用于打造面向开发者的现代 Web 界面，包含悬浮胶囊导航、多列分段卡片以及等距 ASCII/半色调图形艺术。

请配合 [前端内容指南](./frontend-content-guide.md) 编写文案，并配合 [Google DESIGN.md 指南](./google-design.md) 遵循通用的 token 规范。

---

## 1. 视觉理念与核心美学

- **开发者与 AI 共鸣：** 将复古终端文化（ASCII 字符、代码纹理）与现代高端 SaaS UI（简洁的排版、充足的留白、圆角边框）相结合。
- **关键组件：**
  1. **悬浮胶囊页眉** — 居中悬浮的导航栏，带圆角边缘和高对比度品牌标识。
  2. **Hero / 区块标题** — 大号、清晰、居中的标题，字形辨识度高。
  3. **分段功能容器** — 一张封闭的白色卡片，内含等宽的竖列，以细微的全高分隔线隔开。
  4. **等距 ASCII 图形** — 通过 ASCII 文字密度渲染的简洁 3D 线框插图，每列使用不同配色（Emerald、Coral、Violet）。

---

## 2. 调色板与排版 Token

### 调色板

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

### 排版

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

| 角色 | 字号 | 字重 | 说明 |
|------|------|--------|-------|
| Hero 标题 | `--text-hero` | 600–700 | 居中，`--tracking-tight` |
| 区块标题 | `--text-section` | 600 | 每个区块一个主题 |
| 正文 | `--text-body` | 400 | 辅助文案使用 `--text-secondary` |
| 导航链接 | `--text-small` | 500 | `--text-muted`，悬停时加深 |
| ASCII 艺术 | 10–12px 等宽 | 400 | 保留 `white-space: pre`，行高 1.1 |

---

## 3. 布局架构

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

### 间距尺度

使用 8px 基准：`8, 16, 24, 32, 48, 64, 96`。区块垂直节奏：桌面端主要区块之间间隔 `96px`，移动端为 `64px`。

### 断点

| Token | 宽度 | 行为 |
|-------|-------|----------|
| `sm` | 640px | 分段列堆叠显示 |
| `md` | 768px | Hero 字号降低一级 |
| `lg` | 1024px | 完整的 3 列分段卡片 |
| `xl` | 1280px | 最大内容宽度约 1120px |

---

## 4. 组件

### 4.1 悬浮胶囊导航

- 水平居中；距视口 `top: 16–24px`。
- 背景 `--bg-pill`，边框 `1px solid --border-light`，`--shadow-pill`。
- 圆角：`9999px`（完整胶囊形）。
- 内边距：`8px 8px 8px 20px`（logo 居左，链接居中/居右）。
- Logo：文字标识或字母组合标识，`--text-primary`，避免厚重渐变。
- 链接：`--text-small`、`--text-muted`；当前链接使用 `--text-primary` 并加上细微下划线或圆点。
- 胶囊内的 CTA：在白底上使用 `--text-primary` 的填充按钮，或反色的深色 chip。

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

- 文本居中对齐；最大宽度约 720px。
- 标题：`--text-hero`、`--text-primary`、`--leading-tight`。
- 副文案：`--text-body`、`--text-secondary`，桌面端最多 2 行。
- 单个主要 CTA；可选一个次要的幽灵链接。
- 可选：在 Hero 背后放置一个透明度为 4–8% 的淡淡 ASCII 半色调水印。

### 4.3 分段功能卡片

- 一张外层卡片：`--bg-card`、`border-radius: 16–24px`、`--shadow-card`、`1px solid --border-subtle`。
- 内部：在 `lg+` 上使用 CSS grid `repeat(3, 1fr)`；移动端堆叠。
- 列分隔线：`border-right: 1px solid --border-light`（最后一列/堆叠时省略）。
- 每列：顶部为 ASCII 艺术，然后是标题、2–3 行正文，以及可选的文本链接。
- 各列内边距相等：`32–40px`。

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

### 4.4 等距 ASCII 图形

**规则：**

- 使用等宽 `<pre>` 块；除非导出为 OG 图片，否则不要栅格化。
- 密度：每列图形高 12–18 行、宽 28–40 个字符。
- 使用 `/`、`\`、`|`、`_` 以及阴影字符块（`#`、`%`、`.`）模拟等距纵深。
- 每列一种强调色；单个图形内不要使用彩虹渐变。
- 保持抽象风格（立方体、堆叠、终端、流水线）——而非照片级写实。
- 装饰性 ASCII 设置 `aria-hidden="true"`；由列标题承载语义。

**示例（绿色——数据流水线）：**

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

只通过 `.ascii-art` 上的 CSS `color` 分配颜色，不要为每个字符使用内联样式。

---

## 5. 页面检查清单

在此系统中发布页面之前：

- [ ] 画布为 `--bg-canvas`；除卡片/胶囊外，不使用纯 `#fff` 铺满整页
- [ ] 胶囊导航带阴影悬浮于内容之上，而不是全宽横条
- [ ] Hero 居中，且只有一个主要 CTA
- [ ] 功能放在**单张**分段卡片中，而不是三张独立卡片
- [ ] ASCII 艺术为等宽、预格式化，并按列配色
- [ ] 文案遵循前端内容指南（讲结果，而非技术栈名称）
- [ ] 移动端：列堆叠显示；胶囊导航仍然可用（滚动或紧凑链接）
- [ ] 所有交互元素的焦点状态均可见

---

## 6. Arka 集成

### 环境

在 `~/.config/arka/.env` 中：

```bash
ASCII_ISOMETRIC_DESIGN_GUIDE=1              # default on
ASCII_ISOMETRIC_DESIGN_GUIDE_MODE=auto      # auto | always | off
```

### CLI 与 MCP

```bash
arka md_doc read ascii-isometric-landing-page
arka md_doc context ascii-isometric-landing-page
```

MCP：`arka_markdown`，使用 `action=read`、`path=ascii-isometric-landing-page`。

自然语言：

```text
use ascii isometric landing page design
follow ascii-isometric-landing-page guide
```

在构建开发者落地页、等距 ASCII UI 或胶囊导航布局时，会与前端内容指南和 Google DESIGN 指南一起自动注入。
