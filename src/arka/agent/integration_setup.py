"""One-command setup and diagnostics for integrations that need API keys."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from pathlib import Path

from arka.agent import search_setup

PROVIDERS = {
    "serper": ("SERPER_API_KEY", "https://serper.dev/api-key", "web search"),
    "tavily": ("TAVILY_API_KEY", "https://app.tavily.com", "web search"),
    "brave": ("BRAVE_SEARCH_API_KEY", "https://brave.com/search/api/", "web search"),
    "context7": ("CONTEXT7_API_KEY", "https://context7.com", "documentation search"),
    "signoz": ("SIGNOZ_API_KEY", "https://signoz.io", "observability"),
    "supermemory": ("SUPERMEMORY_API_KEY", "https://supermemory.ai", "code-aware memory"),
    "pexels": ("PEXELS_API_KEY", "https://www.pexels.com/api/", "stock media"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/keys", "multi-model routing"),
    "openai": ("OPENAI_API_KEY", "https://platform.openai.com/api-keys", "LLM and embeddings"),
    "anthropic": ("ANTHROPIC_API_KEY", "https://console.anthropic.com/settings/keys", "Claude models"),
    "railway": ("RAILWAY_TOKEN", "https://railway.app/account/tokens", "backend deployment"),
    "vercel": ("VERCEL_TOKEN", "https://vercel.com/account/tokens", "frontend deployment"),
    "github": ("GH_TOKEN", "https://github.com/settings/tokens", "issues and pull requests"),
    "slack": ("SLACK_BOT_TOKEN", "https://api.slack.com/apps", "team notifications"),
    "google": ("GOOGLE_API_KEY", "https://aistudio.google.com/apikey", "Gemini and Google APIs"),
    "sentry": ("SENTRY_AUTH_TOKEN", "https://sentry.io/orgredirect/organizations/:orgslug/settings/auth-tokens/", "error monitoring"),
    "linear": ("LINEAR_API_KEY", "https://linear.app/settings/api", "issue tracking"),
    "discord": ("DISCORD_TOKEN", "https://discord.com/developers/applications", "team notifications"),
    "huggingface": ("HF_TOKEN", "https://huggingface.co/settings/tokens", "open model inference"),
    "mistral": ("MISTRAL_API_KEY", "https://console.mistral.ai/api-keys/", "Mistral models"),
    "cohere": ("COHERE_API_KEY", "https://dashboard.cohere.com/api-keys", "Cohere models"),
    "together": ("TOGETHER_API_KEY", "https://api.together.ai/settings/api-keys", "Together models"),
    "notion": ("NOTION_TOKEN", "https://www.notion.so/my-integrations", "workspace pages"),
    "jira": ("JIRA_API_TOKEN", "https://id.atlassian.com/manage-profile/security/api-tokens", "Jira issues"),
    "teams": ("TEAMS_WEBHOOK_URL", "https://learn.microsoft.com/microsoftteams/platform/webhooks-and-connectors", "team notifications"),
    "supabase": ("SUPABASE_ACCESS_TOKEN", "https://supabase.com/dashboard/account/tokens", "database and auth"),
    "firebase": ("FIREBASE_TOKEN", "https://firebase.google.com/docs/cli#sign-in-test-cli", "app backend"),
    "stripe": ("STRIPE_SECRET_KEY", "https://dashboard.stripe.com/apikeys", "payments"),
    "netlify": ("NETLIFY_AUTH_TOKEN", "https://app.netlify.com/user/applications", "frontend deployment"),
    "render": ("RENDER_API_KEY", "https://dashboard.render.com/u/settings#api-keys", "backend deployment"),
    "fly": ("FLY_API_TOKEN", "https://fly.io/user/personal_access_tokens", "backend deployment"),
    "dockerhub": ("DOCKERHUB_TOKEN", "https://hub.docker.com/settings/security", "container registry"),
    "npm": ("NPM_TOKEN", "https://www.npmjs.com/settings/~/tokens", "JavaScript package registry"),
    "pypi": ("PYPI_TOKEN", "https://pypi.org/manage/account/token/", "Python package registry"),
    "postgres": ("DATABASE_URL", "https://www.postgresql.org/docs/", "PostgreSQL connection"),
    "redis": ("REDIS_URL", "https://redis.io/docs/latest/", "Redis connection"),
    "mongodb": ("MONGODB_URI", "https://www.mongodb.com/docs/", "MongoDB connection"),
    "datadog": ("DD_API_KEY", "https://app.datadoghq.com/organization-settings/api-keys", "Datadog observability"),
    "newrelic": ("NEW_RELIC_LICENSE_KEY", "https://one.newrelic.com/api-keys", "New Relic observability"),
    "langfuse": ("LANGFUSE_PUBLIC_KEY", "https://cloud.langfuse.com", "LLM observability"),
    "langsmith": ("LANGCHAIN_API_KEY", "https://smith.langchain.com/settings", "LLM tracing and evaluation"),
    "wandb": ("WANDB_API_KEY", "https://wandb.ai/authorize", "ML experiment tracking"),
    "modal": ("MODAL_TOKEN_ID", "https://modal.com/settings", "serverless compute"),
    "e2b": ("E2B_API_KEY", "https://e2b.dev/dashboard", "remote code sandboxes"),
    "ollama": ("OLLAMA_API_KEY", "https://ollama.com", "local model runtime"),
    "vllm": ("VLLM_API_KEY", "https://docs.vllm.ai", "local model runtime"),
    "lmstudio": ("LMSTUDIO_API_KEY", "https://lmstudio.ai", "local model runtime"),
    "groq": ("GROQ_API_KEY", "https://console.groq.com/keys", "hosted model inference"),
    "replicate": ("REPLICATE_API_TOKEN", "https://replicate.com/account/api-tokens", "hosted model inference"),
    "cloudflare": ("CLOUDFLARE_API_TOKEN", "https://dash.cloudflare.com/profile/api-tokens", "DNS and edge deployment"),
    "digitalocean": ("DIGITALOCEAN_TOKEN", "https://cloud.digitalocean.com/account/api/tokens", "cloud deployment"),
    "hetzner": ("HCLOUD_TOKEN", "https://console.hetzner.cloud/projects", "cloud deployment"),
    "resend": ("RESEND_API_KEY", "https://resend.com/api-keys", "transactional email"),
    "sendgrid": ("SENDGRID_API_KEY", "https://app.sendgrid.com/guide/integrate/api_keys", "transactional email"),
    "clerk": ("CLERK_SECRET_KEY", "https://dashboard.clerk.com/last-active?path=api-keys", "authentication"),
    "auth0": ("AUTH0_CLIENT_SECRET", "https://manage.auth0.com/dashboard", "authentication"),
    "posthog": ("POSTHOG_API_KEY", "https://app.posthog.com/project/settings", "product analytics"),
    "amplitude": ("AMPLITUDE_API_KEY", "https://app.amplitude.com/settings/projects", "product analytics"),
    "launchdarkly": ("LAUNCHDARKLY_API_KEY", "https://app.launchdarkly.com/settings/authorization", "feature flags"),
    "statsig": ("STATSIG_SERVER_SECRET", "https://console.statsig.com/api_keys", "feature flags"),
    "telegram": ("TELEGRAM_BOT_TOKEN", "https://t.me/BotFather", "bot notifications"),
    "whatsapp": ("WHATSAPP_ACCESS_TOKEN", "https://developers.facebook.com/docs/whatsapp", "WhatsApp messaging"),
}
URL_VARS = {"signoz": "SIGNOZ_URL", "supabase": "SUPABASE_URL", "jira": "JIRA_BASE_URL", "linear": "LINEAR_BASE_URL", "ollama": "OLLAMA_BASE_URL", "vllm": "VLLM_BASE_URL", "lmstudio": "LMSTUDIO_BASE_URL"}
CLI_TOOLS = {
    "github": "gh", "railway": "railway", "vercel": "vercel", "netlify": "netlify",
    "fly": "fly", "firebase": "firebase", "supabase": "supabase", "dockerhub": "docker",
    "npm": "npm", "pypi": "twine",
}
ALIASES = {
    "gh": "github", "gcp": "google", "gemini": "google", "ctx7": "context7",
    "hf": "huggingface", "hugging-face": "huggingface",
}


def env_file() -> Path:
    """Compatibility wrapper allowing callers/tests to override config location."""
    return search_setup.env_file()


def main(argv: list[str] | None = None) -> int:
    # Load only Arka's configured dotenv file; do not import arbitrary shell
    # state or overwrite explicitly supplied environment variables.
    parser = argparse.ArgumentParser(description="Configure Arka integrations")
    sub = parser.add_subparsers(dest="action")
    setup = sub.add_parser("setup")
    setup.add_argument("provider", choices=[*sorted(PROVIDERS), *sorted(ALIASES), "all"])
    setup.add_argument("--key", default="")
    setup.add_argument("--key-stdin", action="store_true", help="read the key from stdin")
    setup.add_argument("--key-file", default="", help="read the key from a local secret file")
    setup.add_argument("--config-dir", default="", help="write to this config directory instead of the global one")
    init = sub.add_parser("init", help="create a project-local .env.example")
    init.add_argument("--config-dir", default=".")
    init.add_argument("--force", action="store_true")
    init.add_argument("--json", action="store_true")
    init.add_argument("--gitignore", action="store_true", help="ensure .env is ignored")
    setup.add_argument("--url", default="", help="optional self-hosted or enterprise base URL")
    setup.add_argument("--json", action="store_true")
    status = sub.add_parser("status", aliases=["list"])
    status.add_argument("--provider", choices=[*sorted(PROVIDERS), *sorted(ALIASES)], default="")
    status.add_argument("--json", action="store_true")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--provider", choices=[*sorted(PROVIDERS), *sorted(ALIASES)], default="")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--fix", action="store_true", help="repair unsafe .env permissions")
    remove = sub.add_parser("remove")
    remove.add_argument("provider", choices=[*sorted(PROVIDERS), *sorted(ALIASES)])
    remove.add_argument("--yes", action="store_true")
    remove.add_argument("--json", action="store_true")
    remove.add_argument("--config-dir", default="")
    args = parser.parse_args(argv)
    if getattr(args, "provider", "") in ALIASES:
        args.provider = ALIASES[args.provider]
    config_path = Path(args.config_dir).expanduser() / ".env" if getattr(args, "config_dir", "") else env_file()
    search_setup.load_saved_env(config_path)
    if args.action == "init":
        target = Path(args.config_dir).expanduser() / ".env.example"
        if target.exists() and not args.force:
            print(f"Already exists: {target}. Use --force to replace.", file=sys.stderr)
            return 2
        lines = ["# Generated by arka integration init", "# Add values to .env; never commit secrets.", ""]
        for provider, (name, _url, purpose) in PROVIDERS.items():
            lines.append(f"# {provider}: {purpose}")
            lines.append(f"{name}=")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        gitignore_updated = False
        if args.gitignore:
            gitignore = target.parent / ".gitignore"
            existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
            if ".env" not in {line.strip() for line in existing}:
                gitignore.write_text("\n".join([*existing, ".env"]).rstrip() + "\n", encoding="utf-8")
                gitignore_updated = True
        if args.json:
            print(json.dumps({"created": True, "path": str(target), "providers": len(PROVIDERS), "gitignore_updated": gitignore_updated}))
        else:
            print(f"Created {target}")
        return 0
    if args.action == "remove":
        name = PROVIDERS[args.provider][0]
        if not args.yes:
            print(f"Refusing to remove {name} without --yes.")
            return 2
        path = config_path
        if path.is_file():
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.split("=", 1)[0].strip() != name]
            path.write_text("\n".join(lines).rstrip() + ("\n" if lines else ""), encoding="utf-8")
        os.environ.pop(name, None)
        if args.json:
            print(json.dumps({"provider": args.provider, "env": name, "removed": True}))
        else:
            print(f"Removed {name} from Arka configuration.")
        return 0
    if args.action == "setup" and args.provider == "all":
        configured = 0
        configured_names = []
        for provider, (name, _url, _purpose) in PROVIDERS.items():
            if os.environ.get(name, "").strip():
                continue
            if not args.json:
                print(f"\nConfiguring {provider} ({name})")
            try:
                key = getpass.getpass("Key (leave blank to skip): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSetup cancelled.")
                return 130
            if key:
                search_setup._write_key(name, key, config_path)
                configured += 1
                configured_names.append(provider)
        if args.json:
            print(json.dumps({"configured": configured_names, "count": configured}))
        else:
            print(f"Configured {configured} integration(s).")
        return 0
    if args.action == "setup":
        name, url, purpose = PROVIDERS[args.provider]
        if args.url and args.provider not in URL_VARS:
            print(f"{args.provider} does not support a custom endpoint URL.", file=sys.stderr)
            return 2
        stdin_key = sys.stdin.read().strip() if args.key_stdin else ""
        file_key = ""
        if args.key_file:
            try:
                file_key = Path(args.key_file).expanduser().read_text(encoding="utf-8").strip()
            except OSError as exc:
                print(f"Could not read key file: {exc}", file=sys.stderr)
                return 2
        key = (args.key or stdin_key or file_key or os.environ.get(name, "")).strip()
        if not key:
            print(f"{args.provider} ({purpose}) — get a key at {url}")
            try:
                key = getpass.getpass(f"Paste {name} (hidden): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSetup cancelled.")
                return 130
            if not key:
                print(f"No key provided. Non-interactive form: arka integration setup {args.provider} --key <key>")
                return 2
        path = search_setup._write_key(name, key, config_path)
        if args.url and args.provider in URL_VARS:
            search_setup._write_key(URL_VARS[args.provider], args.url.strip().rstrip("/"), config_path)
        if args.json:
            result = {"provider": args.provider, "env": name, "configured": True, "path": str(path)}
            if args.url and args.provider in URL_VARS:
                result["url_env"] = URL_VARS[args.provider]
            print(json.dumps(result))
        else:
            print(f"Saved {name} to {path}")
        return 0
    if args.action in ("status", "list"):
        providers = {args.provider: PROVIDERS[args.provider]} if args.provider else PROVIDERS
        records = []
        for provider, (name, url, purpose) in providers.items():
            state = "configured" if os.environ.get(name, "").strip() else "missing"
            records.append({"provider": provider, "state": state, "env": name, "purpose": purpose, "url": url})
        if args.json:
            print(json.dumps(records, indent=2))
        else:
            for record in records:
                print(f"{record['provider']}\t{record['state']}\t{record['env']}\t{record['purpose']}")
        return 0
    if args.action == "doctor":
        providers = {args.provider: PROVIDERS[args.provider]} if args.provider else PROVIDERS
        missing = []
        configured = []
        for provider, (name, url, purpose) in providers.items():
            if not os.environ.get(name, "").strip():
                missing.append(provider)
            else:
                configured.append(provider)
        if missing and not args.json:
            print("Missing optional integrations: " + ", ".join(missing))
            print("Set only what you use; run `arka integration setup <name> --key <key>`.")
        cli_tools = {args.provider: CLI_TOOLS[args.provider]} if args.provider in CLI_TOOLS else CLI_TOOLS if not args.provider else {}
        unavailable = [f"{provider} (install `{binary}`)" for provider, binary in cli_tools.items() if not shutil.which(binary)]
        unsafe_permissions = bool(config_path.is_file() and config_path.stat().st_mode & 0o077)
        fixed_permissions = False
        if unsafe_permissions and args.fix:
            config_path.chmod(0o600)
            unsafe_permissions = False
            fixed_permissions = True
        if unsafe_permissions and not args.json:
            print(f"Unsafe permissions on {config_path}; run chmod 600 {config_path}")
        if unavailable and not args.json:
            print("Missing optional CLIs: " + ", ".join(unavailable))
        if not missing and not unavailable and not args.json:
            print("All registered integrations are configured.")
        if args.json:
            print(json.dumps({"configured_providers": configured, "missing_providers": missing, "missing_clis": unavailable, "unsafe_permissions": unsafe_permissions, "fixed_permissions": fixed_permissions}, indent=2))
        return 0
    parser.print_help()
    return 2
