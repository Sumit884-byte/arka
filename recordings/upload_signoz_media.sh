#!/usr/bin/env bash
# Upload SigNoz hackathon screenshots + demo videos to a public GitHub Release.
# After upload, paste URLs into signoz/BLOG.md (see MEDIA_BASE below).
set -euo pipefail

REPO="${ARKA_MEDIA_REPO:-sumitmishra884byte-cpu/arka}"
TAG="${ARKA_MEDIA_TAG:-signoz-hackathon-media}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MEDIA_BASE="https://github.com/${REPO}/releases/download/${TAG}"

MEDIA_FILES=(
  "$ROOT/recordings/signoz-screenshots/traces-explorer.png"
  "$ROOT/recordings/signoz-screenshots/services-metrics.png"
  # logs-explorer omitted from blog until crisp Playwright capture (SIGNOZ auth). Set ARKA_UPLOAD_LOGS=1 to include.
  "$ROOT/recordings/signoz-screenshots/home-dashboard.png"
  "$ROOT/recordings/signoz-screenshots/dashboard-observability-long.png"
  "$ROOT/recordings/arka-signoz-hackathon-demo.mp4"
  "$ROOT/recordings/arka-demo-submission.mp4"
)

if [[ "${ARKA_UPLOAD_LOGS:-}" == "1" ]]; then
  MEDIA_FILES+=("$ROOT/recordings/signoz-screenshots/logs-explorer.png")
fi

# Gitignored locally (signoz/*.md except README) — published on the release for judges / Devpost
JUDGE_PACK_FILES=(
  "$ROOT/signoz/README.md"
  "$ROOT/signoz/BLOG.md"
  "$ROOT/signoz/FOUR_PILLARS.md"
  "$ROOT/signoz/MCP_INTEGRATION.md"
  "$ROOT/signoz/CURSOR_AGENT_SKILLS.md"
  "$ROOT/signoz/AWS_PRIZE.md"
)

UPLOAD_FILES=("${MEDIA_FILES[@]}" "${JUDGE_PACK_FILES[@]}")
missing=()
for f in "${UPLOAD_FILES[@]}"; do
  [[ -f "$f" ]] || missing+=("$f")
done
if ((${#missing[@]})); then
  echo "Missing files:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  echo >&2
  echo "  Media: python3 recordings/signoz-screenshots/capture_signoz_ui.py --no-dashboard" >&2
  echo "         python3 recordings/build_signoz_demo_video.py" >&2
  echo "  Judge pack: ensure signoz/*.md exist (FOUR_PILLARS, MCP_INTEGRATION, …)" >&2
  exit 1
fi

if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "Run: gh auth login" >&2
  exit 1
fi

if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  echo "Release $TAG exists — uploading assets..."
  gh release upload "$TAG" --repo "$REPO" --clobber "${UPLOAD_FILES[@]}"
else
  echo "Creating release $TAG on $REPO..."
  gh release create "$TAG" \
    --repo "$REPO" \
    --title "SigNoz hackathon blog & demo media" \
    --notes "Public PNG/MP4 demo media plus judge-pack markdown (FOUR_PILLARS, MCP_INTEGRATION, …) for Devpost and AWS Builder Center." \
    "${UPLOAD_FILES[@]}"
fi

echo
echo "=== Public URLs (copy into signoz/README.md / signoz/BLOG.md) ==="
echo "MEDIA_BASE=${MEDIA_BASE}"
echo
echo "--- Media ---"
for f in "${MEDIA_FILES[@]}"; do
  echo "${MEDIA_BASE}/$(basename "$f")"
done
echo
echo "--- Judge pack (markdown) ---"
for f in "${JUDGE_PACK_FILES[@]}"; do
  echo "${MEDIA_BASE}/$(basename "$f")"
done
