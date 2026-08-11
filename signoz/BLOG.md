# See Inside Your Agents: Arka + SigNoz for Track 01

When a model returns 429, a shell step fails, or failover kicks in, you need to see *which* step broke — not just that something failed. We built **Arka + SigNoz** for the [Agents of SigNoz](https://www.wemakedevs.org/hackathons/signoz) hackathon (Track 01 — AI & Agent Observability) to instrument the full agent lifecycle with OpenTelemetry and make every step visible in one trace waterfall.

![End-to-end agent trace waterfall in SigNoz](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/traces-explorer.png)

**Demo video (~3 min):** [arka-signoz-hackathon-demo.mp4](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/arka-signoz-hackathon-demo.mp4)

> **Images:** PNGs live on the [signoz-hackathon-media release](https://github.com/sumitmishra884byte-cpu/arka/releases/tag/signoz-hackathon-media). If your editor (e.g. AWS Builder Center) does not render markdown images, paste the HTML blocks below or upload the PNGs from that release page.

<p align="center">
  <img src="https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/traces-explorer.png" alt="Traces Explorer — arka agent waterfall" width="100%" />
</p>


## What is Arka?

**Arka** is an open-source AI agent for your terminal. You say what you want in plain English; Arka routes the request to the right local skill, runs it on your machine, and falls back across 24 LLM providers when a model is actually needed.

Under the hood it is a Python CLI with a Fish-shell router, a multi-step **goal loop**, 70+ bundled skills, MCP for Cursor and Claude, and security gates on by default — prompt-injection checks, risky-action prompts, and hard blocks on destructive shell patterns.

Install in one line: `uv tool install "arka-agent[chat,observability]"` · Docs: [arka-agent.mintlify.site](https://arka-agent.mintlify.site)

---

## Why we love building it

We did not set out to build “another chat wrapper.” We wanted a **real agent** we could trust in our own terminals every day — one that routes fast, fails gracefully, and stays local when it should.

What keeps us shipping:

- **The router is the product.** 120+ symbolic rules handle most requests with zero LLM tokens. Watching “summarize README” hit a skill in ~1 ms instead of a 3-second model round-trip never gets old.
- **Agents are messy — and that is the fun part.** Routing, planning, tool calls, memory, failover, self-heal — every layer is a design problem. Arka is our sandbox to try ideas in production on our own repos.
- **Dogfooding forces honesty.** When Gemini 429s mid-goal or a shell step fails, we feel it immediately. That pain is why we instrumented every span and wired SigNoz — we wanted the same visibility we wish every agent framework shipped with.
- **Local-first, extensible by design.** Skills are plugins (`skill.json`), secrets stay in `~/.config/arka/`, telemetry is opt-in. You own the stack; we just make the defaults sane.
- **Building in the open.** Issues, routing mismatches, and hackathon demos like this one all land in the same repo. Shipping observability for Track 01 is part of making Arka something we are proud to hand to other developers.

If that resonates, star the repo — it helps others find it: [github.com/Sumit884-byte/arka](https://github.com/Sumit884-byte/arka)

---

## The problem

AI agents are a black box. They chain LLM calls, invoke tools, hit vector DBs, and make decisions autonomously. When latency spikes, token costs explode, or an agent hallucinates in production, fragmented logs do not tell the end-to-end story.

Track 01 asks you to **trace, monitor, and debug AI-native systems**. That means one place to follow a request from routing → planning → LLM attempt → tool execution → recovery — with metrics and logs tied to the same trace IDs.

---

## How we use SigNoz

We do not run a separate observability sidecar. **Arka instruments itself with OpenTelemetry and sends traces, metrics, and logs to SigNoz over OTLP HTTP.** SigNoz is where we deploy the stack, ingest telemetry, and debug the agent lifecycle.

### 1. Deploy with Foundry

SigNoz runs locally from [`casting.yaml`](../casting.yaml) + [`casting.yaml.lock`](../casting.yaml.lock) at repo root. One command brings up the UI (`:8080`), OTLP ingester (`:4318`), and MCP server (`:8000`):

```bash
arka signoz setup -y
```

### 2. Enable telemetry in Arka

Add to `~/.config/arka/.env`:

```bash
OTEL_TRACES_ENABLED=1
OTEL_METRICS_ENABLED=1
OTEL_LOGS_ENABLED=1
SIGNOZ_ENDPOINT=http://localhost:4318
```

Instrumentation lives in `src/arka/telemetry/` — every agent step becomes exportable telemetry with no hand-rolled exporters.

### 3. Emit traces (synthetic or live)

```bash
arka signoz demo-scenarios --synthetic   # no live LLM required
arka goal -y -n 4 "count lines in README.md"   # live agent waterfall
```

Demo scenarios tag spans with `arka.demo.scenario` so you can filter in SigNoz instantly (`vllm-vs-cloud-latency`, `rag-supermemory-cascade`, `semantic-router-split`, `e2e-observability-pillars`, `exception-stack-traces`).

### 4. Debug in SigNoz UI

For the hackathon demo we use **stock SigNoz views** — no custom dashboard required:

| View | Filter / use |
| ---- | ------------ |
| **Traces Explorer** | `service.name = 'arka'` → full waterfall (`arka.route`, `arka.llm.attempt`, RAG spans) |
| **Services** | P99 latency, error rate, ops/sec for the `arka` service |
| **Logs Explorer** | LLM failover, 429 recovery, shell events on the **same trace IDs** as spans |

Click any `arka.llm.attempt` span → **Logs** tab to see correlated agent events without switching tools.

<p><img src="https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/traces-explorer.png" alt="Traces Explorer" width="100%" /></p>

<p><img src="https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/services-metrics.png" alt="Services metrics" width="100%" /></p>

<p><img src="https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/logs-explorer.png" alt="Logs Explorer" width="100%" /></p>

### 5. Verify the stack

```bash
arka signoz status
```

Confirms Docker, foundryctl, OTLP pipelines, and built-in verify queries for routing spans, LLM attempts, and MCP tool calls.

### 6. Optional extras

- **Dashboards:** `arka signoz dashboard install` — bundled panels in `signoz/dashboards/`
- **Alerts:** `arka signoz alert-create --all` — error spike, LLM P99, token budget (needs `SIGNOZ_API_KEY`)
- **MCP:** query traces from Cursor via SigNoz MCP on `:8000` and the [Cursor Agent Skills plugin](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/CURSOR_AGENT_SKILLS.md)

---

## What we shipped

For this hackathon we instrumented Arka’s full agent lifecycle with **OpenTelemetry** and export everything to **SigNoz** over OTLP HTTP on port `4318`.

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

See [How we use SigNoz](#how-we-use-signoz) for the full deploy → instrument → debug workflow.

---

## Track 01 without a custom dashboard

Judges can verify the build with three SigNoz views:

1. **Traces Explorer** — filter `service.name = 'arka'`. You see real spans: `arka.llm.attempt`, `arka.demo.inference_compare`, `arka.route`.

   ![Traces Explorer — arka spans](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/traces-explorer.png)

   <img src="https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/traces-explorer.png" alt="Traces Explorer" width="100%" />

2. **Services** — P99 latency, error rate, ops/sec for the `arka` service.

   ![Services — P99 latency and error rate](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/services-metrics.png)

   <img src="https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/services-metrics.png" alt="Services" width="100%" />

3. **Logs Explorer** — LLM failover events, quota errors, and provider 429 recovery correlated by trace ID. Filter `service.name = 'arka'` and open a trace to see log lines on the same IDs (e.g. `route symbolic → goal loop`, Gemini 429 failover to Groq, `shell ok wc -l README.md`, `agent.self_heal` retries).

   ![Logs Explorer — arka agent events](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/logs-explorer.png)

   <img src="https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/logs-explorer.png" alt="Logs Explorer" width="100%" />

Dashboards and alerts are bundled (`signoz/dashboards/`, `arka signoz alert-create`) for teams that want them — but the hackathon demo video and judge script focus on traces + services + logs.

**Demo video:** [arka-signoz-hackathon-demo.mp4](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/arka-signoz-hackathon-demo.mp4) (~3 min) · [general Arka demo](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/arka-demo-submission.mp4)

### Where to find docs (start here)

| Resource | URL |
| -------- | --- |
| **Observability guide** (setup, demo, dashboards, MCP) | [arka-agent.mintlify.site/guides/observability](https://arka-agent.mintlify.site/guides/observability) |
| **Hackathon judge pack** (checklist, four pillars, demos) | [signoz/README.md on fork](https://github.com/sumitmishra884byte-cpu/arka/blob/main/signoz/README.md) |
| **Blog / submission narrative** (this page) | [BLOG.md on release](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/BLOG.md) |
| **Four pillars walkthrough** | [FOUR_PILLARS.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/FOUR_PILLARS.md) |
| **MCP + Cursor skills** | [MCP_INTEGRATION.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/MCP_INTEGRATION.md) · [CURSOR_AGENT_SKILLS.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/CURSOR_AGENT_SKILLS.md) |
| **AWS prize path** | [AWS_PRIZE.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/AWS_PRIZE.md) |
| **Demo media (PNG/MP4)** | [signoz-hackathon-media release](https://github.com/sumitmishra884byte-cpu/arka/releases/tag/signoz-hackathon-media) |
| **Quickstart** (install `arka-agent`, API keys) | [arka-agent.mintlify.site/quickstart](https://arka-agent.mintlify.site/quickstart) |
| **SigNoz official docs** | [signoz.io/docs](https://signoz.io/docs/) |

---

## Reproduce in 10 minutes

**Prerequisites:** Docker Desktop (≥4 GB RAM), Python 3.11+.

```bash
git clone https://github.com/Sumit884-byte/arka.git
cd arka
git checkout main
pip install -e ".[chat,observability]"

# Deploy SigNoz via Foundry (Docker + foundryctl + cast)
arka signoz setup -y
```

Or install without cloning:

```bash
uv tool install "arka-agent[chat,observability]"
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

![SigNoz home after setup](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/home-dashboard.png)

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

We mapped Arka directly to SigNoz's LLM observability story ([FOUR_PILLARS.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/FOUR_PILLARS.md)):

### 1. End-to-end request tracing

Root span `arka.request` through routing, goal steps, LLM attempts, and tools. Filter: `arka.demo.scenario = 'e2e-observability-pillars'`.

![E2E trace waterfall](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/traces-explorer.png)

### 2. Correlate traces with logs

`emit_log()` attaches the active span's trace ID. Click an `arka.llm.attempt` span → **Logs** tab shows `llm tokens gemini/...` on the same trace.

### 3. Token usage and cost analytics

Span attributes: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `arka.llm.estimated_cost_usd`. Metric: `arka.llm.tokens` by provider and model.

![Observability dashboard — tokens and latency](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/dashboard-observability-long.png)

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

[`casting.yaml`](../casting.yaml) enables SigNoz MCP (`mcp.spec.enabled: true`) so you can query traces and metrics from Cursor via the [SigNoz Agent Skills plugin](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/CURSOR_AGENT_SKILLS.md). Judges can re-run:

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

- **Docs (observability):** [arka-agent.mintlify.site/guides/observability](https://arka-agent.mintlify.site/guides/observability)
- **Upstream repo:** [github.com/Sumit884-byte/arka](https://github.com/Sumit884-byte/arka)
- **Hackathon fork:** [github.com/sumitmishra884byte-cpu/arka](https://github.com/sumitmishra884byte-cpu/arka/tree/main)
- **Judge pack:** [signoz/README.md](https://github.com/sumitmishra884byte-cpu/arka/blob/main/signoz/README.md) · [FOUR_PILLARS.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/FOUR_PILLARS.md) · [release media + docs](https://github.com/sumitmishra884byte-cpu/arka/releases/tag/signoz-hackathon-media)
- **Hackathon:** [wemakedevs.org/hackathons/signoz](https://www.wemakedevs.org/hackathons/signoz)
- **SigNoz docs:** [signoz.io/docs](https://signoz.io/docs/)
- **Demo video:** [arka-signoz-hackathon-demo.mp4](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/arka-signoz-hackathon-demo.mp4) (~3 min) · [general Arka demo](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/arka-demo-submission.mp4)

**YouTube / Devpost blurb:** *See inside your AI agents — not just that something failed, but which step broke. Arka instruments routing, LLM attempts, RAG retrieval, tool calls, and failover with OpenTelemetry; SigNoz shows the full waterfall in Traces Explorer, Services metrics, and correlated Logs Explorer. Reproduce: `arka signoz setup -y` → `arka signoz demo-scenarios --synthetic` → filter `service.name = 'arka'`.*

---

Clone the repo, run `arka signoz setup -y`, then `arka signoz demo-scenarios --synthetic`. Open Traces Explorer, filter `service.name = 'arka'`, and watch the full agent lifecycle in one waterfall.
