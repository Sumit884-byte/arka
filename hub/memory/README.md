# Arka Hub Memory

Exports from Arka unified memory for cross-agent context.

## Files

| File | Format | Use |
| ---- | ------ | --- |
| `summary.json` | JSON | Facts, session index, memory status |
| `context.md` | Markdown | Human-readable bundle for agents that read files |
| `sessions_index.json` | JSON | Recent channel sessions |
| `skills_manifest.json` | JSON | Copy of skills manifest for memory-aware agents |

## Per-agent loading

| Agent | Recommended |
| ----- | ----------- |
| Claude Code / Cursor | `ARKA_CONTEXT_MD` or read `context.md` at session start |
| OpenClaw | Sync `MEMORY.md` tail via `agent_hub sync --unify`; read `context.md` |
| Hermes | `sessions_index.json` for channel continuity |
| Codex / Copilot | `summary.json` facts + `ARKA_SKILLS_MANIFEST` |

## Import back into Arka

```bash
arka agent_hub import-memory path/to/export.json
arka agent_hub import-memory path/to/notes.md
```

Imported text passes through Arka security gates before writing to unified memory.

## Scoped export (edge / ClawBox)

Set on Jetson or always-on devices to limit what the hub exports:

```env
ARKA_MEMORY_TRUST_MAX=team
ARKA_HUB_MEMORY_SCOPE=team:clawbox
```

Use `agent_hub sync` (export-only) on edge — avoid `sync --unify` unless you intend to merge MCP into agent configs.
