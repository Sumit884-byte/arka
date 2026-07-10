# Arka agent dashboards — SigNoz Query Builder

Build these panels in **SigNoz → Dashboards → + New dashboard**, or import the stub JSON below.

After you build the real dashboard in the UI, **Export JSON** and replace `arka-agent-observability.stub.json` for judges.

## Quick import (stub)

1. SigNoz UI → **Dashboards** → **+ New dashboard** → **Import JSON**
2. Upload [`arka-agent-observability.stub.json`](arka-agent-observability.stub.json)
3. Edit each panel to match your data source (Traces / Metrics)

> The stub is a minimal template. SigNoz dashboard JSON is version-specific — prefer building panels via Query Builder below, then exporting.

## Query Builder panels (recommended)

### Panel 1 — Agent request rate

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.request`
- **Aggregation:** Count, group by `name`
- **Visualization:** Time series

### Panel 2 — Goal step latency (p95)

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.agent.goal.step`
- **Aggregation:** p95 of `durationNano`
- **Group by:** `arka.agent.step`
- **Visualization:** Bar chart

### Panel 3 — LLM provider mix

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.llm.attempt`
- **Aggregation:** Count
- **Group by:** `gen_ai.provider.name`
- **Visualization:** Pie / table

### Panel 4 — LLM failover attempts

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.llm.attempt` AND `arka.llm.attempt_index > 1`
- **Aggregation:** Count over time
- **Visualization:** Time series

### Panel 5 — Self-heal events

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.agent.goal.step`
- **Filter events:** `agent.self_heal`
- **Aggregation:** Count
- **Visualization:** Stat / time series

### Panel 6 — Error rate by span name

- **Data source:** Traces
- **Query:** `service.name = arka` AND `status = error`
- **Aggregation:** Count
- **Group by:** `name`
- **Visualization:** Table

### Panel 7 — vLLM inference (optional)

- **Data source:** Traces
- **Query:** `service.name = arka` AND (`arka.inference.backend = vllm` OR `arka.inference.backend = vllm-cloud`)
- **Aggregation:** Count + avg duration
- **Visualization:** Time series

### Panel 8 — Supermemory recall / context

- **Data source:** Traces
- **Query:** `service.name = arka` AND (`name = arka.supermemory.recall` OR `name = arka.supermemory.context`)
- **Aggregation:** Count
- **Group by:** `arka.supermemory.backend`
- **Visualization:** Pie / table

### Panel 9 — Supermemory API errors

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.supermemory.api` AND `status = error`
- **Aggregation:** Count
- **Group by:** `arka.supermemory.path`
- **Visualization:** Table

### Panel 10 — Supermemory ops (metrics)

- **Data source:** Metrics
- **Query:** `arka.supermemory.ops`
- **Aggregation:** Sum, group by `arka.supermemory.operation`, `arka.supermemory.backend`
- **Visualization:** Time series

### Panel 11 — LLM TTFT by provider (demo)

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.llm.attempt` AND `arka.llm.ttft_ms` exists
- **Aggregation:** p95 of `arka.llm.ttft_ms`
- **Group by:** `gen_ai.provider.name`, `arka.inference.backend`
- **Visualization:** Bar chart
- **Demo:** `arka signoz demo-inference`

### Panel 12 — Vector lookup vs LLM (RAG demo)

- **Data source:** Traces
- **Query:** `service.name = arka` AND (`name = arka.supermemory.vector_lookup` OR `name = arka.llm.context_process`)
- **Aggregation:** avg `durationNano` or avg `arka.supermemory.lookup_ms`
- **Visualization:** Time series
- **Demo:** `arka signoz demo-rag`

### Panel 13 — Router decision latency

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.route`
- **Aggregation:** avg `arka.route.latency_ms`
- **Group by:** `arka.route.decision`
- **Visualization:** Bar chart
- **Demo:** `arka signoz demo-router`

