# SigNoz hackathon demo scripts

Runnable scenarios for **Track 01 — AI & Agent Observability** and **Self-hosted Inference**.

## Quick start

```bash
# From repo root — requires SigNoz + OTEL enabled in ~/.config/arka/.env
pip install -e ".[chat,observability]"
arka signoz setup -y          # once: Docker + Foundry + cast
arka signoz demo-scenarios    # all three live demos
```

Use `--synthetic` when API keys or vLLM are unavailable (still produces judge-ready span shapes):

```bash
arka signoz demo-scenarios --synthetic
# or
./hackathon/signoz/demos/run_all.sh --synthetic
```

## Individual scenarios

| Scenario | Command | SigNoz filter |
| -------- | ------- | ------------- |
| vLLM vs cloud latency | `arka signoz demo-inference` | `arka.demo.scenario = vllm-vs-cloud-latency` |
| RAG + Supermemory | `arka signoz demo-rag` | `arka.demo.scenario = rag-supermemory-cascade` |
| Router split | `arka signoz demo-router` | `arka.demo.scenario = semantic-router-split` |

Python module (same behavior):

```bash
python3 -m arka.telemetry.signoz_demo inference
python3 -m arka.telemetry.signoz_demo rag
python3 -m arka.telemetry.signoz_demo router
python3 -m arka.telemetry.signoz_demo all
```

## Environment (live demos)

```bash
# OTLP (required)
OTEL_TRACES_ENABLED=1
SIGNOZ_ENDPOINT=http://localhost:4318

# Scenario 1 — self-hosted inference (pick one or both)
VLLM_HOST=127.0.0.1:8000
VLLM_MODEL=meta-llama/Llama-3.2-3B-Instruct
# or remote GPU:
VLLM_CLOUD_URL=https://your-endpoint.runpod.net/v1
VLLM_CLOUD_API_KEY=...
VLLM_CLOUD_MODEL=meta-llama/Llama-3.2-3B-Instruct

# Cloud comparison provider (default: gemini)
ARKA_DEMO_CLOUD_PROVIDER=gemini
ARKA_DEMO_CLOUD_MODEL=gemini-2.0-flash
GEMINI_API_KEY=...

# Scenario 2 — Supermemory (optional; falls back to local memory)
SUPERMEMORY_API_KEY=...
MEMORY=auto

# Scenario 3 — router (default commands work offline)
ROUTE_MODE=symbolic
ARKA_DEMO_SYMBOLIC_CMD="generate password"
ARKA_DEMO_SEMANTIC_CMD="what shell command shows disk usage on macOS"
```

See [../README.md](../README.md#demo-scenarios) for span hierarchies and judge talking points.
