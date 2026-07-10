# Contribution Guidelines

We welcome contributions of all sizes — bug reports, docs fixes, new skills, and plugin ideas. This project aims to be **welcoming** and **inclusive**; please be respectful in issues and pull requests.

## Prerequisites

- **Python** `3.11` or higher
- **git**
- Optional: [fish shell](https://fishshell.com) for the full 70+ skill router

## Local development

```bash
git clone https://github.com/Sumit884-byte/arka.git
cd arka
python3 scripts/sync_bundled.py
pip install -e ".[chat,dev]"
cp .env.example ~/.config/arka/.env   # add API keys as needed
arka doctor
```

Run tests:

```bash
pytest
```

Refresh after pulling upstream:

```bash
./scripts/refetch.sh --install
```

## Branching

1. Fork the repository and create a branch from `main`.
2. Make focused changes — one feature or fix per pull request.
3. Add or update tests when behavior changes.
4. Open a pull request with a clear description of what and why.

## Good first issues

New to the codebase? Look for the **good first issue** label on [GitHub Issues](https://github.com/Sumit884-byte/arka/issues?q=label%3A%22good+first+issue%22). These are scoped tasks meant to help you learn the router, skills, and test layout without a steep ramp-up.

## Roadmap

High-impact areas we are actively improving:

- Symbolic routing coverage and plugin triggers
- LLM provider failover and per-skill model profiles
- Documentation at [arka-agent.mintlify.site](https://arka-agent.mintlify.site)
- Chart, vision, and Google Workspace integrations

Check open issues and discussions for the latest priorities before starting large work.

By contributing, you agree that your contributions will be licensed under the project's **GPL-2.0** license.

## Questions

- **Docs:** [arka-agent.mintlify.site](https://arka-agent.mintlify.site)
- **Bugs & features:** [GitHub Issues](https://github.com/Sumit884-byte/arka/issues)
