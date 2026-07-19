# Arka documentation (Mintlify)

This folder is the **source of truth** for [arka-agent.mintlify.site](https://arka-agent.mintlify.site).

Mintlify deploys from the main [Sumit884-byte/arka](https://github.com/Sumit884-byte/arka) repository. One push to `main` updates both the app repo and the live docs site (after Mintlify is pointed at this repo — see below).

## Local preview

Install the [Mintlify CLI](https://www.npmjs.com/package/mint):

```bash
npm i -g mint
```

From this directory (`docs/`, where `docs.json` lives):

```bash
mint dev
```

Open [http://localhost:3000](http://localhost:3000).

## Reliability checks

Before publishing docs changes, run the lightweight repository checker from the
repo root:

```bash
python scripts/check_docs.py docs
```

The checker verifies internal Mintlify links and basic MDX frontmatter such as
`title`. It is intentionally local-only and does not crawl external websites.

## Structure

```
docs/
├── docs.json          # Mintlify navigation and site config
├── index.mdx          # Home page
├── quickstart.mdx
├── concepts/          # Routing, LLM, security
├── guides/            # Feature guides
├── reference/         # Configuration, aliases, troubleshooting
├── logo/
│   ├── icon.png       # Brand mark (terminal prompt + figure)
│   ├── mark.svg       # Vector mark for scaling
│   ├── light.svg      # Navbar logo (light theme)
│   └── dark.svg       # Navbar logo (dark theme)
├── favicon.svg
└── favicon.png
```

## Mintlify dashboard setup

After consolidating docs into this repo, update the Mintlify project once:

1. Open [Mintlify dashboard](https://dashboard.mintlify.com) → your Arka project → **Settings** → **Git**.
2. Change the connected repository from `Sumit884-byte/docs` to **`Sumit884-byte/arka`**.
3. Set **docs path** to `/docs` (not repo root).
4. Set **branch** to `main`.
5. Save and trigger a deploy (or push a commit to `main`).

The public URL stays **https://arka-agent.mintlify.site**.

## Contributing

Edit MDX pages in this folder and open a PR on `Sumit884-byte/arka`. Follow existing frontmatter (`title`, `description`, `keywords`) and Mintlify components (`Card`, `Tip`, `Note`, `Warning`). Run `python scripts/check_docs.py docs` before pushing.

## SEO checklist

- Give every public page a unique, search-oriented `title` and a 140–160 character `description`.
- Add 3–8 specific `keywords` that match the page intent; avoid repeating the site name in every keyword.
- Put the primary phrase in the opening paragraph and one heading, then link to the relevant guide.
- Prefer descriptive internal links such as “local model selection” over “click here”.
- Keep command examples indexable and human-readable; do not put secrets or user-specific paths in examples.
- Mintlify supplies canonical URLs, sitemap, robots, and Open Graph metadata from this frontmatter and `docs.json`; verify them after deployment.
