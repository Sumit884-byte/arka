# Fish Shell Configuration (Arka)

A modern, AI-powered Fish shell setup with **Arka** — a voice-capable natural-language agent that routes requests to 70+ skills, deep web search, PDF RAG, and system automation.

> [!TIP]
> **Lightweight & secure**: Commands run locally. LLM calls use Gemini, Groq, or Ollama APIs — no Docker required for daily use (PrivateGPT + Qdrant only for PDF ingest).

## Quick start

### Cross-platform (macOS, Windows, Linux)

Install Arka as a Python package — works on any OS:

```bash
git clone https://github.com/Sumit884-byte/arka.git
cd arka
./scripts/refetch.sh --install   # pull + sync bundle + pip install
cp .env.example ~/.config/arka/.env   # add API keys
arka doctor
arka ask "what is Rust?"
```

Already cloned on another machine — refresh from GitHub:

```bash
cd arka
arka refetch --install
# or: ./scripts/refetch.sh --install
```

```bash
# PyPI / pipx (no git clone)
pipx install "arka-agent[chat]"
arka setup
arka doctor
```

| Platform | Mode |
|----------|------|
| **Linux + fish** | Full 70+ skills via `config.fish` (voice, system, media, …) |
| **macOS / Windows** | Portable Python skills: chat, web answers, passwords, calc, weather |
| **Linux without fish** | Same portable mode as macOS/Windows |

Config locations (when not using `~/.config/fish`):

| OS | Config | Cache |
|----|--------|-------|
| Linux | `~/.config/arka/` | `~/.cache/arka/` |
| macOS | `~/Library/Application Support/arka/` | `~/Library/Caches/arka/` |
| Windows | `%APPDATA%\arka\` | `%LOCALAPPDATA%\arka\` |

Override with `ARKA_HOME`, `ARKA_CONFIG_DIR`, or `ARKA_CACHE_DIR`.

### Fish shell (Linux — full agent)

```fish
# Reload config
exec fish

# Natural language (same as `agent`)
arka "what's the weather"
arka "ask Profile.pdf about main skills"
arka facing hair loss

