# SigNoz alert rules (Arka hackathon)

Bundled trace-based alert definitions for the Agents of SigNoz hackathon. Each JSON file uses SigNoz alert schema **v5** with `queries` (not deprecated `builderQueries`).

## Create via CLI

```bash
# 1. Create API key: SigNoz UI → Settings → Service Accounts → Add Key
# 2. Add to .env:
#    SIGNOZ_API_KEY=<your-key>

arka signoz alert-create agent-error-spike
arka signoz alert-list
```

Dry-run (no API key needed):

```bash
arka signoz alert-create agent-error-spike --dry-run
```

## Bundled rules

| File | Alert name | Fires when |
| ---- | ---------- | ---------- |
| `agent-error-spike.json` | Arka agent error spike | >5 error spans with `service.name = arka` in 10m window |
| `llm-p99-latency.json` | Arka LLM p99 latency high | p99 `arka.llm.duration_ms` > 30s on `arka.llm.attempt` |
| `llm-token-budget.json` | Arka LLM token budget spike | sum `gen_ai.usage.total_tokens` > 50k in 15m |

## Manual import

If the API is unavailable, open **Alerts → New alert rule** and recreate using the filter expressions in [`../dashboards/README.md`](../dashboards/README.md).
