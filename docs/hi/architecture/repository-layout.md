# Repository layout

Arka runtime code को `src/arka/` के अंतर्गत, executable maintenance helpers को
`scripts/` में, tests को `tests/` में, और user-facing documentation को `docs/` में रखता है।

## Source tree (committed)

| Path | उद्देश्य |
|------|---------|
| `src/arka/` | Python package — skills, routing, integrations |
| `src/arka/agent/` | User-facing task workflows |
| `src/arka/core/` | Shared config, security, routing primitives |
| `src/arka/integrations/` | External systems और MCP adapters |
| `src/arka/llm/` | Providers, fallback, model selection |
| `src/arka/routing/` | Symbolic और NL route translation |
| `src/arka/fish/`, `src/arka/bundled/` | Fish runtime और synced distribution assets |
| `bin/` | Legacy CLI shims (installs के लिए `bundled/` में synced) |
| `scripts/` | Maintainer tooling (`sync_bundled.py`, publish, refetch) |
| `tests/` | Pytest suite |
| `docs/` | Mintlify documentation |
| `recordings/` | Curated demo captures (CLI screenshots, terminal transcripts) |
| `examples/` | Sample configs और harnesses |

नए runtime features को `src/arka/` के अंतर्गत सबसे संकीर्ण मौजूदा boundary में रखा जाना चाहिए,
और user-facing होने पर उन्हें `dispatch.py` तथा एक symbolic route के ज़रिए expose किया जाना चाहिए।

## Local state (कभी commit न करें)

Editable checkouts writable runtime state को **`<repo>/.arka/`**
(`config_dir()`) में store करते हैं। Installed copies `~/.config/arka/` का उपयोग करती हैं (या legacy
`~/.config/fish/` का, जब उस tree में पहले से `.env` मौजूद हो)।

| Location | उदाहरण |
|----------|----------|
| `<repo>/.arka/` या `~/.config/arka/` | `.env`, `mcp.json`, `personalize.json`, `email_contacts.json`, `email_draft_history.json`, `logs/mcp.jsonl`, `message-sessions/`, `personas/` |
| `~/.cache/arka/` | अस्थायी caches (`CACHE_DIR` override समर्थित) |
| `~/arka-generated/` | `view_data` / `generate_data` से Tabular/data exports (`DATA_OUTPUT_DIR` override समर्थित) |
| `<repo>/.arka-index` | `repo_context` के लिए local repo index (regenerated) |

`arka doctor` और `ensure_layout()`, `migrate_scattered_state()` को call करते हैं ताकि
पुराने repo-root artifacts (`mcp.json`, `platform.json`, `logs/`, email
history, आदि) को `.arka/` में move किया जा सके। Migration के बाद, जब canonical copy पहले से `.arka/` के अंतर्गत मौजूद हो, तो **repo
root पर stale duplicates को delete करना सुरक्षित है**।

Secrets केवल config `.env` में ही रखें — `.env`, `your-secret-here`
placeholders, या tool credential caches (जैसे `.local/state/gh/`) को कभी commit न करें।

## Regeneratable demo artifacts

`recordings/_demo_build/` और `recordings/live-demo-ui/` के अंतर्गत per-run folders
ffmpeg/terminal capture के **build outputs** हैं। ये gitignored हैं; demo media अपडेट करते समय
`recordings/` में मौजूद scripts से इन्हें regenerate करें।

## Repo root में क्या न रखें

इन्हें checkout root पर न रखें — इनकी जगह `.arka/`,
`~/arka-generated/`, या `/tmp` के अंतर्गत है:

- `email_draft_history.json`, `email_contacts.json`
- `logs/mcp.jsonl`
- Local QA से बने ad-hoc `*-bug.md` tickets
- `agent/`, `llm/`, `stock/`, या `personas/` नाम के खाली legacy folders (modules
  `src/arka/` के अंतर्गत रहते हैं)
