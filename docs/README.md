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
└── favicon.svg
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

Edit MDX pages in this folder and open a PR on `Sumit884-byte/arka`. Follow existing frontmatter (`title`, `description`, `keywords`) and Mintlify components (`Card`, `Tip`, `Note`, `Warning`).
