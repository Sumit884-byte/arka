# Arka

**Your terminal, upgraded.** Route plain English to **70+ local skills** — deterministic offline routing, voice, 24-provider LLM failover, and security gates on by default.

[![License: GPL v2](https://img.shields.io/badge/License-GPL%20v2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/arka-agent.svg)](https://pypi.org/project/arka-agent/)
[![Docs](https://img.shields.io/badge/docs-Mintlify-6366F1)](https://arka-agent.mintlify.site)

**Documentation:** [arka-agent.mintlify.site](https://arka-agent.mintlify.site)

## Why Arka?

- **Deterministic routing:** 120+ symbolic rules handle most requests with zero LLM tokens before any model is called.
- **Extensible:** Add third-party skills via `skill.json` plugins — no fork required.
- **Secure by default:** Prompt-injection checks, risky-action prompts, and hard blocks on destructive shell patterns.
- **Local-first:** Skills run on your machine; LLM calls failover across Gemini, Groq, Ollama, and 20+ other providers.

## Supported platforms

| Platform | Support |
| --- | --- |
| **macOS** | Full support — recommended for daily use |
| **Linux** | Full support |
| **Windows** | Python CLI and `arka` subcommands work; the full 70+ skill router needs [fish shell](https://fishshell.com) (`scoop install fish` or `winget install fishshell`). Without fish, Arka runs in **portable** mode with Python fallbacks. Some fish-oriented skills target macOS/Linux. |

**Requirements:** Python **3.11+**. Optional: fish shell for natural-language routing and voice integration.

Config paths: `~/.config/arka/` (Linux), `~/Library/Application Support/arka/` (macOS), `%APPDATA%\arka\` (Windows).

## Installation

PyPI package name is **`arka-agent`** — published at [pypi.org/project/arka-agent](https://pypi.org/project/arka-agent/).

**Recommended (standalone, no clone, no build):**

```bash
pipx install "arka-agent[chat]"
arka setup
arka doctor
```

Or with pip in a venv:

```bash
python3 -m pip install "arka-agent[chat]"
arka setup
arka doctor
```

**GitHub fallback** (if you need the latest commit before the next PyPI release):

```bash
pipx install "arka-agent[chat] @ git+https://github.com/Sumit884-byte/arka.git"
arka setup
arka doctor
```

**From a git clone** (best for contributors or tracking `main`):

```bash
git clone https://github.com/Sumit884-byte/arka.git
cd arka
./scripts/refetch.sh --install
arka setup
arka doctor
```

**Configure API keys** (at least one cloud key or local Ollama):

```bash
cp .env.example ~/.config/arka/.env   # macOS/Linux; see Supported platforms for Windows path
```

Add a free-tier key from [Google AI Studio](https://aistudio.google.com/apikey) or [Groq Console](https://console.groq.com/keys), then run `arka free tier setup` for recommended `.env` settings.

**Optional one-liners:**

```bash
brew install fish                    # macOS — unlocks full skill router
arka mcp doctor && arka mcp install   # verify MCP server; print Cursor snippet
```

See the [Quickstart guide](https://arka-agent.mintlify.site/quickstart) and [MCP integration](https://arka-agent.mintlify.site/guides/mcp) for fish setup, Cursor merge steps, and optional extras (`[voice]`, `[pdf]`, `[all]`).

## Try Arka without building from source

There is no hosted demo instance or shared test account. The fastest path to evaluate Arka:

1. **Browse the live docs** — [arka-agent.mintlify.site](https://arka-agent.mintlify.site) (skills catalog, routing concepts, CLI reference).
2. **Install in one command** — use the pip/pipx git install above (no manual build step).
3. **Use free-tier LLM keys** — Gemini and Groq both offer free tiers; Ollama is local and costs nothing:

   ```bash
   arka free tier setup
   arka doctor
   ```

4. **Run sample commands** that exercise routing and LLM failover:

   ```bash
   arka ask "what is Rust?"
   arka "convert 100 USD to INR"
   arka council "should I learn Rust?"
   arka quiz python
   arka coding-tui .
   arka repo_health scan
   ```

   Inside the coding TUI, `/test scripts` runs verification scripts discovered under `scripts/` (no hardcoded list — Arka inspects filenames, docstrings, argparse, and `test_*` functions). Use `/test` for pytest and `repo_health scan` to see why each script matched.

5. **Try MCP in Cursor** — after install, `arka mcp doctor` then `arka mcp install`; merge the printed snippet into **Cursor Settings → MCP** and restart Cursor.

Full walkthrough: [Quickstart](https://arka-agent.mintlify.site/quickstart) · [Free credits guide](https://arka-agent.mintlify.site/guides/free-credits)

## Quick Start

Get to a working answer in under a minute:

```bash
arka doctor                              # verify install + keys
arka ask "what is Rust?"                 # web + AI answer
arka "convert 100 USD to INR"            # natural language routing
arka council "should I learn Rust?"      # multi-persona deliberation
```

Voice (optional):

```bash
arka listen    # then say: "hey arka, what's the weather"
```

More guides — skills, stocks, PDF RAG, Google Workspace, goal agent, testing — live on the [documentation site](https://arka-agent.mintlify.site).

## Contributing

We welcome contributions of all sizes! Please read our [Contribution Guidelines](CONTRIBUTING.md) to get started with the local development workflow.

Look for the **good first issue** label on [GitHub Issues](https://github.com/Sumit884-byte/arka/issues?q=label%3A%22good+first+issue%22) to find a welcoming entry point.

## License

Distributed under the **GNU General Public License v2.0**. See [LICENSE](LICENSE) for more information.
