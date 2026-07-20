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

## Publishing to PyPI

The package name on PyPI is **`arka-agent`**. Publishing is handled by GitHub Actions (`.github/workflows/publish.yml`) on pushed tags matching `v*`, or manually via `scripts/publish_pypi.sh`.

### First-time PyPI setup (maintainers)

1. Register the project on [pypi.org](https://pypi.org/) (or claim `arka-agent` if reserved).
2. Configure **trusted publishing** on the PyPI project (after the first upload):
   - Open [arka-agent → Publishing](https://pypi.org/manage/project/arka-agent/settings/publishing/)
   - **Add a new publisher** → **GitHub**
   - Owner: `Sumit884-byte`, repository name: `arka`, workflow name: `publish.yml`, environment name: `pypi`
   - (Use *Pending publishers* under account settings only before the project exists on PyPI.)
3. In GitHub: Settings → Environments → create **`pypi`** (no secrets required when using trusted publishing).

### Release checklist

1. Confirm the version is not already on PyPI: `pip index versions arka-agent`
2. Bump `version` in `pyproject.toml` and `__version__` in `src/arka/__init__.py`
3. Merge the version bump PR, then tag and push:

```bash
git checkout main && git pull origin main
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

4. Watch the **Publish** workflow on GitHub Actions.
5. Verify: `pipx install "arka-agent[chat]"` and `arka doctor`

### Manual publish (fallback)

```bash
./scripts/publish_pypi.sh          # build + twine check (dry run)
export PYPI_TOKEN='pypi-...'       # or UV_PUBLISH_TOKEN with uv installed
./scripts/publish_pypi.sh --upload
```

## Questions

- **Docs:** [arka-agent.mintlify.site](https://arka-agent.mintlify.site)
- **Bugs & features:** [GitHub Issues](https://github.com/Sumit884-byte/arka/issues)
