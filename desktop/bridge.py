#!/usr/bin/env python3
"""HTTP bridge for the Arka desktop app (fork of web/bridge.py with desktop paths)."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DESKTOP_DIR = Path(__file__).resolve().parent
REPO_ROOT = DESKTOP_DIR.parent
WEB_SESSION_CHANNEL = "web"

BRIDGE_HOST = os.environ.get("ARKA_BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("ARKA_BRIDGE_PORT", "8766"))
REMOTE_URL = (
    os.environ.get("ARKA_BACKEND_URL")
    or os.environ.get("ARKA_REMOTE_URL")
    or os.environ.get("REMOTE_URL")
    or "http://127.0.0.1:8765"
).rstrip("/")
REMOTE_TOKEN = (
    os.environ.get("ARKA_BACKEND_TOKEN")
    or os.environ.get("ARKA_REMOTE_TOKEN")
    or os.environ.get("REMOTE_TOKEN")
    or ""
).strip()
DIST_DIR = DESKTOP_DIR / "ui" / "dist"


def _bootstrap_env() -> None:
    src = REPO_ROOT / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass
    global REMOTE_TOKEN
    REMOTE_TOKEN = (
        os.environ.get("ARKA_BACKEND_TOKEN")
        or os.environ.get("ARKA_REMOTE_TOKEN")
        or os.environ.get("REMOTE_TOKEN")
        or ""
    ).strip()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Arka-Token")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


def _proxy_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    url = f"{REMOTE_URL}{path}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    tok = token if token is not None else REMOTE_TOKEN
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get("REMOTE_TIMEOUT", "600"))) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {"ok": False, "error": raw or exc.reason}
        return exc.code, data
    except urllib.error.URLError as exc:
        return 503, {"ok": False, "error": f"remote server unreachable at {REMOTE_URL}: {exc.reason}"}


def _capabilities_payload() -> dict:
    skill_dir = REPO_ROOT / "src" / "arka" / "agent"
    names = sorted(path.stem for path in skill_dir.glob("*.py") if path.stem != "__init__")
    names = [name for name in names if not name.startswith("_")]
    return {"ok": True, "dispatch_skills": names, "count": len(names), "source": "local"}


def _config_payload() -> dict:
    return {
        "ok": True,
        "app": "desktop",
        "has_token": bool(REMOTE_TOKEN),
        "remote_url": REMOTE_URL,
        "bridge_port": BRIDGE_PORT,
    }


def _route_payload(text: str) -> dict:
    from arka.router import route

    decision = route(text)
    return {
        "ok": True,
        "skill": decision.skill,
        "source": decision.source,
        "kind": decision.kind,
        "rule": decision.rule,
        "decision": decision.decision,
    }


def _sessions_resume(channel: str, chat_id: str, *, limit: int = 100) -> dict:
    from arka.integrations.message_sessions import resume_payload

    payload = resume_payload(channel, chat_id, limit=limit)
    return {"ok": True, **payload}


def _sessions_push(channel: str, chat_id: str, role: str, text: str) -> dict:
    from arka.integrations.message_sessions import push

    code, err = push(channel, chat_id, role, text)
    if code != 0:
        return {"ok": False, "error": err or "push failed"}
    return {"ok": True}


def _sessions_reset(channel: str, chat_id: str) -> dict:
    from arka.integrations.message_sessions import reset

    reset(channel, chat_id)
    return {"ok": True}


def _doctor_payload() -> dict:
    buf = io.StringIO()
    code = 1
    try:
        from contextlib import redirect_stdout

        from arka.cli import _cmd_doctor

        with redirect_stdout(buf):
            code = _cmd_doctor()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": code == 0, "output": buf.getvalue().strip(), "exit_code": code}


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "ArkaDesktopBridge/0.1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return (self.headers.get("X-Arka-Token") or REMOTE_TOKEN or "").strip()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Arka-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/health":
            status, data = _proxy_json("/v1/health")
            _json_response(self, status, data)
            return
        if path == "/v1/config":
            _json_response(self, 200, _config_payload())
            return
        if path == "/v1/capabilities":
            _json_response(self, 200, _capabilities_payload())
            return
        if path == "/v1/doctor":
            _json_response(self, 200, _doctor_payload())
            return
        if path == "/v1/sessions/resume":
            query = parse_qs(urlparse(self.path).query)
            channel = (query.get("channel") or [WEB_SESSION_CHANNEL])[0].strip() or WEB_SESSION_CHANNEL
            chat_id = (query.get("chat_id") or ["default"])[0].strip() or "default"
            try:
                limit = int((query.get("limit") or ["100"])[0])
            except ValueError:
                limit = 100
            try:
                _json_response(self, 200, _sessions_resume(channel, chat_id, limit=max(1, min(limit, 200))))
            except Exception as exc:
                _json_response(self, 500, {"ok": False, "error": str(exc)})
            return
        if path.startswith("/") and DIST_DIR.is_dir():
            rel = path.lstrip("/") or "index.html"
            file_path = (DIST_DIR / rel).resolve()
            if not str(file_path).startswith(str(DIST_DIR.resolve())):
                _json_response(self, 403, {"ok": False, "error": "forbidden"})
                return
            if file_path.is_dir():
                file_path = file_path / "index.html"
            if not file_path.is_file() and rel != "index.html":
                file_path = DIST_DIR / "index.html"
            if file_path.is_file():
                content = file_path.read_bytes()
                ctype = "text/html"
                if file_path.suffix == ".js":
                    ctype = "application/javascript"
                elif file_path.suffix == ".css":
                    ctype = "text/css"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
        _json_response(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            data = json.loads(self._read_body().decode("utf-8") or "{}")
        except json.JSONDecodeError:
            _json_response(self, 400, {"ok": False, "error": "invalid JSON"})
            return

        if path == "/v1/route":
            text = (data.get("text") or "").strip()
            if not text:
                _json_response(self, 400, {"ok": False, "error": "missing text"})
                return
            try:
                _json_response(self, 200, _route_payload(text))
            except Exception as exc:
                _json_response(self, 500, {"ok": False, "error": str(exc)})
            return

        if path == "/v1/sessions/push":
            channel = (data.get("channel") or WEB_SESSION_CHANNEL).strip() or WEB_SESSION_CHANNEL
            chat_id = (data.get("chat_id") or "default").strip() or "default"
            role = (data.get("role") or "user").strip().lower() or "user"
            text = (data.get("text") or "").strip()
            if not text:
                _json_response(self, 400, {"ok": False, "error": "missing text"})
                return
            try:
                _json_response(self, 200, _sessions_push(channel, chat_id, role, text))
            except Exception as exc:
                _json_response(self, 500, {"ok": False, "error": str(exc)})
            return

        if path == "/v1/sessions/reset":
            channel = (data.get("channel") or WEB_SESSION_CHANNEL).strip() or WEB_SESSION_CHANNEL
            chat_id = (data.get("chat_id") or "default").strip() or "default"
            try:
                _json_response(self, 200, _sessions_reset(channel, chat_id))
            except Exception as exc:
                _json_response(self, 500, {"ok": False, "error": str(exc)})
            return

        if path == "/v1/agent":
            text = (data.get("text") or "").strip()
            if not text:
                _json_response(self, 400, {"ok": False, "error": "missing text"})
                return
            token = self._token()
            if not token:
                _json_response(
                    self,
                    401,
                    {
                        "ok": False,
                        "error": "missing token — set REMOTE_TOKEN in ~/.config/arka/.env",
                    },
                )
                return
            channel = (data.get("channel") or WEB_SESSION_CHANNEL).strip() or WEB_SESSION_CHANNEL
            chat_id = (data.get("chat_id") or "default").strip() or "default"
            try:
                _sessions_push(channel, chat_id, "user", text)
            except Exception:
                pass
            route_info = None
            try:
                route_info = _route_payload(text)
            except Exception:
                pass
            status, payload = _proxy_json("/v1/agent", method="POST", payload=data, token=token)
            if route_info and isinstance(payload, dict):
                payload["route"] = route_info
            if isinstance(payload, dict):
                reply = (payload.get("output") or payload.get("error") or "").strip()
                if reply:
                    try:
                        _sessions_push(channel, chat_id, "assistant", reply)
                    except Exception:
                        pass
                payload["session"] = {"channel": channel, "chat_id": chat_id}
            _json_response(self, status, payload)
            return

        _json_response(self, 404, {"ok": False, "error": "not found"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka desktop bridge")
    parser.add_argument("--host", default=BRIDGE_HOST)
    parser.add_argument("--port", type=int, default=BRIDGE_PORT)
    args = parser.parse_args()

    _bootstrap_env()
    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    print(f"Arka desktop bridge on http://{args.host}:{args.port}", flush=True)
    print(f"Proxying agent/health to {REMOTE_URL}", flush=True)
    if DIST_DIR.is_dir():
        print(f"Serving UI from {DIST_DIR}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
