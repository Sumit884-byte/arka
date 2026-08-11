#!/usr/bin/env python3
"""n8n workflow automation integration — thin guide over remote_server and webhook."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys


def _backend_url() -> str:
    return (
        os.environ.get("ARKA_BACKEND_URL")
        or os.environ.get("ARKA_REMOTE_URL")
        or os.environ.get("REMOTE_URL")
        or "http://127.0.0.1:8765"
    ).rstrip("/")


def _backend_token() -> str:
    return (
        os.environ.get("ARKA_BACKEND_TOKEN")
        or os.environ.get("ARKA_REMOTE_TOKEN")
        or os.environ.get("REMOTE_TOKEN")
        or os.environ.get("WEBHOOK_TOKEN")
        or ""
    ).strip()


def _webhook_info() -> dict[str, object]:
    try:
        from arka.integrations.webhook import status_info

        return status_info()
    except ImportError:
        host = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
        port = int(os.environ.get("WEBHOOK_PORT", "8767"))
        return {
            "enabled": os.environ.get("WEBHOOK_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on"),
            "host": host,
            "port": port,
            "token_set": bool(_backend_token()),
            "inbox_url": f"http://{host}:{port}/v1/inbox",
            "health_url": f"http://{host}:{port}/v1/health",
        }


def status_payload() -> dict[str, object]:
    webhook = _webhook_info()
    token_set = bool(_backend_token())
    return {
        "backend_url": _backend_url(),
        "agent_url": f"{_backend_url()}/v1/agent",
        "backend_health_url": f"{_backend_url()}/v1/health",
        "webhook_enabled": bool(webhook.get("enabled")),
        "webhook_inbox_url": webhook.get("inbox_url"),
        "webhook_health_url": webhook.get("health_url"),
        "token_set": token_set,
        "message_sessions": os.environ.get("MESSAGE_SESSIONS", "1").strip() not in ("0", "false", "no", "off"),
    }


def cmd_status(args: argparse.Namespace) -> int:
    info = status_payload()
    if args.json:
        print(json.dumps(info, indent=2))
        return 0

    print("Arka n8n integration")
    print(f"Remote agent: {info['agent_url']}")
    print(f"Remote health: {info['backend_health_url']}")
    print(f"Webhook inbox: {info['webhook_inbox_url']}")
    print(f"Token configured: {'yes' if info['token_set'] else 'no'}")
    print(f"Webhook enabled: {'yes' if info['webhook_enabled'] else 'no'}")
    print(f"Session continuity: {'on' if info['message_sessions'] else 'off'}")
    print("")
    print("Start services:")
    print("  arka serve                              # remote API on :8765")
    print("  WEBHOOK_ENABLED=1 arka webhook serve    # verified inbox on :8767")
    print("")
    print("n8n HTTP Request (agent):")
    print(f"  POST {info['agent_url']}")
    print('  Header Authorization: Bearer <REMOTE_TOKEN>')
    print('  JSON body: {"text":"{{ $json.prompt }}","remote_speak":false}')
    print("")
    print("n8n HTTP Request (inbox + sessions):")
    print(f"  POST {info['webhook_inbox_url']}")
    print('  Header Authorization: Bearer <WEBHOOK_TOKEN or REMOTE_TOKEN>')
    print(
        '  JSON body: {"text":"{{ $json.message }}","source":"n8n",'
        '"chat_id":"{{ $json.session_id || \"default\" }}"}'
    )
    print("")
    print("Docs: arka n8n example")
    return 0 if info["token_set"] else 1


def _agent_node() -> dict[str, object]:
    url = f"{_backend_url()}/v1/agent"
    return {
        "name": "Arka Agent",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "parameters": {
            "method": "POST",
            "url": url,
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "Bearer {{ $env.REMOTE_TOKEN }}"},
                    {"name": "Content-Type", "value": "application/json"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": '={"text": {{ JSON.stringify($json.prompt) }}, "remote_speak": false}',
            "options": {"timeout": 600000},
        },
        "notes": "Full Arka agent via remote_server — start with: arka serve",
    }


def _inbox_node() -> dict[str, object]:
    webhook = _webhook_info()
    url = str(webhook.get("inbox_url") or "http://127.0.0.1:8767/v1/inbox")
    return {
        "name": "Arka Webhook Inbox",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "parameters": {
            "method": "POST",
            "url": url,
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "Bearer {{ $env.WEBHOOK_TOKEN || $env.REMOTE_TOKEN }}"},
                    {"name": "Content-Type", "value": "application/json"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": (
                '={"text": {{ JSON.stringify($json.message) }}, "source": "n8n", '
                '"chat_id": {{ JSON.stringify($json.session_id || "default") }}}'
            ),
            "options": {"timeout": 300000},
        },
        "notes": "Verified ingress with session continuity — WEBHOOK_ENABLED=1 arka webhook serve",
    }


def _curl_examples() -> str:
    token = _backend_token() or "$REMOTE_TOKEN"
    backend = _backend_url()
    webhook = _webhook_info()
    inbox = webhook.get("inbox_url", "http://127.0.0.1:8767/v1/inbox")
    return f"""# Remote agent (/v1/agent) — run: arka serve
