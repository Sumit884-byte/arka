#!/usr/bin/env python3
"""Verified webhook ingress for external channels — token auth + security gates."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

CACHE = Path.home() / ".cache" / "fish-agent"
PID_PATH = CACHE / "arka_webhook.pid"


def _enabled() -> bool:
    return os.environ.get("WEBHOOK_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def _token() -> str:
    return (os.environ.get("WEBHOOK_TOKEN") or os.environ.get("REMOTE_TOKEN") or "").strip()


def status_info() -> dict[str, object]:
    """Structured webhook listener status (OpenClaw/Hermes-style gateway health)."""
    pid = ""
    if PID_PATH.is_file():
        try:
            pid = PID_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            pid = ""
    host = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
    port = int(os.environ.get("WEBHOOK_PORT", "8767"))
    return {
        "enabled": _enabled(),
        "host": host,
        "port": port,
        "token_set": bool(_token()),
        "pid": pid,
        "running": bool(pid),
        "inbox_url": f"http://{host}:{port}/v1/inbox",
        "health_url": f"http://{host}:{port}/v1/health",
    }


def health_payload() -> dict[str, object]:
    """Same shape as GET /v1/health for MCP clients."""
    info = status_info()
    return {
        "ok": True,
        "agent": os.environ.get("AGENT_NAME", "arka"),
        "webhook_enabled": bool(info["enabled"]),
        "running": bool(info["running"]),
        "listen": info["inbox_url"],
    }


def _verify_inbound(text: str) -> tuple[bool, str]:
    """Treat all webhook payloads as untrusted external content."""
    text = (text or "").strip()
    if not text:
        return False, "empty message"
    if len(text) > int(os.environ.get("WEBHOOK_MAX_CHARS", "4000")):
        return False, "message too long"
    try:
        from arka.core.security import verify_user_prompt, verify_web_query

        for check in (verify_user_prompt, verify_web_query):
            gate = check(text)
            if gate.status == "block":
                return False, gate.reason
    except ImportError:
        pass
    return True, ""


def _run_agent(text: str) -> tuple[str, int]:
    env = os.environ.copy()
    env["AGENT_SPEAK"] = "0"
    cmd = f"agent_hear {shlex.quote(text)}"
    try:
        proc = subprocess.run(
            ["fish", "-ic", cmd],
            capture_output=True,
            text=True,
            env=env,
            timeout=int(os.environ.get("WEBHOOK_TIMEOUT", "300")),
        )
    except subprocess.TimeoutExpired:
        return "Request timed out.", 124
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return out or "(no output)", int(proc.returncode or 0)


class WebhookHandler(BaseHTTPRequestHandler):
    server_version = "ArkaWebhook/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[arka-webhook] {self.address_string()} - {fmt % args}", flush=True)

    def _auth_ok(self) -> bool:
        token = _token()
        if not token:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip() == token
        return self.headers.get("X-Arka-Token", "").strip() == token

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/health":
            self._json(200, health_payload())
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not _auth_ok():
            self._json(401, {"ok": False, "error": "unauthorized — set WEBHOOK_TOKEN"})
            return
        path = urlparse(self.path).path
        if path not in ("/v1/inbox", "/v1/webhook", "/v1/agent"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        try:
            data = json.loads(self._read_body().decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid JSON"})
            return
        text = (data.get("text") or data.get("message") or "").strip()
        ok, reason = _verify_inbound(text)
        if not ok:
            self._json(403, {"ok": False, "error": reason})
            return
        source = (data.get("source") or data.get("channel") or "webhook").strip()[:64]
        chat_id = (data.get("chat_id") or data.get("session_id") or data.get("from") or "default").strip()[:64]
        session_ctx = ""
        try:
            from arka.integrations.message_sessions import context_for, is_silence_token, push

            push(source, chat_id, "user", text)
            session_ctx = context_for(source, chat_id)
        except ImportError:
            is_silence_token = lambda _t: False  # noqa: E731
        try:
            from arka.integrations.heartbeat import ping

            ping(f"webhook.{source}", source="webhook")
        except ImportError:
            pass
        agent_text = text
        if session_ctx:
            agent_text = f"[Session continuity]\n{session_ctx}\n\n[Message]\n{text}"
        output, code = _run_agent(agent_text)
        try:
            from arka.integrations.message_sessions import is_silence_token, push

            if output and not is_silence_token(output):
                push(source, chat_id, "assistant", output)
        except ImportError:
            pass
        silent = bool(output and is_silence_token(output))
        self._json(
            200,
            {
                "ok": code == 0,
                "exit_code": code,
                "output": "" if silent else output,
                "silent": silent,
                "source": source,
                "chat_id": chat_id,
            },
        )


def serve() -> int:
    if not _enabled():
        print("Webhook disabled. Set WEBHOOK_ENABLED=1 and WEBHOOK_TOKEN in .env", file=sys.stderr)
        return 1
    if not _token():
        print("WEBHOOK_TOKEN (or REMOTE_TOKEN) required.", file=sys.stderr)
        return 1
    host = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
    port = int(os.environ.get("WEBHOOK_PORT", "8767"))
    server = ThreadingHTTPServer((host, port), WebhookHandler)
    CACHE.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    print(f"Arka webhook listening on http://{host}:{port} (POST /v1/inbox)")
    print("Auth: Authorization: Bearer <WEBHOOK_TOKEN>  or  X-Arka-Token header")

    def _stop(*_args: object) -> None:
        server.shutdown()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        server.serve_forever()
    finally:
        PID_PATH.unlink(missing_ok=True)
    return 0


def main() -> int:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="Arka verified webhook ingress")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve").set_defaults(func=lambda _a: serve())
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")

    def _status(args: argparse.Namespace) -> int:
        info = status_info()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print(f"Webhook: {'on' if info['enabled'] else 'off'}")
            print(f"Listen: {info['inbox_url']}")
            print(f"Token configured: {info['token_set']}")
            if info["pid"]:
                print(f"PID: {info['pid']}")
        return 0

    p.set_defaults(func=_status)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
