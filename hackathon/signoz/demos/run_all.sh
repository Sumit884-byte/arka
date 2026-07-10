#!/usr/bin/env bash
# Run all three SigNoz hackathon demo scenarios.
# Prerequisites: OTEL_TRACES_ENABLED=1, SigNoz on :4318 (arka signoz setup -y)
set -euo pipefail
cd "$(dirname "$0")/../../.."

SYNTH=""
if [[ "${1:-}" == "--synthetic" ]]; then
  SYNTH="--synthetic"
  shift
fi

echo "=== Scenario 1: vLLM vs Cloud Latency ==="
python3 -m arka.telemetry.signoz_demo inference $SYNTH "$@"

echo ""
echo "=== Scenario 2: RAG & Supermemory Cascade ==="
python3 -m arka.telemetry.signoz_demo rag $SYNTH "$@"

echo ""
echo "=== Scenario 3: Semantic Router Split ==="
python3 -m arka.telemetry.signoz_demo router $SYNTH "$@"

echo ""
echo "Done. Open ${SIGNOZ_UI_URL:-http://localhost:8080}/traces and filter service.name = arka"
