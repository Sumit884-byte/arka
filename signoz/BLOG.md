# See Inside Your Agents: Arka + SigNoz for Track 01

When a model returns 429, a shell step fails, or failover kicks in, you need to see *which* step broke — not just that something failed. We built **Arka + SigNoz** for the [Agents of SigNoz](https://www.wemakedevs.org/hackathons/signoz) hackathon (Track 01 — AI & Agent Observability) to instrument the full agent lifecycle with OpenTelemetry and make every step visible in one trace waterfall.

---

## The problem

AI agents are a black box. They chain LLM calls, invoke tools, hit vector DBs, and make decisions autonomously. When latency spikes, token costs explode, or an agent hallucinates in production, fragmented logs do not tell the end-to-end story.

Track 01 asks you to **trace, monitor, and debug AI-native systems**. That means one place to follow a request from routing → planning → LLM attempt → tool execution → recovery — with metrics and logs tied to the same trace IDs.

---

## What we shipped

**Arka** is a Python CLI agent with natural-language routing, a goal loop, 70+ skills, and security gates. **SigNoz** receives everything over OTLP HTTP on port `4318`.

Instrumentation lives in `src/arka/telemetry/`:

| Signal | What Arka exports |
| ------ | ----------------- |
| **Traces** | `arka.request` → `arka.route` → `arka.agent.goal` → `arka.llm.attempt` → `arka.tool.shell` |
| **Metrics** | `arka.routing.decisions`, `arka.skill.duration`, `arka.llm.tokens`, `arka.mcp.ops` |
| **Logs** | Structured agent events with `trace_id` / `span_id` correlation |

Every demo scenario tags spans with `arka.demo.scenario` so you can filter in SigNoz without guessing:

- `vllm-vs-cloud-latency` — compare `arka.llm.ttft_ms` across providers
- `rag-supermemory-cascade` — vector lookup → context → LLM complete
- `semantic-router-split` — symbolic route (~1 ms) vs LLM fallback (~seconds)
- `e2e-observability-pillars` — route → memory → LLM → shell in one waterfall
- `exception-stack-traces` — auto-recorded `exception.stacktrace` on error spans

Deploy is reproducible: [`casting.yaml`](../casting.yaml) + [`casting.yaml.lock`](../casting.yaml.lock) at repo root, one command via Foundry.

---

## Track 01 without a custom dashboard

You do **not** need to import a dashboard to score Track 01. Judges can verify the build with three SigNoz views:

1. **Traces Explorer** — filter `service.name = 'arka'`. You see real spans: `arka.llm.attempt`, `arka.demo.inference_compare`, `arka.route`.
2. **Services** — P99 latency, error rate, ops/sec for the `arka` service.
3. **Logs Explorer** — LLM failover events, quota errors, and provider 429 recovery correlated by trace ID.

Dashboards and alerts are bundled (`signoz/dashboards/`, `arka signoz alert-create`) for teams that want them — but the hackathon demo video and judge script focus on traces + services + logs.

**Demo video:** [`recordings/arka-signoz-hackathon-demo.mp4`](../recordings/arka-signoz-hackathon-demo.mp4) (~2 min)

---

## Reproduce in 10 minutes

**Prerequisites:** Docker Desktop (≥4 GB RAM), Python 3.11+.

```bash
git clone https://github.com/Sumit884-byte/arka.git
cd arka
pip install -e ".[chat,observability]"

# Deploy SigNoz via Foundry (Docker + foundryctl + cast)
arka signoz setup -y
```

Add to `~/.config/arka/.env` (or repo `.env`):

```bash
OTEL_TRACES_ENABLED=1
OTEL_METRICS_ENABLED=1
OTEL_LOGS_ENABLED=1
SIGNOZ_ENDPOINT=http://localhost:4318
```

Emit synthetic agent traces (no live LLM required):

```bash
arka signoz demo-scenarios --synthetic
arka signoz status   # verify pipelines + judge filter queries
```

Open **http://localhost:8080** → Traces Explorer → filter `service.name = 'arka'`.

For a live agent waterfall:

```bash
arka goal -y -n 4 "count lines in README.md"
```

Refresh SigNoz UI screenshots and rebuild the demo video:

```bash
python3 recordings/signoz-screenshots/capture_signoz_ui.py --no-dashboard
python3 recordings/build_signoz_demo_video.py
```

---

## Four observability pillars

We mapped Arka directly to SigNoz's LLM observability story ([`FOUR_PILLARS.md`](FOUR_PILLARS.md)):

### 1. End-to-end request tracing

Root span `arka.request` through routing, goal steps, LLM attempts, and tools. Filter: `arka.demo.scenario = 'e2e-observability-pillars'`.

### 2. Correlate traces with logs

`emit_log()` attaches the active span's trace ID. Click an `arka.llm.attempt` span → **Logs** tab shows `llm tokens gemini/...` on the same trace.

### 3. Token usage and cost analytics

Span attributes: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `arka.llm.estimated_cost_usd`. Metric: `arka.llm.tokens` by provider and model.

### 4. Alerts

Bundled recipes: agent error spike, LLM P99 latency, token budget. Create with `arka signoz alert-create --all` (requires `SIGNOZ_API_KEY`).

---

## Tech stack

| Layer | Technology |
| ----- | ---------- |
| Agent | **Arka** — CLI, Fish router, goal loop, skills |
| LLM | **Agno** — model-agnostic routing and chat |
| Telemetry | **OpenTelemetry** — OTLP HTTP → SigNoz `:4318` |
| Observability | **SigNoz** — traces, metrics, logs, Query Builder |
| Deploy | **SigNoz Foundry** — `foundryctl cast -f casting.yaml` |
| MCP (optional) | SigNoz MCP on `:8000` — Cursor Agent Skills plugin |

---

## Foundry and MCP

[`casting.yaml`](../casting.yaml) enables SigNoz MCP (`mcp.spec.enabled: true`) so you can query traces and metrics from Cursor via the [SigNoz Agent Skills plugin](CURSOR_AGENT_SKILLS.md). Judges can re-run:

```bash
foundryctl cast -f casting.yaml
```

and verify OTel traces land in SigNoz within minutes.

---

## AI disclosure

Per [hackathon rules](https://www.wemakedevs.org/hackathons/signoz/rules), we declare AI assistant use:

- **Cursor** — OpenTelemetry instrumentation, SigNoz wiring, docs, demo video script, screenshot capture automation, and this blog draft
- **LLM providers** — used during normal Arka development and demo scenario design

Failure to disclose AI assistance disqualifies submissions; we list it here and in our Devpost form.

---

## Links

- **Repo:** [github.com/Sumit884-byte/arka](https://github.com/Sumit884-byte/arka)
- **Hackathon:** [wemakedevs.org/hackathons/signoz](https://www.wemakedevs.org/hackathons/signoz)
- **SigNoz docs:** [signoz.io/docs](https://signoz.io/docs/)
- **Submission guide:** [`signoz/README.md`](README.md)
- **Demo video:** [`recordings/arka-signoz-hackathon-demo.mp4`](../recordings/arka-signoz-hackathon-demo.mp4)

---

Clone the repo, run `arka signoz setup -y`, then `arka signoz demo-scenarios --synthetic`. Open Traces Explorer, filter `service.name = 'arka'`, and watch the full agent lifecycle in one waterfall.
