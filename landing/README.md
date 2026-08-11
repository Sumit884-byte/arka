# Arka landing page

Static marketing page for the [Arka](https://github.com/Sumit884-byte/arka) project — hero, features, install CTA, and links to docs, GitHub, PyPI, and the desktop app.

No build step. Self-contained HTML, CSS, and a small JS file under `landing/`.

## Preview locally

From this directory:

```bash
python3 -m http.server 8080
```

Then open [http://localhost:8080](http://localhost:8080).

Alternatives:

```bash
npx --yes serve .
# or
php -S localhost:8080
```

## Files

| File | Purpose |
| --- | --- |
| `index.html` | Page structure and content |
| `styles.css` | Dark theme matching Arka UI (`#0b0d12` bg, orange accent) |
| `main.js` | Mobile nav, copy install command, scroll reveal |
| `assets/` | Logo SVGs (from `docs/logo/`) |

## Deploy

Any static host works — GitHub Pages, Netlify, Cloudflare Pages, etc. Point the site root at this `landing/` folder (or copy its contents to your host's publish directory).

For GitHub Pages from the repo root, enable **Settings → Pages → GitHub Actions**. Pushes to `main` that touch `landing/` deploy via `.github/workflows/pages.yml` to **https://sumit884-byte.github.io/arka/** (upstream repo).

## Brand

Colors and typography align with:

- `desktop/ui/src/styles/global.css` — dark shell, orange accent
- `docs/docs.json` — indigo primary (`#6366F1`)
- `docs/logo/` — mark and wordmark SVGs
