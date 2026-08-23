#!/usr/bin/env python3
"""Arka inference API — OpenAI-compatible chat without MCP tools or skills."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from arka.integrations.ollama_tunnel import RateLimiter

CACHE = Path.home() / ".cache" / "fish-agent"
PID_PATH = CACHE / "arka_api.pid"
_CHAT_DEDUP_TTL = 5.0


def _enabled() -> bool:
    return os.environ.get("ARKA_API_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def _token() -> str:
    try:
        from arka.core.unified_api import api_token

        return api_token()
    except ImportError:
        return (os.environ.get("ARKA_API_TOKEN") or os.environ.get("REMOTE_TOKEN") or "").strip()


def _host() -> str:
    return os.environ.get("ARKA_API_HOST", "127.0.0.1").strip() or "127.0.0.1"


def _port() -> int:
    return int(os.environ.get("ARKA_API_PORT", "8768"))


def _rate_limit_rpm() -> int:
    try:
        return max(1, int(os.environ.get("ARKA_API_RPM", "60")))
    except ValueError:
        return 60


def _default_model() -> str:
    return (
        os.environ.get("AI_PREFERRED_MODEL") or os.environ.get("LLM_MODEL") or "arka"
    ).strip() or "arka"


def _api_only() -> bool:
    return os.environ.get("ARKA_API_ONLY", "1").strip().lower() in ("1", "true", "yes", "on")


def status_info() -> dict[str, object]:
    pid = ""
    if PID_PATH.is_file():
        try:
            pid = PID_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            pid = ""
    host = _host()
    port = _port()
    return {
        "enabled": _enabled(),
        "api_only": _api_only(),
        "host": host,
        "port": port,
        "token_set": bool(_token()),
        "pid": pid,
        "running": bool(pid),
        "health_url": f"http://{host}:{port}/v1/health",
        "chat_url": f"http://{host}:{port}/v1/chat/completions",
        "models_url": f"http://{host}:{port}/v1/models",
    }


def health_payload() -> dict[str, object]:
    info = status_info()
    return {
        "ok": True,
        "service": "arka-api",
        "agent": os.environ.get("AGENT_NAME", "arka"),
        "api_enabled": bool(info["enabled"]),
        "api_only": bool(info["api_only"]),
        "running": bool(info["running"]),
        "model": _default_model(),
    }


def _apply_api_only_mode() -> None:
    if not _api_only():
        return
    os.environ.setdefault("ARKA_MCP_ENABLE_PERSONAL_SKILLS", "0")
    try:
        from arka.core.just_ai import enable_just_ai

        enable_just_ai()
    except ImportError:
        os.environ.setdefault("JUST_AI", "1")


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("input_text")
                if text:
                    parts.append(str(text).strip())
            elif isinstance(block, str) and block.strip():
                parts.append(block.strip())
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _messages_to_prompt(messages: list[dict[str, Any]]) -> tuple[str, str]:
    system_parts: list[str] = []
    convo_parts: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip().lower()
        content = _message_text(msg.get("content"))
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            convo_parts.append(f"Assistant: {content}")
        else:
            convo_parts.append(content)
    system = "\n\n".join(system_parts) or "You are a helpful assistant."
    user = "\n\n".join(convo_parts)
    return system, user


def _chat_completion_dedup_key(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _run_chat_completion_impl(
    *,
    system: str,
    user: str,
    model: str,
    temperature: float,
) -> tuple[str, str, int]:
    try:
        from arka.llm.cli import llm_complete

        answer = llm_complete(system, user, temperature, task="chat", skill="api")
        return answer.strip(), model, 0
    except ImportError:
        try:
            from arka.llm.fallback import llm_complete as fallback_complete

            answer = fallback_complete(system, user, temperature, task="chat")
            return answer.strip(), model, 0
        except Exception as exc:
            return f"LLM unavailable: {exc}", model, 1
    except Exception as exc:
        return f"Completion failed: {exc}", model, 1


def run_chat_completion(payload: dict[str, Any]) -> tuple[str, str, int]:
    """Return (answer_text, model_id, exit_code)."""
    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return "", str(payload.get("model") or _default_model()), 1

    system, user = _messages_to_prompt(messages)
    if not user.strip():
        return "", str(payload.get("model") or _default_model()), 1

    model = str(payload.get("model") or _default_model())
    try:
        temperature = float(payload.get("temperature", 0.2))
    except (TypeError, ValueError):
        temperature = 0.2

    def _complete() -> tuple[str, str, int]:
        return _run_chat_completion_impl(
            system=system,
            user=user,
            model=model,
            temperature=temperature,
        )

    try:
        from arka.core.fetch_dedup import fetch_dedup_enabled, get_cache

        if fetch_dedup_enabled():
            key = _chat_completion_dedup_key(payload)
            return get_cache("arka_api_chat").get_or_fetch(key, _complete, ttl=_CHAT_DEDUP_TTL)
    except ImportError:
        pass
    return _complete()


def models_payload() -> dict[str, Any]:
    model = _default_model()
    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "arka",
            }
        ],
    }


def chat_completion_payload(answer: str, model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": max(1, len(answer.split())),
            "total_tokens": max(1, len(answer.split())),
        },
    }


class ArkaApiHandler(BaseHTTPRequestHandler):
    server_version = "ArkaAPI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[arka-api] {self.address_string()} - {fmt % args}", flush=True)

    def _client_key(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if forwarded:
            return forwarded
        if self.client_address:
            return self.client_address[0]
        return self.address_string()

    def _rate_limit_ok(self) -> bool:
        server = getattr(self, "server", None)
        if server is None:
            return True
        limiter: RateLimiter | None = getattr(server, "rate_limiter", None)
        if limiter is None:
            return True
        return limiter.allow(self._client_key())

    def _auth_ok(self) -> bool:
        token = _token()
        if not token:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip() == token
        return self.headers.get("X-Arka-Token", "").strip() == token

    def _reject(self, code: int, message: str) -> None:
        self._json(code, {"ok": False, "error": message})

    def _require_rate_limit(self) -> bool:
        if self._rate_limit_ok():
            return True
        self._reject(429, "rate limit exceeded")
        return False

    def _require_auth(self) -> bool:
        if self._auth_ok():
            return True
        self._reject(401, "unauthorized")
        return False

    def _json(self, code: int, payload: dict[str, Any]) -> None:
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
        if not self._require_rate_limit():
            return
        path = urlparse(self.path).path
        if path in ("/", "/v1/health", "/health"):
            self._json(200, health_payload())
            return
        if path == "/v1/models":
            if not self._require_auth():
                return
            self._json(200, models_payload())
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._require_rate_limit():
            return
        path = urlparse(self.path).path
        if path not in ("/v1/chat/completions", "/v1/complete"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        if not self._require_auth():
            return

        started = time.perf_counter()
        try:
            data = json.loads(self._read_body().decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid JSON"})
            return

        if path == "/v1/complete":
            text = str(data.get("prompt") or data.get("text") or "").strip()
            if not text:
                self._json(400, {"ok": False, "error": "missing prompt"})
                return
            data = {
                "messages": [{"role": "user", "content": text}],
                "model": data.get("model"),
                "temperature": data.get("temperature", 0.2),
            }

        answer, model, code = run_chat_completion(data)
        if code != 0 and not answer:
            self._json(400, {"ok": False, "error": "missing messages"})
            return

        self._json(200, chat_completion_payload(answer, model))
        try:
            from arka.telemetry.tracing import log_response_duration

            log_response_duration(
                f"http arka-api {path}",
                start=started,
                attributes={
                    "arka.http.path": path,
                    "arka.http.model": model,
                    "arka.exit_code": code,
                },
            )
        except ImportError:
            pass


def serve() -> int:
    if not _enabled():
        print("Arka API disabled. Set ARKA_API_ENABLED=1 in .env", file=sys.stderr)
        return 1
    if not _token():
        print("ARKA_API_TOKEN (or REMOTE_TOKEN) required.", file=sys.stderr)
        return 1

    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    _apply_api_only_mode()

    try:
        from arka.core.api_security import warn_if_insecure_startup

        warn_if_insecure_startup("arka-api")
    except ImportError:
        pass

    host = _host()
    port = _port()
    server = ThreadingHTTPServer((host, port), ArkaApiHandler)
    server.rate_limiter = RateLimiter(_rate_limit_rpm())  # type: ignore[attr-defined]
    CACHE.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    print(f"Arka API listening on http://{host}:{port}/v1/chat/completions")
    print("Inference only — no MCP tools or skill routing")
    print(f"Auth: Bearer token required on all routes except /v1/health (rpm={_rate_limit_rpm()})")

    def _stop(*_args: object) -> None:
        server.shutdown()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        server.serve_forever()
    finally:
        PID_PATH.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Arka inference API — OpenAI-compatible chat/completions (no tools or skills)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve").set_defaults(func=lambda _a: serve())
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")

    def _status(args: argparse.Namespace) -> int:
        info = status_info()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print(f"Arka API: {'on' if info['enabled'] else 'off'}")
            print(f"API-only mode: {'yes' if info['api_only'] else 'no'}")
            print(f"Listen: {info['chat_url']}")
            print(f"Token configured: {info['token_set']}")
            if info["pid"]:
                print(f"PID: {info['pid']}")
        return 0

    p.set_defaults(func=_status)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
