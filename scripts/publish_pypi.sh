#!/usr/bin/env bash
# Build and upload arka-agent to PyPI.
# Prefers uv when installed; falls back to python -m build + twine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Syncing bundled assets..."
python3 scripts/sync_bundled.py

echo "Cleaning dist/..."
rm -rf dist build
find . -maxdepth 2 -name '*.egg-info' -type d -exec rm -rf {} + 2>/dev/null || true

if command -v uv >/dev/null 2>&1; then
  echo "Building sdist and wheel (uv build --no-sources)..."
  uv build --no-sources
  echo "Validating artifacts..."
  uv tool run twine check dist/*
else
  echo "uv not found — using python -m build..."
  python3 -m pip install -q build twine
  python3 -m build
  python3 -m twine check dist/*
fi

echo "Artifacts:"
ls -lh dist/

if [[ "${1:-}" == "--upload" ]]; then
  if command -v uv >/dev/null 2>&1; then
    if [[ -z "${UV_PUBLISH_TOKEN:-${PYPI_TOKEN:-}}" ]]; then
      echo "Set UV_PUBLISH_TOKEN or PYPI_TOKEN to upload." >&2
      exit 1
    fi
    export UV_PUBLISH_TOKEN="${UV_PUBLISH_TOKEN:-$PYPI_TOKEN}"
    uv publish
  else
    if [[ -z "${PYPI_TOKEN:-}" ]]; then
      echo "Set PYPI_TOKEN to upload (or install uv and use UV_PUBLISH_TOKEN)." >&2
      exit 1
    fi
    python3 -m twine upload --non-interactive dist/*
  fi
else
  cat <<'EOF'

Dry run complete. To publish:

  # Create an API token at https://pypi.org/manage/account/token/
  export UV_PUBLISH_TOKEN='pypi-...'   # uv
  # or
  export PYPI_TOKEN='pypi-...'         # twine fallback

  # Optional: bump version before re-publishing an existing release
  # uv version --bump patch
  # Also update src/arka/__init__.py __version__ to match pyproject.toml

  ./scripts/publish_pypi.sh --upload

Automated publish (recommended after configuring PyPI trusted publishing):

  git tag -a v0.1.0 -m "Release v0.1.0"
  git push origin v0.1.0

Test install from PyPI (after upload):

  pipx install "arka-agent[chat]"
  arka doctor

EOF
fi
