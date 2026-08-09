# Project Docs

First-person README and `blog-post.md` synced to git changes. Voice: **"I built…"**, **"I learned…"** — not corporate "we".

## When to use

- After shipping features — refresh README and blog to match the code
- Starting a dev.to post from an existing repo
- Keeping portfolio docs in sync without dumping markdown in chat

## CLI

```bash
arka project_docs status
arka project_docs readme --apply
arka project_docs blog --apply
arka project_docs update --apply
arka project_docs blog --apply --post          # write + publish to dev.to
arka project_docs update --apply --post
arka project_docs status --since abc1234
```

## Natural language

- "sync project docs from code changes"
- "update readme in first person"
- "write blog in first person and post to dev.to"
- "first person readme from recent changes"

## Output files

| File | Sections |
|------|----------|
| `README.md` | What it is, demo, stack, how to run, journey/learnings |
| `blog-post.md` | What I Built, Demo, Stack, proud of, learned, what's next |

Preserves existing YAML frontmatter on `blog-post.md`. Optional `--post` delegates to `devto_post` (needs `DEVTO_API_KEY`).

## vs human_docs

- **project_docs** — repo-aware, first-person, syncs from git diff
- **human_docs** — generic human-sounding markdown from a prompt
