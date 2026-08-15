# Arka × SigNoz — Track 01: AI & Agent Observability

Submission for [Agents of SigNoz](https://www.wemakedevs.org/hackathons/signoz) (Jul 20–26, 2026) · [Hackathon rules](https://www.wemakedevs.org/hackathons/signoz/rules)

**Documentation:** [arka-agent.mintlify.site/guides/observability](https://arka-agent.mintlify.site/guides/observability) · **Hackathon repo (fork):** [github.com/sumitmishra884byte-cpu/arka](https://github.com/sumitmishra884byte-cpu/arka/tree/main/signoz) · **Upstream:** [github.com/Sumit884-byte/arka](https://github.com/Sumit884-byte/arka/tree/main/signoz)

**Judge pack docs** (markdown not in git — served from the fork release):

| Doc | Public URL |
| --- | ---------- |
| Hackathon README (this page) | [signoz/README.md](https://github.com/sumitmishra884byte-cpu/arka/blob/main/signoz/README.md) |
| Blog / submission narrative | [BLOG.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/BLOG.md) |
| Four SigNoz pillars | [FOUR_PILLARS.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/FOUR_PILLARS.md) |
| MCP integration | [MCP_INTEGRATION.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/MCP_INTEGRATION.md) |
| Cursor Agent Skills | [CURSOR_AGENT_SKILLS.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/CURSOR_AGENT_SKILLS.md) |
| AWS prize path | [AWS_PRIZE.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/AWS_PRIZE.md) |
| Demo media (PNG/MP4) | [signoz-hackathon-media release](https://github.com/sumitmishra884byte-cpu/arka/releases/tag/signoz-hackathon-media) |

## Problem

### Why we're doing this

**Your AI agents are a black box.** AI is eating software, and nobody can see inside it.

**Flying blind.** Agents chain LLM calls, invoke tools, hit vector DBs, and make decisions autonomously. When latency spikes, costs explode, or an agent hallucinates in production, you can't debug what you can't see. Fragmented logs don't give the end-to-end story Track 01 asks for: trace, monitor, and debug AI-native systems.

**What we need: total visibility.** SigNoz gives full visibility into every AI workflow — trace each agent step, monitor provider/token costs, correlate LLM responses with downstream failures. OpenTelemetry-native, so instrumentation works everywhere. **One platform. Every AI signal.**

Arka's angle: when a model returns 429, a shell step fails, or failover kicks in, you need to see *which* step broke and *why* — not just that something failed.

## Solution

**Arka + SigNoz** instruments the full agent lifecycle with **OpenTelemetry** and exports it to SigNoz:

- **Route** — NL routing (`arka.route`, LLM fallback)
- **Plan & act** — goal-loop steps, Fish shell tools, 70+ skills
- **LLM layer** — every attempt + failover across 16+ providers (Agno orchestrator)
- **Memory** — Supermemory API + local fallback (`arka.supermemory.remember` / `recall` / `context` spans, `arka.supermemory.ops` metric)
- **Self-heal** — failed commands emit `agent.self_heal`; the next step diagnoses from history
- **Inference** — optional Ollama/vLLM auto-start spans

One OTLP trace waterfall in SigNoz shows routing → planning → tools → recovery — agent observability you can reproduce locally with Foundry.

**Four SigNoz pillars** (E2E tracing, log correlation, token/cost analytics, alerts/dashboards): [FOUR_PILLARS.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/FOUR_PILLARS.md) · `arka signoz demo-e2e --synthetic`

## Tech stack

| Layer | Technology | Role in this build |
| ----- | ---------- | ------------------ |
| Agent | **Arka** | Python CLI + Fish shell router, goal loop, 70+ skills, security gates |
| LLM | **Agno** | Model-agnostic routing and chat (`pip install -e ".[chat,observability]"`) |
| Telemetry | **OpenTelemetry** | `src/arka/telemetry/` — OTLP HTTP → SigNoz ingester `:4318` |
| Observability | **SigNoz** | Traces, Query Builder, dashboards — see [dashboards/README.md](dashboards/README.md) |
| Deploy | **SigNoz Foundry** | [`casting.yaml`](../casting.yaml) + [`casting.yaml.lock`](../casting.yaml.lock) — `foundryctl cast`; MCP enabled on `:8000` |
| Inference (opt.) | **vLLM / Ollama** | Self-hosted backends; spans `arka.inference.*`, `arka.llm.attempt` |
| Patterns (opt.) | **OpenClaw-inspired** | Session memory (`MEMORY.md`), webhook ingress, heartbeat — same OTel hooks |
| Hackathon | **Track 01 — AI & Agent Observability** | E2E agent + LLM failover + self-heal traces |

**Compliance:** Official [hackathon rules](https://www.wemakedevs.org/hackathons/signoz/rules) mapped below. Copy-paste block: [Submission template](#submission-template).

---

## Official rules (summary)

Source: [Agents of SigNoz — Rules](https://www.wemakedevs.org/hackathons/signoz/rules) · [Overview](https://www.wemakedevs.org/hackathons/signoz)

### Agency protocols

| Rule | Notes for Arka |
| ---- | -------------- |
| **Team size 1–4** | Solo or agency — confirm roster before submit |
| **Required tech: SigNoz** | Deeper use of OTel **traces, metrics, logs**, dashboards, and alerts → stronger score |
| **Three tracks** | We target **Track 01 — AI & Agent Observability** (example builds are inspiration only) |
| **AI assistants allowed** | Must **declare in submission** — nondisclosure = disqualification |
| **IP** | Belongs to the team that built it |
| **Pre-hackathon work** | Planning/sketches OK; coding should start when hackathon opens |

### SigNoz field requirements

| Requirement | Arka |
| ----------- | ---- |
| Install SigNoz via **Foundry** (SigNoz + MCP in one step) | `arka signoz setup -y` or `foundryctl cast -f casting.yaml` |
| **Reproducible deploy** — `casting.yaml` + `casting.yaml.lock` in repo | ✅ Repo root |
| Use **MCP**, **Query Builder**, **dashboards**, **alerts** (recommended) | MCP ✅ · [Cursor Agent Skills plugin](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/CURSOR_AGENT_SKILLS.md) · dashboards/alerts ✅ |
| **AWS prize** — [AWS Builder Center](https://builder.aws.com/) signup + **build with AWS** | [AWS_PRIZE.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/AWS_PRIZE.md) (Bedrock path). **$100 AWS credits:** email contact@wemakedevs.org |
| **Blog prize** — publish on **AWS Builder Center** | Optional — Bedrock + SigNoz walkthrough |

---

## Rules compliance checklist

Use this before submitting. Judges may re-run Foundry and verify OTel traces in SigNoz.

| Requirement | Status | Where / how |
| ----------- | ------ | ----------- |
| SigNoz installed via **Foundry** | ✅ | Repo root [`casting.yaml`](../casting.yaml) + [`casting.yaml.lock`](../casting.yaml.lock) |
| Reproducible deployment (`casting.yaml` + `.lock`) | ✅ | `foundryctl forge -f casting.yaml` regenerates lock; `foundryctl cast` deploys |
| **OpenTelemetry** traces exported to SigNoz | ✅ | `src/arka/telemetry/` — OTLP HTTP to ingester `:4318` |
| Traces, metrics, logs pipelines in SigNoz | ✅ traces · ✅ metrics · ✅ logs | Traces: E2E waterfall. Metrics: OTLP counters. Logs: OTLP structured agent events |
| SigNoz **MCP server** enabled | ✅ | `mcp.spec.enabled: true` in `casting.yaml` → `signoz-mcp` on `:8000` |
| SigNoz **Query Builder** / dashboards | ✅ docs | [dashboards/README.md](dashboards/README.md) — panel queries + import stub |
| SigNoz **alerts** | ✅ bundled | `arka signoz alert-create` — [`alerts/`](alerts/) + [recipes](dashboards/README.md#recommended-alerts) |
| **AI assistant disclosure** in submission | ⚠️ required | Fill [Submission template](#submission-template) — failure to disclose = disqualification |
| Team size 1–4, IP to team | ✅ | Confirm agency roster + internal IP agreement |
| Code of Conduct | ✅ | Respect policy — report issues to organizers |

**Optional prizes**

| Prize | Requirement | Arka status |
| ----- | ----------- | ----------- |
| Best use of AWS | Builder Center signup + build with AWS | [AWS_PRIZE.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/AWS_PRIZE.md) · $100 credits: contact@wemakedevs.org |
| Best blog | **Publish on AWS Builder Center** (mandatory for prize) | Optional — not started |

---

## Submission template

Copy into Devpost / submission form.

```markdown
### Project: Arka + SigNoz — AI Agent Observability

**Track:** 01 — AI & Agent Observability

**Team:** [Name(s)] (1–4 members)

**Repo:** https://github.com/sumitmishra884byte-cpu/arka (branch: `main`)

**Judge pack docs** (public markdown on fork release — not in git):

- README: https://github.com/sumitmishra884byte-cpu/arka/blob/main/signoz/README.md
- BLOG: https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/BLOG.md
- FOUR_PILLARS: https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/FOUR_PILLARS.md
- MCP_INTEGRATION: https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/MCP_INTEGRATION.md
- CURSOR_AGENT_SKILLS: https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/CURSOR_AGENT_SKILLS.md
- AWS_PRIZE: https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/AWS_PRIZE.md

**AI tools used (required — nondisclosure disqualifies):**
- [ ] Cursor — used for [code, docs, debugging, observability wiring, …]
- [ ] [Other tools/models] — used for […]

**SigNoz integration (deeper = stronger score):**
- Foundry: `casting.yaml` + `casting.yaml.lock` at repo root
- OTel traces + metrics + logs → SigNoz ingester (`:4318`)
- MCP: enabled in casting (port 8000) — optional Cursor demo
- Dashboards + alerts: see `signoz/dashboards/`

**Demo (5 min):**
1. `foundryctl cast -f casting.yaml` → SigNoz UI at http://localhost:8080
2. Enable OTEL in `~/.config/arka/.env` (see below)
3. `arka signoz demo` → synthetic E2E trace
4. `arka goal -y -n 4 "count lines in README.md"` → live agent waterfall
5. (Optional) Install [SigNoz Agent Skills for Cursor](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/CURSOR_AGENT_SKILLS.md) — plugin + `/signoz-mcp-setup http://localhost:8000/mcp`

**Video / screenshots:** https://github.com/sumitmishra884byte-cpu/arka/releases/tag/signoz-hackathon-media

**Video description (Devpost / YouTube):**
Three-minute Track 01 demo — deploy SigNoz with Foundry (`arka signoz setup -y`), emit synthetic agent traces (`arka signoz demo-scenarios --synthetic`), and inspect routing, LLM attempts, RAG retrieval, failover, and tool calls in SigNoz Traces Explorer, Services metrics, and correlated Logs Explorer. OpenTelemetry built into arka-agent; reproducible via `casting.yaml` at repo root. Full text: `recordings/signoz-hackathon-demo-description.txt`.
```

---

## For judges — reproduce in ~10 minutes

Prerequisites: Docker Desktop (≥4 GB RAM), Python 3.11+.

**Quick setup (installs Docker + foundryctl when missing):**

```bash
arka signoz setup          # interactive — prompts before installs/cast
arka signoz setup -y       # unattended (or ARKA_AUTO_INSTALL=1)
arka signoz setup --check-only   # prerequisite status only
arka signoz status         # tracing + docker/foundryctl lines
```

On macOS, Docker Desktop still needs a manual first launch after `brew install --cask docker` — Arka opens the app and waits up to ~90s for the daemon.

### 1. Install Foundry

```bash
curl -fsSL https://signoz.io/foundry.sh | bash
# or: download from https://github.com/SigNoz/foundry/releases
```

### 2. Deploy SigNoz from repo casting

```bash
git clone https://github.com/sumitmishra884byte-cpu/arka.git arka && cd arka
git checkout main

foundryctl gauge -f casting.yaml    # validate Docker
foundryctl cast -f casting.yaml     # forge + deploy (writes pours/, updates lock if needed)
```

Verify:

```bash
docker ps | grep signoz
curl -fsS http://localhost:8080/api/v1/health && echo " SigNoz UI OK"
curl -fsS http://localhost:8000/livez && echo " MCP OK"
```

| Endpoint | URL |
| -------- | --- |
| SigNoz UI | http://localhost:8080 |
| OTLP HTTP | http://localhost:4318 |
| OTLP gRPC | http://localhost:4317 |
| SigNoz MCP | http://localhost:8000/mcp |

### 3. Install Arka + observability extras

```bash
pip install -e ".[chat,observability]"
```

### 4. Enable tracing

Add to `~/.config/arka/.env` (or copy from `src/arka/env.example`):

```bash
OTEL_TRACES_ENABLED=1
OTEL_SERVICE_NAME=arka
SIGNOZ_ENDPOINT=http://localhost:4318
SIGNOZ_UI_URL=http://localhost:8080
```

### 5. Run demo commands

```bash
arka signoz status          # tracing config + SigNoz UI link
arka signoz demo            # sample E2E agent trace (no LLM)
arka goal -y -n 3 "count lines in README.md"   # live agent (needs API key)
```

Open **SigNoz → Traces** → filter `service.name = arka`.

### 6. (Optional) SigNoz MCP + dashboards

- MCP setup: [MCP_INTEGRATION.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/MCP_INTEGRATION.md)
- Dashboard panels: [dashboards/README.md](dashboards/README.md)

---

## How Arka maps to Track 01 example builds

| Hackathon example | Arka implementation |
| ----------------- | --------------------- |
| **AI agents with E2E observability on SigNoz** | Primary build — `arka.request` → route → goal steps → LLM attempts → tools/skills, all exported via OTLP to SigNoz |
| **Self-hosted inference observability (vLLM)** | `vllm` / `vllm-cloud` in LLM fallback chain; spans `arka.inference.server.prepare`, `arka.inference.vllm.check`, `arka.inference.vllm.cloud`, `arka.llm.attempt` with `arka.inference.backend=vllm` or `vllm-cloud`; `arka signoz vllm` health check |
| **SRE Sidekick with SigNoz MCP** | Phase 1: goal agent emits traces you inspect in SigNoz; Phase 2 (stretch): MCP tool to query failed spans — see [MCP_INTEGRATION.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/MCP_INTEGRATION.md) |
| **n8n workflows with E2E observability** | Arka skills/routines are the workflow layer — same OTel hooks apply to any skill chain (`arka.skill.*`) |
| **Self-healing infra with SigNoz metrics** | Goal agent retries after failed commands — `agent.self_heal` span events when exit ≠ 0, next step diagnoses from history |

## Foundry files (repo root)

| File | Purpose |
| ---- | ------- |
| [`casting.yaml`](../casting.yaml) | Declarative SigNoz + MCP deployment (Docker Compose) |
| [`casting.yaml.lock`](../casting.yaml.lock) | Resolved config checksums — judges re-run Foundry against this |

Regenerate lock after editing `casting.yaml`:

```bash
foundryctl forge -f casting.yaml
```

Our casting enables MCP by default:

```yaml
spec:
  deployment:
    flavor: compose
    mode: docker
  mcp:
    spec:
      enabled: true
```

## Demo Scenarios

Three judge-ready traces for **Self-hosted Inference** and **Agent Observability**. Full env vars: [demos/README.md](demos/README.md).

### Prerequisites

```bash
pip install -e ".[chat,observability]"
arka signoz setup -y
# ~/.config/arka/.env — OTEL_TRACES_ENABLED=1, SIGNOZ_ENDPOINT=http://localhost:4318
```

### Scenario 1 — vLLM vs Cloud Latency Gap (Self-hosted Inference)

Compare the same prompt on **vLLM** (local or `vllm-cloud`) vs an external cloud API (default: Gemini).

```bash
arka signoz demo-inference
# offline / no vLLM: arka signoz demo-inference --synthetic
```

**Span hierarchy**

```
arka.request                         arka.demo.scenario=vllm-vs-cloud-latency
└── arka.demo.inference_compare
    ├── arka.llm.complete            arka.demo.backend=vllm-cloud
    │   └── arka.llm.attempt         arka.inference.backend=vllm-cloud
    │       arka.llm.ttft_ms, arka.llm.duration_ms, http.url → VLLM endpoint
    └── arka.llm.complete            arka.demo.backend=cloud-api
        └── arka.llm.attempt         gen_ai.provider.name=gemini
            lower ttft_ms, http.url → generativelanguage.googleapis.com
```

**What judges should notice:** vLLM spans often show **higher `arka.llm.ttft_ms`** (local GPU queue / smaller hardware) while cloud spans show **network RTT** in `http.url` + faster provider TTFT. Side-by-side `durationNano` on `arka.llm.attempt` makes the gap obvious.

### Scenario 2 — RAG & Supermemory Fetch Cascade

One trace: vector/memory lookup → LLM consumes context.

```bash
arka signoz demo-rag
# no API keys: arka signoz demo-rag --synthetic
```

**Span hierarchy**

```
arka.request                         arka.demo.scenario=rag-supermemory-cascade
└── arka.rag.cascade
    ├── arka.supermemory.context
    │   └── arka.supermemory.vector_lookup   arka.supermemory.lookup_ms
    │       (or arka.supermemory.api for cloud profile/search)
    └── arka.llm.context_process             arka.llm.context_chars
        └── arka.llm.complete
            └── arka.llm.attempt
```

**What judges should notice:** **`arka.supermemory.lookup_ms`** (vector/API fetch) is a short child span; **`arka.llm.complete`** dominates wall time — proves you can see *where* RAG latency lives vs LLM processing.

### Scenario 3 — Semantic Router Split (Agent Observability)

Symbolic route (instant, no model) vs semantic route (LLM classifier).

```bash
arka signoz demo-router
# no LLM key: arka signoz demo-router --synthetic
```

**Span hierarchy**

```
arka.request                         arka.demo.scenario=semantic-router-split
└── arka.demo.router_compare
    ├── arka.route                   arka.route.decision=symbolic  (~1ms)
    │   arka.route.skill=calc 17 * 23
    └── arka.route                   arka.route.decision=llm
        └── arka.route.llm           arka.route.latency_ms >> symbolic
```

**What judges should notice:** **`arka.route.decision=symbolic`** completes in sub-millisecond `arka.route.latency_ms` with **no** `arka.route.llm` child. Semantic path adds **`arka.route.llm`** — agent avoids unnecessary model calls for simple intents.

### Run all scenarios

```bash
arka signoz demo-scenarios
./signoz/demos/run_all.sh
```

Saved SigNoz trace filters: [dashboards/README.md](dashboards/README.md#trace-explorer-saved-views).

---

## Arka benchmarking (adoption)

Observability tells you *what happened* on a run; benchmarks tell you *whether Arka is good enough to adopt* — routing accuracy, provider cost, and end-to-end agent quality, all measured with the same OTel signals this hackathon instruments.

### Why benchmarks matter

| Question | Without benchmarks | With Arka benches + SigNoz |
| -------- | ------------------ | -------------------------- |
| Does NL routing work? | Anecdotal “it routed correctly” | Accuracy % over ~100+ NL cases; offline vs LLM split |
| Is zero-token routing worth it? | Guess from one trace | `arka.route.decision=symbolic` latency vs `arka.route.llm` + token cost |
| Which model should I use? | Manual trial and error | Ranked providers per task profile (`chat`, `route`, `agent`) |
| Can Arka compete with other agents? | Marketing claims | Harness tasks with completion rate, steps, wall time, and cost |

### Three benchmark suites

| Suite | Measures | Existing infra | Rollout |
| ----- | -------- | -------------- | ------- |
| **ArkaRouteBench** | Routing accuracy, offline hit rate, zero-token vs LLM routing | `tests/test_nl_routing_coverage.py` (~107 NL cases), `arka dev route-audit`, `ROUTE_MODE=symbolic_only` | **1 — first** |
| **ArkaModelBench** | Provider/model comparison by task profile; quality + cost tradeoffs | `arka benchmark run\|show\|apply`, `~/.config/arka/benchmark-results.json`, default suite in `src/arka/llm/templates/benchmark-default.yaml` | **2** |
| **ArkaHarnessBench Lite** | 25 real tasks — Arka vs OpenClaw / Claude Code on completion, steps, cost | Goal loop + skill chain (same spans as live agent demos) | **3** |

**Rollout order:** RouteBench → docs/badges → ModelBench → HarnessBench Lite. RouteBench ships first because routing is the front door — every request passes through `arka.route` before planning or LLM calls.

### Planned metrics

| Suite | Primary metrics | SigNoz / OTel signals |
| ----- | --------------- | --------------------- |
| **RouteBench** | Top-1 skill accuracy, offline hit rate (%), symbolic p50/p99 latency, LLM-route token cost | `arka.route`, `arka.route.decision`, `arka.route.latency_ms`, `arka.route.source` (`offline` / `llm` / `fish`) |
| **ModelBench** | Score per candidate × task profile, cost per 1k tokens, p50/p99 `arka.llm.duration_ms`, failover rate | `arka.llm.attempt`, `gen_ai.provider.name`, `gen_ai.request.model`, `arka.llm.attempt_index` |
| **HarnessBench** | Task pass rate, median steps to done, total wall time, aggregate token spend | `arka.request` → `arka.agent.goal` → `arka.agent.goal.step` waterfall; group by `arka.benchmark.suite` (planned attribute) |

Scenario 3 ([Semantic Router Split](#scenario-3--semantic-router-split-agent-observability)) is the preview: symbolic routes finish in ~1 ms with no LLM child; semantic routes add `arka.route.llm` and measurable token cost. RouteBench scales that comparison across the full NL coverage table.

### Run what exists today

```bash
# Routing coverage (offline symbolic path)
ROUTE_MODE=symbolic_only pytest tests/test_nl_routing_coverage.py -v

# Symbolic / fish / test parity audit
arka dev route-audit

# Provider benchmark (dry-run needs no API keys)
arka benchmark init
arka benchmark run --dry-run
arka benchmark show
arka benchmark apply --dry-run

# Live benchmark run with OTEL enabled → traces in SigNoz
OTEL_TRACES_ENABLED=1 SIGNOZ_ENDPOINT=http://localhost:4318 arka benchmark run
```

With tracing on, filter **SigNoz → Traces** by `service.name = arka` and compare `arka.route.decision=symbolic` vs `llm` side-by-side — the same panels used for [demo-router](#scenario-3--semantic-router-split-agent-observability) become adoption dashboards once benchmark suites run in CI.

Planned additions: README badges (offline hit rate, route accuracy), a RouteBench CI job, and dashboard panels grouped by `arka.benchmark.suite` for HarnessBench cost/latency regressions.

---

## Span hierarchy (E2E)

```
arka.request                    # top-level CLI request (goal / ask)
├── arka.route                  # NL routing decision
│   ├── arka.route.symbolic     # (attribute arka.route.decision=symbolic)
│   └── arka.route.llm          # LLM route fallback
├── arka.rag.cascade            # memory fetch → LLM context (demo)
├── arka.supermemory.vector_lookup
├── arka.skill.<name>           # skill execution
├── arka.agent.goal             # autonomous session
│   └── arka.agent.goal.step
│       ├── arka.llm.complete   # plan next JSON action
│       │   └── arka.llm.attempt
│       ├── arka.tool.shell     # fish command
│       ├── arka.tool.read_file
│       └── event: agent.self_heal   # failed cmd → retry next step
├── arka.inference.server.prepare    # auto-start Ollama/vLLM
├── arka.inference.vllm.check        # arka signoz vllm (local)
└── arka.inference.vllm.cloud        # arka signoz vllm (remote)
```

## Key attributes (filter/group in SigNoz)

| Attribute | Use |
| --------- | --- |
| `gen_ai.provider.name` | Which LLM provider succeeded/failed |
| `gen_ai.request.model` | Model ID |
| `arka.task` | `agent`, `chat`, `route`, … |
| `arka.agent.step` | Goal step number |
| `arka.agent.status` | `continue`, `done`, `read` |
| `arka.inference.backend` | `vllm`, `vllm-cloud`, `ollama`, … |
| `arka.route.source` | `offline`, `llm`, `fish` |
| `arka.llm.attempt_index` | Failover attempt # |
| `http.method` | LLM request verb (`POST` for chat completions) |
| `http.status_code` | Provider HTTP status (`200`, `401`, `429`, …) |
| `arka.route.decision` | `symbolic`, `llm`, `fish` — router demo filter |
| `arka.route.latency_ms` | Symbolic vs LLM routing cost |
| `arka.llm.ttft_ms` | Time-to-first-token (or total when non-streaming) |
| `arka.llm.duration_ms` | Full LLM attempt wall time |
| `arka.supermemory.lookup_ms` | Vector / keyword fetch duration |
| `arka.demo.scenario` | `vllm-vs-cloud-latency`, `rag-supermemory-cascade`, `semantic-router-split` |

## Demo script (5 min)

1. `foundryctl cast -f casting.yaml` — show SigNoz + MCP running
2. `arka signoz demo` — show synthetic E2E trace in SigNoz
3. `arka goal -y -n 4 "…real task…"` — show live agent waterfall
4. Trigger a failing command — highlight `agent.self_heal` event + next-step recovery
5. (Optional) SigNoz MCP in Cursor — ask "show failed arka spans in the last hour"
6. (Optional) Set `VLLM_HOST` or `VLLM_CLOUD_URL` — show `arka signoz vllm` + inference spans

## Pitch (30 sec)

AI agents chain LLM calls and tools autonomously — when latency spikes or a step fails, you're flying blind. **Arka + SigNoz** instruments every agent step, LLM failover, and skill invocation with OpenTelemetry. One trace shows routing → planning → tool execution → self-heal retries — debuggable AI infrastructure you actually own.

## Commands reference

```fish
arka signoz setup [-y] [--skip-cast] [--check-only]
arka signoz status
arka signoz demo
arka signoz demo-inference [--synthetic]
arka signoz demo-rag [--synthetic]
arka signoz demo-router [--synthetic]
arka signoz demo-scenarios [--synthetic]
arka signoz vllm
arka benchmark run|show|apply          # ModelBench — provider rankings
arka dev route-audit                   # RouteBench — routing parity audit
python3 bin/arka_llm.py trace-status
python3 bin/arka_signoz.py setup -y
foundryctl cast -f casting.yaml
```

## vLLM (self-hosted inference)

```bash
VLLM_HOST=127.0.0.1:8000
VLLM_MODEL=meta-llama/Llama-3.2-3B-Instruct
# VLLM_START_CMD=vllm serve meta-llama/Llama-3.2-3B-Instruct --port 8000
LLM_FALLBACK=vllm:meta-llama/Llama-3.2-3B-Instruct,gemini:gemini-2.0-flash
```

Traces tag `arka.inference.backend=vllm` on local LLM attempts and server auto-start, or `vllm-cloud` for remote OpenAI-compatible endpoints.

## vLLM Cloud (RunPod, Baseten, …)

```bash
VLLM_CLOUD_URL=https://your-endpoint.runpod.net/v1
VLLM_CLOUD_API_KEY=your-key
VLLM_CLOUD_MODEL=meta-llama/Llama-3.2-3B-Instruct
LLM_FALLBACK=vllm-cloud:meta-llama/Llama-3.2-3B-Instruct,gemini:gemini-2.0-flash
```

## Related docs

- **[Observability guide (Mintlify)](https://arka-agent.mintlify.site/guides/observability)** — `arka signoz setup`, demo, dashboards, MCP (primary docs for judges)
- [FOUR_PILLARS.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/FOUR_PILLARS.md) — traces, metrics, logs, LLM spans walkthrough
- [MCP_INTEGRATION.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/MCP_INTEGRATION.md) — SigNoz MCP for SRE Sidekick / Cursor
- [BLOG.md](https://github.com/sumitmishra884byte-cpu/arka/releases/download/signoz-hackathon-media/BLOG.md) — submission narrative + screenshots
- [dashboards/README.md](dashboards/README.md) — Query Builder panels + alert recipes
- [Arka benchmarking (adoption)](#arka-benchmarking-adoption) — RouteBench, ModelBench, HarnessBench Lite + SigNoz tie-in
- [SigNoz Foundry docs](https://signoz.io/docs/install/docker/)
- [SigNoz MCP server docs](https://signoz.io/docs/ai/signoz-mcp-server/)