# List skills
arka help
agent_route "summarize ENGLSH-2 weeks 1-3"   # preview routing, no run
```

## Arka — voice & NL agent

| Command | Description |
|---------|-------------|
| `arka <request>` | Route NL to the best skill or shell command |
| `agent <request>` | Same router (alias) |
| `agent_route <q>` | Preview routing without executing |
| `arka start` / `arka stop` | Remote server + wake listener |
| `arka listen` | Wake-word listener ("hey arka, …") |
| `arka speak-lang hi-IN` | Voice language (Sarvam / Edge TTS) |
| `arka usage report` | App + website screen time |

Voice flow: say **"hey arka, …"** → STT → skill router → optional TTS reply (`AGENT_SPEAK=1` default).

### Chat & web answers (`arka_chat.py`)

Intent routing, deep scrape RAG, location, weather, and calc (see `arka_chat.py`).

| Skill | Example |
|-------|---------|
| `web_answer [--deep] <q>` | Auto deep search when needed; session memory |
| `deep_web_answer <q>` | DDG → scrape pages → LLM synthesis |
| `calc <expr>` | SymPy + explanation (`integrate sin(x) dx`) |
| `hyperlocal_weather [q]` | Open-Meteo + IP geolocation |
| `set_location [city\|PIN]` | Ground search queries locally |
| `nearby_places [city]` | Offline POI map (OSM Overpass) |
| `map_download <city>` | Cache city map to `~/.cache/fish-agent/maps/` |
| `error_helper <text>` | Explain tracebacks / fix steps |
| `chat_reset` | Clear chat session + location context |
| `deep_queue add\|list\|run\|results` | Background deep-search queue |

Forced web search: prefix with `/` — e.g. `arka "/who won IPL 2025"`.

Answers are tagged `[FROM SEARCH]` or `[FROM MEMORY]` (stripped for TTS).

### PDF RAG (`arka_pdf_rag.py` + PrivateGPT)

| Skill | Example |
|-------|---------|
| `pdf_ingest <file.pdf>` | Ingest (auto-starts PrivateGPT + Qdrant Docker) |
| `pdf_list` | List ingested documents |
| `pdf_ask [--doc DOC] <q>` | Q&A or summarize one or all PDFs |

NL examples:

```fish
arka "ask Profile.pdf about main skills"
arka "summarize ENGLSH-2 weeks 1 to 3"
```

### Other notable skills

**Media:** `play_spotify`, `play_youtube`, `play_movie`, `play_song`  
**System:** `weather`, `system_monitor`, `disk_breakdown`, `app_usage`, `screenshot`  
**Dev:** `install_uv`, `install_app`, `git_summary`, `lint_python`, `open_project`  
**Web:** `web_essay`, `search_web`, `browse_web`  
**Advisory:** `agent_ask` — gathers Linux context via shell, then answers  

Full list: `arka help` or `skills`.

---

## Classic AI helpers

Built-in wrappers for Gemini, Groq, and Ollama (used by Arka and standalone):

| Command | Purpose |
|---------|---------|
| `ask <prompt>` | Get a Linux command for a task (copies to clipboard) |
| `talk <prompt>` | General chat |
| `fix` | Fix last failed command via AI |
| `ai <prompt>` | Shortcut for local Ollama |
| `ai-models` | List providers and models |

```fish
ask "find files larger than 100MB"
ask -p groq "check port 8080"
talk "explain fish universal variables"
fix   # after a failed command
```

---

## Python modules

| File | Role |
|------|------|
| `arka_chat.py` | Deep web RAG, intent, weather, maps, calc, session |
| `arka_pdf_rag.py` | PrivateGPT ingest / ask / list |
| `arka_usage.py` | GNOME app + browser usage tracking |
| `arka_disk.py` | Disk breakdown by file type |
| `arka_wake.py` | Wake-word listener (Vosk) |
| `arka_remote_server.py` | Phone STT/TTS → PC agent |
| `web_answer.py` | DuckDuckGo instant-answer snippets |
| `sarvam_speak.py` / `edge_speak.py` | TTS backends |
| `sarvam_stt.py` | STT via Sarvam Saaras v3 (command after wake) |

Cache & logs: `~/.cache/fish-agent/`

---

## Setup

### Package install (all platforms)

```bash
git clone <your-repo-url> arka && cd arka
python3 scripts/sync_bundled.py   # before building a wheel
pip install -e ".[chat]"            # editable dev install
arka setup
```

Publish / CI wheel:

```bash
python3 scripts/sync_bundled.py
pip wheel . -w dist/
```

Optional extras: `[chat]`, `[voice]`, `[pdf]`, `[all]`.

### Fish + Linux (full skills)

### Prerequisites

**Shell & CLI:** `fish`, `curl`, `jq`, `eza`, `batcat`, `zoxide`, `fzf`, `ripgrep`, `python3`

**Chat engine (optional but recommended):**

```bash
pip install --break-system-packages -r ~/.config/fish/arka_chat_requirements.txt
# ddgs trafilatura beautifulsoup4 sympy geopy
```

**PDF RAG (optional):** [PrivateGPT](https://github.com/zylon-ai/private-gpt) at `~/Projects/private-gpt`, Docker for Qdrant (`arka-qdrant` on port 6333).

### Environment (`.env`)

Create `~/.config/fish/.env`:

```env
# LLM (at least one)
GEMINI_API_KEY=...
GROQ_API_KEY=...
OLLAMA_HOST=127.0.0.1:11434

# Prefer faster routing when Gemini quota is low
AI_PREFERRED_PROVIDER=groq
AI_PREFERRED_MODEL=llama-3.3-70b-versatile

# Arka
AGENT_NAME=arka
AGENT_SPEAK=1
ARKA_SPEAK_LANG=en-IN

# PDF RAG
ARKA_PDF_RAG_URL=http://127.0.0.1:8080
ARKA_PRIVATEGPT_HOME=~/Projects/private-gpt
ARKA_PDF_RAG_AUTO_START=1