curl -s {backend}/v1/agent \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer {token}" \\
  -d '{{"text":"summarize open PRs","remote_speak":false}}'

# Webhook inbox (/v1/inbox) — run: WEBHOOK_ENABLED=1 arka webhook serve
curl -s {inbox} \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer {token}" \\
  -d '{{"text":"remind me to review logs","source":"n8n","chat_id":"workflow-1"}}'

# Health checks
curl -s {backend}/v1/health
curl -s {webhook.get("health_url", "http://127.0.0.1:8767/v1/health")} \\
  -H "Authorization: Bearer {token}"
"""


def cmd_example(args: argparse.Namespace) -> int:
    payload = {
        "curl": _curl_examples().strip(),
        "n8n_http_request_agent": _agent_node(),
        "n8n_http_request_inbox": _inbox_node(),
        "n8n_to_arka": {
            "summary": "Use HTTP Request nodes to call Arka from n8n workflows.",
            "agent_endpoint": f"{_backend_url()}/v1/agent",
            "inbox_endpoint": _webhook_info().get("inbox_url"),
        },
        "arka_to_n8n": {
            "summary": "Add an n8n Webhook trigger node, copy its Production URL, then POST from Arka.",
            "curl_from_arka": (
                'curl -s "$N8N_WEBHOOK_URL" -H "Content-Type: application/json" '
                '-d \'{"event":"arka.completed","output":"{{ agent output }}"}\''
            ),
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("# Arka ↔ n8n examples\n")
    print("## curl\n")
    print(payload["curl"])
    print("\n## n8n HTTP Request — agent node\n")
    print(json.dumps(payload["n8n_http_request_agent"], indent=2))
    print("\n## n8n HTTP Request — inbox node (session continuity)\n")
    print(json.dumps(payload["n8n_http_request_inbox"], indent=2))
    print("\n## Arka → n8n (Webhook trigger)\n")
    print(payload["arka_to_n8n"]["summary"])
    print(payload["arka_to_n8n"]["curl_from_arka"])
    return 0


def wants_n8n(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if re.match(r"(?i)^(?:arka\s+)?n8n(?:\s+status|\s+example|\s+help|\s+--help)?$", clean):
        return True
    if re.match(r"(?i)^n8n\b", clean):
        return True
    if re.search(r"(?i)\bn8n\b.*\b(?:workflow|automation|integrat)", clean):
        return True
    if re.search(r"(?i)\b(?:workflow\s+automation|connect\s+arka\s+to\s+n8n)\b", clean):
        return True
    return False


def route_command(text: str) -> str:
    if not wants_n8n(text):
        return ""
    clean = (text or "").strip()
    if re.match(r"(?i)^(?:arka\s+)?n8n\s+status$", clean):
        return "n8n status"
    if re.match(r"(?i)^(?:arka\s+)?n8n\s+example$", clean):
        return "n8n example"
    if re.match(r"(?i)^(?:arka\s+)?n8n\s+help$", clean):
        return "n8n status"
    return "n8n status"


def main(argv: list[str] | None = None) -> int:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    raw = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(description="Arka n8n workflow integration")
    sub = parser.add_subparsers(dest="cmd")

    p_status = sub.add_parser("status", help="Show endpoints and n8n HTTP Request hints")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_example = sub.add_parser("example", help="Print curl and n8n node JSON snippets")
    p_example.add_argument("--json", action="store_true")
    p_example.set_defaults(func=cmd_example)

    if not raw or raw[0] in ("-h", "--help", "help"):
        parser.print_help()
        return 0

    args = parser.parse_args(raw)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
