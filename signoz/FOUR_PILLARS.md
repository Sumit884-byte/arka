# Four SigNoz observability pillars — Arka demo guide

How Arka maps to SigNoz's LLM observability story for hackathon judges.

## 1. End-to-end request tracing

**Claim:** Trace every step from user input to final response.

**Arka implementation:**
- Root span `arka.request` → `arka.route` → `arka.agent.goal` → tools → `arka.llm.attempt`
- Demo: `arka signoz demo-e2e --synthetic`

**SigNoz filter:** `arka.demo.scenario = e2e-observability-pillars`

**Judge script:** Open Traces → waterfall shows route → memory lookup → LLM → shell tool in one view.

---

## 2. Correlate LLM traces with system logs

**Claim:** Jump from a slow LLM trace to application logs without switching tools.

**Arka implementation:**
- `emit_log()` attaches `trace_id` / `span_id` from the active OTel span
- LLM completions emit structured logs with `gen_ai.*` attrs inside the same trace
- Self-heal failures emit `agent.self_heal` log events correlated to `arka.agent.goal.step`

**Demo:** Run `arka signoz demo-e2e --synthetic`, click `arka.llm.attempt` span → **Logs** tab shows `llm tokens gemini/...` with matching trace ID.

---

## 3. Token usage & cost analytics

**Claim:** Track input/output tokens by model and operation; budget alerts.

**Arka implementation:**
- Agno run metrics → span attrs: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens`, `arka.llm.estimated_cost_usd`
- Metric counter: `arka.llm.tokens` (by provider, model, token type)
- Alert: `arka signoz alert-create llm-token-budget`

**SigNoz panels (Query Builder):**
- Traces → `name = arka.llm.attempt` → sum `gen_ai.usage.total_tokens` → group by `gen_ai.request.model`
- Traces → avg `arka.llm.ttft_ms` vs avg `arka.llm.duration_ms` (inference vs total latency)

---

## 4. Powerful alerts & custom dashboards

**Claim:** Alert on trace attributes — error rates, P99 latency, token limits.

**Bundled alerts** (`signoz/alerts/`):

| Slug | Fires when |
| ---- | ---------- |
| `agent-error-spike` | >5 error spans (`service.name = arka`) in 10m |
| `llm-p99-latency` | p99 `arka.llm.duration_ms` > 30s on `arka.llm.attempt` |
| `llm-token-budget` | sum `gen_ai.usage.total_tokens` > 50k in 15m |

```bash
arka signoz alert-create --all   # needs SIGNOZ_API_KEY
```

**Dashboard stub:** [`dashboards/arka-agent-observability.stub.json`](dashboards/arka-agent-observability.stub.json) + panel recipes in [`dashboards/README.md`](dashboards/README.md).

---

## One-command judge demo

```bash
OTEL_TRACES_ENABLED=1 SIGNOZ_ENDPOINT=http://localhost:4318
arka signoz demo-e2e --synthetic
arka signoz demo-scenarios --synthetic   # all scenarios including E2E
```

Open http://localhost:8080/traces and walk through all four pillars in ~2 minutes.

---

## Exception recording (automatic stack traces)

**Claim:** Record exceptions automatically with detailed stack traces in SigNoz.

**Arka implementation:**
- Every `span()` context manager auto-records uncaught exceptions via `record_exception()`
- `mark_error(span, message, exc=exc)` attaches `exception.type`, `exception.message`, `exception.stacktrace`
- Correlated error logs include the same stack trace and trace ID

**Demo:**

```bash
arka signoz demo-exceptions --synthetic
```

**SigNoz filter:** `arka.demo.scenario = exception-stack-traces`

**Judge script:** Click an error span → **Events** or span details → view full Python stack trace. Jump to **Logs** tab on the same trace.
