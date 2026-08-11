# SigNoz Publish

One-shot workflow for the Arka + SigNoz hackathon submission: update `signoz/BLOG.md`, commit and push to GitHub, deploy the landing page to Vercel.

## Requirements

- **git** with a configured remote (`origin`)
- **vercel** CLI (`npm i -g vercel`, `vercel login`, `cd landing && vercel link`)
- Optional: **gh** CLI for GitHub auth (`brew install gh`)
- Optional: LLM API key for blog generation (`GROQ_API_KEY` or configured provider)

## CLI

```bash
# Preview plan (no destructive actions)
arka signoz_publish --dry-run -m "Update hackathon blog"

# Execute full flow
arka signoz_publish --yes -m "Update SigNoz submission narrative"

# Generate blog from topic, then push + deploy
arka signoz_publish --yes --topic "new demo screenshots" -m "Refresh SigNoz demo media"

# Preflight checks
arka signoz_publish check
```

## Natural language

- "signoz publish push to github and deploy vercel"
- "publish signoz hackathon update blog and push"
- "signoz publish --topic observability demo"

## Safety

- Without `--yes`, only prints a preview plan
- Commit requires `-m/--message` or `--yes` (auto-generated message)
- `--dry-run` simulates git push and vercel deploy without executing
- `--skip-blog`, `--skip-git`, `--skip-deploy` for partial runs

## Limitations

- Vercel deploy targets `landing/` by default (`--vercel-dir`)
- Blog LLM generation needs a configured LLM provider; falls back to appending an update section
- Does not create GitHub releases or Devpost submissions — git push + Vercel only
