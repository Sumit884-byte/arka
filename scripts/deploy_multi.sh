#!/usr/bin/env bash
set -e

# ==============================================================================
# Arka Multi-Platform Deployment Script
# ==============================================================================
# Deploys Arka to multiple platforms (Cloud Docker, Railway, Vercel, Netlify,
# Render, Cloudflare, etc.) in a single command execution.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PLATFORMS_ARG="${1:-all}"
PRODUCTION=0
YES=0

for arg in "$@"; do
  case "$arg" in
    --prod|--production)
      PRODUCTION=1
      ;;
    --yes|-y)
      YES=1
      ;;
  esac
done

echo "========================================================"
echo "      Arka Multi-Platform Deployment Controller        "
echo "========================================================"

cd "$ROOT_DIR"

if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

PROD_FLAG=""
if [ "$PRODUCTION" -eq 1 ]; then
  PROD_FLAG="--production"
fi

YES_FLAG=""
if [ "$YES" -eq 1 ]; then
  YES_FLAG="--yes"
fi

if [ "$PLATFORMS_ARG" = "all" ] || [ "$PLATFORMS_ARG" = "--all" ]; then
  echo "Deploying to all detected platforms..."
  python3 -m arka.cli deploy --all $PROD_FLAG $YES_FLAG
else
  echo "Deploying to requested platforms: $PLATFORMS_ARG..."
  python3 -m arka.cli deploy --platforms "$PLATFORMS_ARG" $PROD_FLAG $YES_FLAG
fi
