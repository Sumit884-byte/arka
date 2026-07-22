# SigNoz Agent Skills for Cursor (Arka hackathon)

Use the official [SigNoz Agent Skills & Plugin](https://signoz.io/docs/ai/agent-skills/?agent-client=cursor) so Cursor can query Arka traces, build dashboards, create alerts, and investigate failures — without leaving the editor.

## Prerequisites

```bash
arka signoz setup -y
curl -fsS http://localhost:8000/livez && echo " MCP OK"
curl -fsS http://localhost:8080/api/v1/health && echo " SigNoz UI OK"
```

Create a SigNoz API key: http://localhost:8080 → **Settings → Service Accounts → Add Key**

Add to `.env`:

```bash
SIGNOZ_API_KEY=<your-key>
```

## Recommended — SigNoz plugin (skills + MCP bundled)

The plugin is not on the public Cursor Marketplace yet. Install via **Team Marketplace**:

1. **Cursor → Settings → Plugins → Team Marketplaces**
2. Add marketplace URL: `https://github.com/SigNoz/agent-skills`
3. Install the **`signoz`** plugin from the marketplace panel
4. In Cursor Agent chat, run:

   ```
   /signoz-mcp-setup http://localhost:8000/mcp
   ```

   For SigNoz Cloud use `https://mcp.<region>.signoz.cloud/mcp` instead (`us`, `eu`, `in`, etc.).

5. **Reload Cursor**, then open **Settings → MCP** and complete authentication for the `signoz` server if prompted.

### What you get

The plugin bundles MCP registration plus skills that auto-activate for matching tasks ([full list](https://signoz.io/docs/ai/agent-skills/)):

| Skill | Use with Arka |
| ----- | ------------- |
| `signoz-generating-queries` | Query `service.name = arka` traces, logs, metrics |
| `signoz-creating-dashboards` | Import/build Arka agent dashboards |
| `signoz-creating-alerts` | Create rules for error spikes, P99 latency, token budget |
| `signoz-investigating-alerts` | Diagnose why `agent-error-spike` fired |
| `signoz-explaining-dashboards` | Explain hackathon dashboard panels to judges |
| `signoz-setting-up-observability` | Full SLI/SLO + dashboard + alert workflow |

## Fallback — manual MCP + individual skills

If the plugin is unavailable:

```bash
# 1. MCP config (copy and add your API key)
cp .cursor/mcp.json.example .cursor/mcp.json
# edit SIGNOZ-API-KEY

# 2. Optional: install individual skills (any skills.sh-compatible agent)
npx skills add SigNoz/agent-skills --skill signoz-generating-queries
npx skills add SigNoz/agent-skills --skill signoz-creating-alerts
npx skills add SigNoz/agent-skills --skill signoz-creating-dashboards
```

Or use the CLI helper:

```bash
arka signoz cursor-setup --write
```

## Emit traces first, then query in Cursor

```bash
OTEL_TRACES_ENABLED=1 SIGNOZ_ENDPOINT=http://localhost:4318
arka signoz demo-scenarios --synthetic
arka signoz demo-exceptions --synthetic
```

### Example Cursor prompts (after plugin/MCP connected)

```
Why did the Arka agent error spike alert fire? Show related spans and logs.
```

```
Create a dashboard panel for gen_ai.usage.total_tokens grouped by gen_ai.request.model where service.name = arka
```

```
Show the trace waterfall for arka.demo.scenario = exception-stack-traces and explain the stack traces
```

```
Compare p99 arka.llm.duration_ms vs arka.llm.ttft_ms for vllm-cloud vs gemini on arka.llm.attempt spans
```

```
Import alert rules from signoz/alerts/ for agent-error-spike and llm-token-budget
```

## Arka-native MCP (traced in SigNoz)

Arka also calls SigNoz MCP from Python with OTel spans (`arka.mcp.*`):

```bash
arka signoz mcp ping
arka signoz mcp tools
ARKA_MCP_SELF_HEAL=1 arka goal "..."
```

See [MCP_INTEGRATION.md](MCP_INTEGRATION.md) and [FOUR_PILLARS.md](FOUR_PILLARS.md).

## Troubleshooting

| Issue | Fix |
| ----- | --- |
| Plugin not visible | Use Team Marketplace URL above; public marketplace may not list it yet |
| MCP `401` | Set `SIGNOZ-API-KEY` in MCP headers or run `/signoz-mcp-setup` again |
| Empty trace results | Run `arka signoz demo-scenarios --synthetic` first |
| Skills without MCP | skills.sh installs skill files only — MCP must be connected separately |

## References

- [Agent Skills & Plugin — Cursor](https://signoz.io/docs/ai/agent-skills/?agent-client=cursor)
- [SigNoz skills on skills.sh](https://skills.sh/signoz/agent-skills)
- [GitHub: SigNoz/agent-skills](https://github.com/SigNoz/agent-skills)
- [SigNoz MCP Server](https://signoz.io/docs/ai/signoz-mcp-server/)
