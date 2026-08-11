#!/usr/bin/env bash
set -e

# ==============================================================================
# Arka One-Step Cloud Deployment Script
# ==============================================================================
# Deploys Arka to any cloud-hosted machine (Linux VM, VPS, Docker host).
# Enforces ARKA_HOSTED_MODE=1, restricting desktop/device skills while
# enabling all cloud, repo, CI, API, and developer tools.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

CHECK_ONLY=0
PORT="${PORT:-8765}"
TOKEN="${REMOTE_TOKEN:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      CHECK_ONLY=1
      shift
      ;;
    --token)
      TOKEN="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "========================================================"
echo "         Arka One-Step Cloud Deployment Helper          "
echo "========================================================"

# Check prerequisites
HAS_DOCKER=0
HAS_COMPOSE=0
HAS_PYTHON=0

if command -v docker >/dev/null 2>&1; then
  HAS_DOCKER=1
fi

if docker compose version >/dev/null 2>&1; then
  HAS_COMPOSE=1
elif command -v docker-compose >/dev/null 2>&1; then
  HAS_COMPOSE=1
fi

if command -v python3 >/dev/null 2>&1; then
  HAS_PYTHON=1
fi

if [ "$HAS_DOCKER" -eq 0 ] && [ "$HAS_PYTHON" -eq 0 ]; then
  echo "Error: Neither Docker nor Python 3 was found on this system."
  echo "Please install Docker or Python 3 to run Arka in cloud mode."
  exit 1
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "Prerequisites Check:"
  echo "  Docker:         $([ $HAS_DOCKER -eq 1 ] && echo 'YES' || echo 'NO')"
  echo "  Docker Compose: $([ $HAS_COMPOSE -eq 1 ] && echo 'YES' || echo 'NO')"
  echo "  Python 3:       $([ $HAS_PYTHON -eq 1 ] && echo 'YES' || echo 'NO')"
  echo "Cloud Mode Enforcement:"
  echo "  ARKA_HOSTED_MODE=1 (Desktop/GUI/Audio skills disabled, Cloud/Repo/API skills enabled)"
  exit 0
fi

if [ -z "$TOKEN" ]; then
  if [ "$HAS_PYTHON" -eq 1 ]; then
    TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
  else
    TOKEN=$(openssl rand -hex 16 2>/dev/null || echo "arka_cloud_$(date +%s)")
  fi
fi

export ARKA_HOSTED_MODE=1
export ARKA_REMOTE_PROFILE=coding
export ARKA_MCP_ENABLE_PERSONAL_SKILLS=0
export REMOTE_HOST=0.0.0.0
export REMOTE_TOKEN="$TOKEN"
export PORT="$PORT"

echo ""
echo "Deploying Arka on Cloud Machine..."
echo "  Mode:                   HOSTED (Cloud)"
echo "  Port:                   $PORT"
echo "  Token:                  $TOKEN"
echo "  Hosted Skill Guard:     ACTIVE (Personal/GUI/Desktop skills disabled)"
echo ""

if [ "$HAS_COMPOSE" -eq 1 ] && [ -f "$ROOT_DIR/docker-compose.yml" ]; then
  echo "-> Launching with Docker Compose..."
  cd "$ROOT_DIR"
  docker compose up -d --build
  echo "✓ Arka container started via Docker Compose."
elif [ "$HAS_DOCKER" -eq 1 ] && [ -f "$ROOT_DIR/Dockerfile" ]; then
  echo "-> Building and running Docker container..."
  cd "$ROOT_DIR"
  docker build -t arka-cloud:latest .
  docker stop arka-cloud-server 2>/dev/null || true
  docker rm arka-cloud-server 2>/dev/null || true
  docker run -d \
    --name arka-cloud-server \
    --restart unless-stopped \
    -p "$PORT:8765" \
    -e ARKA_HOSTED_MODE=1 \
    -e ARKA_REMOTE_PROFILE=coding \
    -e ARKA_MCP_ENABLE_PERSONAL_SKILLS=0 \
    -e REMOTE_HOST=0.0.0.0 \
    -e REMOTE_TOKEN="$TOKEN" \
    arka-cloud:latest
  echo "✓ Arka Docker container started."
else
  echo "-> Starting directly with Python server..."
  cd "$ROOT_DIR"
  if [ -d "venv" ]; then
    source venv/bin/activate
  elif [ -d ".venv" ]; then
    source .venv/bin/activate
  fi
  python3 -m arka.integrations.remote_server serve &
  echo "✓ Arka server launched in background."
fi

echo ""
echo "========================================================"
echo " Deployment Complete!"
echo " Health Check:  http://0.0.0.0:$PORT/v1/health"
echo " Agent API:     http://0.0.0.0:$PORT/v1/agent"
echo " Authorization: Bearer $TOKEN"
echo "========================================================"
