#!/usr/bin/env bash
# Build the React desktop UI into src/arka/web/dist/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/web"
if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found — install Node.js (https://nodejs.org) or use Homebrew: brew install node" >&2
  exit 1
fi
npm install
npm run build
echo "Built → $ROOT/src/arka/web/dist/"
