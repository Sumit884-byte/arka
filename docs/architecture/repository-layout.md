# Repository layout

Arka keeps runtime code under `src/arka/`, executable maintenance helpers in
`scripts/`, tests in `tests/`, and user-facing documentation in `docs/`.

## Source tree (committed)

| Path | Purpose |
|------|---------|
| `src/arka/` | Python package — skills, routing, integrations |
| `src/arka/agent/` | User-facing task workflows |
| `src/arka/core/` | Shared config, security, routing primitives |
| `src/arka/integrations/` | External systems and MCP adapters |
| `src/arka/llm/` | Providers, fallback, model selection |
| `src/arka/routing/` | Symbolic and NL route translation |
| `src/arka/fish/`, `src/arka/bundled/` | Fish runtime and synced distribution assets |
| `bin/` | Legacy CLI shims (synced into `bundled/` for installs) |
| `scripts/` | Maintainer tooling (`sync_bundled.py`, publish, refetch) |
| `tests/` | Pytest suite |
| `docs/` | Mintlify documentation |
| `recordings/` | Curated demo captures (CLI screenshots, terminal transcripts) |
| `examples/` | Sample configs and harnesses |

New runtime features belong in the narrowest existing boundary under `src/arka/`
and should be exposed through `dispatch.py` plus a symbolic route when
user-facing.

## Local state (never commit)

Editable checkouts store writable runtime state in **`<repo>/.arka/`**
(`config_dir()`). Installed copies use `~/.config/arka/` (or legacy
`~/.config/fish/` when that tree already holds `.env`).

| Location | Examples |
|----------|----------|
| `<repo>/.arka/` or `~/.config/arka/` | `.env`, `mcp.json`, `personalize.json`, `email_contacts.json`, `email_draft_history.json`, `logs/mcp.jsonl`, `message-sessions/`, `personas/` |
| `~/.cache/arka/` | Transient caches (`CACHE_DIR` override supported) |
| `~/arka-generated/` | Tabular/data exports from `view_data` / `generate_data` (`DATA_OUTPUT_DIR` override supported) |
| `<repo>/.arka-index` | Local repo index for `repo_context` (regenerated) |

`arka doctor` and `ensure_layout()` call `migrate_scattered_state()` to move
historical repo-root artifacts (`mcp.json`, `platform.json`, `logs/`, email
history, etc.) into `.arka/`. After migration, **stale duplicates at the repo
root are safe to delete** when the canonical copy already lives under `.arka/`.

Secrets belong in config `.env` only — never commit `.env`, `your-secret-here`
placeholders, or tool credential caches (e.g. `.local/state/gh/`).

## Regeneratable demo artifacts

`recordings/_demo_build/` and per-run folders under `recordings/live-demo-ui/`
are ffmpeg/terminal capture **build outputs**. They are gitignored; regenerate
with the scripts in `recordings/` when updating demo media.

## What not to put in the repo root

Avoid dropping these at the checkout root — they belong under `.arka/`,
`~/arka-generated/`, or `/tmp`:

- `email_draft_history.json`, `email_contacts.json`
- `logs/mcp.jsonl`
- Ad-hoc `*-bug.md` tickets from local QA
- Empty legacy folders named `agent/`, `llm/`, `stock/`, or `personas/` (modules
  live under `src/arka/`)