# Usage tracking (autostart on login)
ARKA_USAGE_TRACK=1
ARKA_WEB_TRACK=1
```

### Layout

```
~/.config/fish/
├── config.fish          # Main entry (~8000 lines: skills, routing, Arka)
├── .env                 # Secrets & preferences (not committed)
├── arka_chat.py         # Chat / deep web engine
├── arka_pdf_rag.py      # PDF RAG wrapper
├── arka_chat_requirements.txt
├── privategpt/
│   └── settings.override.yaml
└── functions/           # Extra fish functions (e.g. i → uv pip install)
```

---

## Usage examples

### Natural language

```fish
arka install torch for cpu
arka "how much disk is videos taking"
arka "play bohemian rhapsody on spotify"
arka "is my cpu too outdated for gaming?"    # → agent_ask
arka "where is Tokyo"                        # → web_answer
arka facing hair loss                        # → web_answer + session
```

### PDF

```fish
pdf_ingest ~/Documents/Profile.pdf
pdf_ask --doc "ENGLSH-2 W1-3.pdf" "summarize weeks 1 to 3"
pdf_list
```

### Chat / search

```fish
web_answer --deep "latest news on AI regulation"
calc "integrate sin(x) dx"
hyperlocal_weather
deep_queue add "who won the last IPL final"
deep_queue run && deep_queue results
chat_reset
```

### Voice

**Wake word (lightweight):** `arka listen` / `arka debug` — Vosk + optional Groq Whisper  
**Full voice agent (HF):** Hugging Face [speech-to-speech](https://github.com/huggingface/speech-to-speech) with VAD + Whisper STT + Pocket TTS, routed to Arka skills:

```fish
arka voice install          # first time: venv + deps (~5–10 min)
arka voice start            # talk naturally; no "hey arka" needed
arka voice stop
arka voice status
tail -f ~/.cache/fish-agent/arka_voice_hf.log
```

Repo: `~/.config/fish/speech-to-speech`  
Bridge: voice LLM calls → `agent` (all skills). Optional `.env`:

```env
ARKA_HF_STT_MODEL=distil-whisper/distil-small.en
ARKA_HF_TTS_VOICE=jean          # pocket TTS preset
ARKA_HF_BRIDGE_PORT=8787
```

```fish
arka start                    # remote + wake listener
arka listen debug             # live STT log
# Say: "hey arka, what's the weather"
AGENT_SPEAK=0 arka "timer 5m" # text-only reply
```

---

## Modern CLI aliases

- **`ls`, `ll`, `la`, `lt`** — `eza`
- **`cat`, `bat`** — `batcat`
- **`z`** — `zoxide`
- **`i`** — `uv pip install` (⚠️ only use as a command, not NL — Arka routes chat away from this)

## Project shortcuts

`vgen`, `gitube`, `iaf-wiki`, `gitsearch` — quick `cd` / open helpers defined in `config.fish`.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Could not generate an answer` | Set `AI_PREFERRED_PROVIDER=groq` or run `ollama serve` |
| Gemini 429 / slow responses | Use Groq as preferred provider |
| `uv pip install am` on random text | Fixed — use `arka`, not raw shell, for NL |
| PDF ask fails | `arka pdf status`; ensure Qdrant Docker is up |
| Deep search empty | `pip install ddgs trafilatura beautifulsoup4` |
| Map download timeout | Retry `map_download Kolkata` later (Overpass API) |
| Speech recognition poor | Set `ARKA_STT=sarvam` + `SARVAM_API_KEY` (Saaras v3); or `ARKA_STT=auto` + `GROQ_API_KEY`; `ARKA_VOSK_TIER=best`; `arka listen models` |
| Listener crashes (no vosk) | `~/.config/fish/venv-arka/bin/python3 ~/.config/fish/arka_wake.py --check` then `arka debug` |
| Wrong microphone | `pactl list sources short` → set `ARKA_MIC_DEVICE=<source name>` in `.env` |

Logs: `~/.cache/fish-agent/*.log`