### Panel 14 — LLM token usage by model

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.llm.attempt` AND `gen_ai.usage.total_tokens` exists
- **Aggregation:** sum `gen_ai.usage.total_tokens`
- **Group by:** `gen_ai.request.model`
- **Visualization:** Pie / table
- **Demo:** `arka signoz demo-e2e`

### Panel 15 — LLM cost estimate (USD)

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.llm.attempt`
- **Aggregation:** sum `arka.llm.estimated_cost_usd` (or `arka.llm.cost_usd`)
- **Group by:** `gen_ai.provider.name`
- **Visualization:** Time series

### Panel 16 — p99 LLM latency vs TTFT

- **Data source:** Traces
- **Query:** `service.name = arka` AND `name = arka.llm.attempt`
- **Aggregation:** p95 `arka.llm.duration_ms`, p95 `arka.llm.ttft_ms`
- **Group by:** `gen_ai.provider.name`
- **Visualization:** Time series (compare inference vs network+model)

## Trace ↔ log correlation

After `arka signoz demo-e2e --synthetic`:

1. Traces → filter `arka.demo.scenario = e2e-observability-pillars`
2. Click `arka.llm.attempt` span
3. **Logs** tab → correlated entries with `gen_ai.usage.*` and same trace ID
4. **Metrics** tab → `arka.llm.tokens` counter

See [`../FOUR_PILLARS.md`](../FOUR_PILLARS.md) for the full judge walkthrough.

## Trace explorer saved views

Save these in **Traces → Filters** for demo:

| View name | Filter |
| --------- | ------ |
| All Arka requests | `service.name = arka` AND `name = arka.request` |
| Goal sessions | `name = arka.agent.goal` |
| Failed tools | `name = arka.tool.shell` AND `status = error` |
| LLM failover | `name = arka.llm.attempt` AND `arka.llm.attempt_index > 1` |
| Supermemory | `name = arka.supermemory.context` OR `name = arka.supermemory.recall` |
| Memory API errors | `name = arka.supermemory.api` AND `status = error` |
| vLLM vs cloud demo | `arka.demo.scenario = vllm-vs-cloud-latency` |
| RAG cascade demo | `arka.demo.scenario = rag-supermemory-cascade` |
| Router split demo | `arka.demo.scenario = semantic-router-split` |
| Symbolic routes only | `name = arka.route` AND `arka.route.decision = symbolic` |
| LLM routes only | `name = arka.route` AND `arka.route.decision = llm` |
| MCP connections | `name = arka.mcp.connect` OR `name = arka.mcp.call_tool` |
| SigNoz MCP tools | `name = arka.tool.signoz_mcp` OR `name = arka.tool.mcp` |
| Exception stack traces | `exception.type` exists OR `arka.demo.scenario = exception-stack-traces` |

## Recommended alerts

Bundled alert JSON (importable / API-ready) lives in [`../alerts/`](../alerts/).

Create via CLI (requires `SIGNOZ_API_KEY` from SigNoz → Settings → Service Accounts):

```bash
arka signoz alert-create agent-error-spike
arka signoz alert-list
```

| Alert | Slug | Condition | Severity |
| ----- | ---- | --------- | -------- |
| Agent error spike | `agent-error-spike` | `service.name = arka` AND `status = error` count > 5 in 10m | Warning |
| LLM p99 latency | `llm-p99-latency` | `arka.llm.attempt` p99 duration > 30s for 5m | Warning |
| LLM token budget | `llm-token-budget` | sum `gen_ai.usage.total_tokens` > 50k in 15m | Warning |
| LLM failover burst | *(manual)* | `arka.llm.attempt_index > 2` count > 10 in 15m | Warning |
| Goal step timeout | *(manual)* | `arka.agent.goal.step` p99 duration > 30s for 5m | Critical |
| No agent traffic | *(manual)* | `arka.request` count = 0 for 1h (dev env) | Info |

Manual UI path: **Alerts → New alert rule** — use the filters above in Query Builder.

## Export for submission

After building dashboards and alerts:

```bash
# From SigNoz UI: Dashboard → ⋮ → Export JSON
cp ~/Downloads/arka-agent.json hackathon/signoz/dashboards/arka-agent-observability.json
```

Commit the exported JSON before final submission so judges can import your exact panels.
