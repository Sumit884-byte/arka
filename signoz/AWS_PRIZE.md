# AWS Builder Center prize — Best use of AWS

**Prize:** Amazon Echo Dot for every team member.

**Eligibility (per hackathon rules):** [Sign up to AWS Builder Center](https://builder.aws.com/) and **build with AWS**.

Arka already supports **Amazon Bedrock** in the LLM fallback chain — the fastest path is: **Bedrock inference + SigNoz observability**, not redeploying the whole stack.

---

## 1. Sign up (required)

1. Create a profile at [AWS Builder Center](https://builder.aws.com/) — **mandatory for AWS prize eligibility**
2. Note your Builder Center username/URL for the Devpost submission
3. **$100 AWS credits** (all participants): email [contact@wemakedevs.org](mailto:contact@wemakedevs.org)
4. (Optional) Publish a build story on Builder Center — required for **Best blog** prize

---

## 2. Enable Amazon Bedrock

In [AWS Console → Bedrock](https://console.aws.amazon.com/bedrock/):

1. **Model access** — enable at least one model (e.g. `Claude 3.5 Sonnet` or `Amazon Nova Lite`)
2. **IAM** — user/role with `bedrock:InvokeModel` (or use access keys for dev)

Add to `~/.config/arka/.env`:

```env
# Existing SigNoz / OTel
OTEL_TRACES_ENABLED=1
OTEL_SERVICE_NAME=arka
SIGNOZ_ENDPOINT=http://localhost:4318

# AWS Bedrock
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_DEFAULT_REGION=us-east-1

# Prefer Bedrock for goal + agent tasks
AI_PREFERRED_PROVIDER=bedrock
AI_PREFERRED_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0
# or: amazon.nova-lite-v1:0

# Optional explicit chain
LLM_FALLBACK_AGENT=bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0,gemini:gemini-2.0-flash
```

If you use an OpenAI-compatible Bedrock gateway instead:

```env
BEDROCK_API_BASE=https://your-bedrock-gateway/v1
BEDROCK_API_KEY=...
```

---

## 3. Demo — Bedrock + SigNoz (5 min)

```bash
arka signoz status
arka goal -y -n 3 "summarize the README in one sentence"
```

**In SigNoz → Traces**, filter:

```
service.name = arka AND gen_ai.provider.name = bedrock
```

Show judges:

| What | Where in SigNoz |
| ---- | ---------------- |
| Bedrock LLM calls | `arka.llm.attempt` spans · `gen_ai.provider.name = bedrock` |
| HTTP status | `http.status_code` on LLM spans |
| Agent waterfall | `arka.request` → `arka.agent.goal.step` → `arka.llm.attempt` |
| Metrics | `arka.llm.attempts` grouped by `gen_ai.provider.name` |
| Logs | `service.name = arka` · `llm ok bedrock/...` |

---

## 4. Stronger AWS story (optional)

Pick one if you want to stand out for “best use”:

| Approach | Effort | Pitch |
| -------- | ------ | ----- |
| **Bedrock only** (above) | Low | “Agent observability on AWS inference” |
| **SigNoz on EC2** | Medium | Run `foundryctl cast` on an EC2 instance; Arka local → remote SigNoz OTLP |
| **Arka on EC2** | Medium | Goal agent on EC2, Bedrock in-region, SigNoz Docker on same host |
| **Builder Center blog** | Low–med | Post walkthrough with screenshots + trace waterfall |

---

## 5. Submission disclosure (copy-paste)

```markdown
**AWS Builder Center:** [your profile URL]

**Build with AWS:**
- Amazon Bedrock for agent LLM inference (`gen_ai.provider.name = bedrock` in SigNoz traces)
- Region: us-east-1 (or your region)
- Model: anthropic.claude-3-5-sonnet-20241022-v2:0 (or Nova)

**Demo:** `arka goal` → Bedrock → OTLP traces/metrics/logs → SigNoz UI
```

---

## References

- [Amazon Bedrock docs](https://docs.aws.amazon.com/bedrock/)
- [AWS Builder Center](https://builder.aws.com/)
- Arka Bedrock env: `src/arka/env.example` (`BEDROCK_*`, `AWS_*`)
- [Hackathon README](README.md) · [MCP integration](MCP_INTEGRATION.md)
