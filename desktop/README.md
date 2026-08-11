# Arka Desktop (Tauri)

Native desktop shell for **local Arka** — chat, skills, and status in a window. The app auto-starts:

1. **`arka serve`** — agent backend on `http://127.0.0.1:8765`
2. **`bridge.py`** — API + UI proxy on `http://127.0.0.1:8766`

All skills run on your machine. Nothing is hosted in the cloud.

## Prerequisites

1. **Arka installed** (editable checkout or pip):

```bash
pipx install "arka-agent[chat]"
# or from this repo:
pip install -e ".[chat]"
```

2. **Config** — `~/.config/arka/.env` with at least:

```env
REMOTE_TOKEN=your-secret-token-here
```

Generate any random string; the desktop bridge reads it automatically.

3. **Rust** (for Tauri): [rustup.rs](https://rustup.rs)

4. **Node.js** 18+

## Quick start (development)

```bash
cd desktop
npm install
npm install --prefix ui
npm run dev
```

This opens the Tauri window, starts `arka serve` + bridge, and loads the Vite UI (dev) or built UI (release).

## Production build

```bash
cd desktop
npm install
npm install --prefix ui
npm run build
```

Output: `src-tauri/target/release/bundle/` (`.app` on macOS, `.dmg`, etc.)

## Manual backend (without Tauri)

Useful for debugging:

```bash
# Terminal 1
arka serve

# Terminal 2
cd desktop && python3 bridge.py

# Terminal 3 (dev UI)
cd desktop/ui && npm install && npm run dev
```

Open [http://localhost:5173](http://localhost:5173) (dev) or [http://127.0.0.1:8766](http://127.0.0.1:8766) (built UI served by bridge).

## Environment

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `REMOTE_TOKEN` | — | Auth for `/v1/agent` (required) |
| `ARKA_PYTHON` | `python3` | Python executable |
| `ARKA_REPO` | parent of `desktop/` | Repo root for `PYTHONPATH` |
| `ARKA_BRIDGE_PORT` | `8766` | Bridge port |
| `ARKA_BACKEND_URL` | `http://127.0.0.1:8765` | Remote server URL |

## Project layout

```
desktop/
  bridge.py          # Local HTTP bridge (API + static UI)
  ui/                # React dashboard (Vite)
  src-tauri/         # Tauri shell — spawns Python backends
  package.json       # npm run dev | build
```

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| Chat returns 401 | Set `REMOTE_TOKEN` in `~/.config/arka/.env` |
| Backend timeout on launch | Run `arka doctor`; ensure `python3 -m arka.integrations.remote_server serve` works |
| Blank window in release build | Run `npm run build --prefix ui` before `npm run build` |
| Port in use | `lsof -i :8765` / `:8766` and stop old processes |

## Privacy

Same as CLI Arka: skills execute locally, keys stay in `~/.config/arka/`, LLM calls use only providers you configure.
