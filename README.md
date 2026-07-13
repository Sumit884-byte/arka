# Arka

A cross-platform, **extensible** AI agent for your terminal. Route plain English to **70+ local skills** — with **deterministic** offline routing, voice, 24-provider LLM failover, and security gates on by default.

[![License: GPL v2](https://img.shields.io/badge/License-GPL%20v2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/arka-agent.svg)](https://pypi.org/project/arka-agent/)

**Documentation:** [arka-agent.mintlify.site](https://arka-agent.mintlify.site)

## Why Arka?

- **Deterministic routing:** 120+ symbolic rules handle most requests with zero LLM tokens before any model is called.
- **Extensible:** Add third-party skills via `skill.json` plugins — no fork required.
- **Secure by default:** Prompt-injection checks, risky-action prompts, and hard blocks on destructive shell patterns.
- **Local-first:** Skills run on your machine; LLM calls failover across Gemini, Groq, Ollama, and 20+ other providers.

## Prerequisites

Requires **Python `3.11` or higher**. Optional: [fish shell](https://fishshell.com) for the full skill router and voice integration.

## Installation

```bash
pipx install "arka-agent[chat]"  # PyPI package coming soon; use git install below if pip 404s
arka setup
```

Or from source:

```bash
git clone https://github.com/Sumit884-byte/arka.git
cd arka
./scripts/refetch.sh --install
```

Copy API keys (at least one cloud key or local Ollama):

```bash
cp .env.example ~/.config/arka/.env
```

## Quick Start

Get to a working answer in under a minute:

```bash
arka doctor
arka ask "what is Rust?"
arka "convert 100 USD to INR"
arka council "should I learn Rust?"
```

Voice (optional):

```bash
arka listen    # then say: "hey arka, what's the weather"
```

Full guides — skills, stocks, PDF RAG, Google Workspace, goal agent, testing — live on the [documentation site](https://arka-agent.mintlify.site).

## Contributing

We welcome contributions of all sizes! Please read our [Contribution Guidelines](CONTRIBUTING.md) to get started with the local development workflow.

Look for the **good first issue** label on [GitHub Issues](https://github.com/Sumit884-byte/arka/issues?q=label%3A%22good+first+issue%22) to find a welcoming entry point.

## License

Distributed under the **GNU General Public License v2.0**. See [LICENSE](LICENSE) for more information.
