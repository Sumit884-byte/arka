# Google DESIGN.md guide

Arka bundles a curated summary of Google's open **DESIGN.md** format so agents
apply consistent visual identity when building UI — alongside the
[frontend content guide](./frontend-content-guide.md) for user-facing copy.

**Upstream spec:** https://github.com/google-labs-code/design.md

---

## What it does

- Auto-injects for frontend/UI goals, coding-tui plans, and `frontend_loop` reviews
- Prefers a project-root `DESIGN.md` when one exists
- Falls back to the bundled `google-design.md` (format rules + agent workflow)
- Exposes MCP / CLI aliases: `google-design`, `design.md`, `DESIGN.md`

---

## Environment

In `~/.config/arka/.env`:

```bash
GOOGLE_DESIGN_GUIDE=1                 # default on
GOOGLE_DESIGN_GUIDE_MODE=auto         # auto | always | off
FRONTEND_CONTENT_GUIDE=1              # copy policy (paired by default)
```

Set either guide to `0` to disable it independently.

---

## CLI

```bash
arka md_doc read google-design
arka md_doc read design.md            # project DESIGN.md if present
arka md_doc context google-design
```

Natural language (symbolic routing):

```text
follow google design.md
use design.md for this UI
```

---

## MCP

`arka_markdown` accepts:

| Alias | Resolves to |
|-------|-------------|
| `google-design` | project `DESIGN.md` or bundled guide |
| `design.md` | same |
| `frontend-content-guide` | bundled copy policy |

Example: `arka_markdown` with `action=read`, `path=google-design`.

---

## Project DESIGN.md

Commit a project-specific `DESIGN.md` at the repo root (YAML tokens + markdown
sections). Arka will prefer it over the bundled summary. Validate with:

```bash
npx @google/design.md lint DESIGN.md
```

See the [official spec](https://github.com/google-labs-code/design.md) for the
full token schema, section order, and CLI reference.
