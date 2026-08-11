"""Expose local Ollama through an authenticated proxy and optional public tunnel."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CACHE = Path.home() / ".cache" / "fish-agent"
STATE_PATH = CACHE / "ollama-tunnel.json"
PROXY_PID_PATH = CACHE / "ollama-tunnel-proxy.pid"
TUNNEL_PID_PATH = CACHE / "ollama-tunnel.pid"

_TUNNEL_URL_RE = re.compile(r"https?://[^\s\"']+")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _truthy(name: str, default: str = "1") -> bool:
    return _env(name, default).lower() in {"1", "true", "yes", "on"}


def _proxy_port() -> int:
    try:
        return max(1024, int(_env("OLLAMA_TUNNEL_PORT", "11435")))
    except ValueError:
        return 11435


def _rate_limit_rpm() -> int:
    try:
        return max(1, int(_env("OLLAMA_TUNNEL_RPM", "60")))
    except ValueError:
        return 60


def _ollama_base_url() -> str:
    try:
        from arka.core.api_security import safe_ollama_host

        host = safe_ollama_host()
    except ImportError:
        host = _env("OLLAMA_HOST", "127.0.0.1:11434").replace("0.0.0.0", "127.0.0.1")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host.rstrip("/")


class RateLimiter:
    """Simple per-client requests-per-minute limiter."""

    def __init__(self, rpm: int) -> None:
        self.rpm = max(1, rpm)
        self._events: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, client_key: str) -> bool:
        now = time.time()
        with self._lock:
            window = [t for t in self._events[client_key] if now - t < 60.0]
            if len(window) >= self.rpm:
                self._events[client_key] = window
                return False
            window.append(now)
            self._events[client_key] = window
            return True


def load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(data: dict[str, Any]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ensure_token(*, persist: bool = True) -> str:
    token = _env("OLLAMA_TUNNEL_TOKEN")
    if token:
        return token

    token = secrets.token_urlsafe(24)
    if not persist:
        os.environ["OLLAMA_TUNNEL_TOKEN"] = token
        return token

    try:
        from arka.llm.provider_select import set_env_vars

        set_env_vars({"OLLAMA_TUNNEL_TOKEN": token})
    except ImportError:
        os.environ["OLLAMA_TUNNEL_TOKEN"] = token
    return token


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _stop_pid(path: Path) -> int | None:
    pid = _read_pid(path)
    if pid is None:
        path.unlink(missing_ok=True)
        return None
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    path.unlink(missing_ok=True)
    return pid


def _forward_to_ollama(method: str, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes, str]:
    url = f"{_ollama_base_url()}{path}"
    req_headers = {
        k: v
        for k, v in headers.items()
        if k.lower() not in {"host", "authorization", "content-length", "connection"}
    }
    request = urllib.request.Request(url, data=body or None, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            payload = resp.read()
            content_type = resp.headers.get("Content-Type", "application/json")
            return resp.status, payload, content_type
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        content_type = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
        return exc.code, payload, content_type
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        msg = json.dumps({"error": {"message": str(exc), "type": "upstream_error"}}).encode()
        return 502, msg, "application/json"


class OllamaTunnelHandler(BaseHTTPRequestHandler):
    server_version = "ArkaOllamaTunnel/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[arka-tunnel] {self.address_string()} - {fmt % args}", flush=True)

    def _token_ok(self) -> bool:
        expected = _env("OLLAMA_TUNNEL_TOKEN")
        if not expected:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip() == expected
        return self.headers.get("X-Arka-Token", "").strip() == expected

    def _rate_limit_ok(self) -> bool:
        limiter: RateLimiter | None = getattr(self.server, "rate_limiter", None)
        if limiter is None:
            return True
        client = self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.address_string()
        return limiter.allow(client)

    def _reject(self, code: int, message: str) -> None:
        body = json.dumps({"ok": False, "error": message}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, method: str) -> None:
        if not self._token_ok():
            self._reject(401, "unauthorized — set OLLAMA_TUNNEL_TOKEN")
            return
        if not self._rate_limit_ok():
            self._reject(429, "rate limit exceeded")
            return

        path = urlparse(self.path).path
        allowed = {
            "/v1/chat/completions",
            "/v1/completions",
            "/v1/models",
            "/v1/embeddings",
            "/api/chat",
            "/api/generate",
            "/api/tags",
        }
        if path not in allowed and not path.startswith("/v1/"):
            self._reject(404, f"unsupported path: {path}")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        fwd_headers = {k: v for k, v in self.headers.items()}
        status, payload, content_type = _forward_to_ollama(method, path, body, fwd_headers)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/health", "/v1/health"}:
            body = json.dumps(
                {
                    "ok": True,
                    "service": "arka-ollama-tunnel",
                    "upstream": _ollama_base_url(),
                    "rate_limit_rpm": _rate_limit_rpm(),
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._proxy("GET")

    def do_POST(self) -> None:
        self._proxy("POST")


def serve_proxy(*, host: str = "127.0.0.1", port: int | None = None) -> int:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    ensure_token(persist=True)
    port = port or _proxy_port()
    try:
        from arka.core.api_security import warn_if_insecure_startup

        if host not in {"127.0.0.1", "localhost", "::1"}:
            warn_if_insecure_startup("ollama-tunnel")
    except ImportError:
        pass

    CACHE.mkdir(parents=True, exist_ok=True)
    PROXY_PID_PATH.write_text(str(os.getpid()), encoding="utf-8")

    def _stop(_signum, _frame) -> None:
        PROXY_PID_PATH.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    httpd = ThreadingHTTPServer((host, port), OllamaTunnelHandler)
    httpd.rate_limiter = RateLimiter(_rate_limit_rpm())  # type: ignore[attr-defined]
    print(f"[arka-tunnel] Proxy on http://{host}:{port} → {_ollama_base_url()}", flush=True)
    print("[arka-tunnel] Auth: Bearer OLLAMA_TUNNEL_TOKEN (stored in .env — not printed)", flush=True)
    try:
        httpd.serve_forever()
    finally:
        PROXY_PID_PATH.unlink(missing_ok=True)
    return 0


def _detect_tunnel_cmd(port: int) -> tuple[str, list[str], str] | None:
    cloudflared = shutil.which("cloudflared")
    if cloudflared:
        return (
            cloudflared,
            ["tunnel", "--url", f"http://127.0.0.1:{port}"],
            "cloudflared",
        )
    ngrok = shutil.which("ngrok")
    if ngrok:
        return (
            ngrok,
            ["http", str(port), "--log=stdout"],
            "ngrok",
        )
    return None


def _extract_tunnel_url(text: str) -> str:
    for match in _TUNNEL_URL_RE.finditer(text):
        url = match.group(0).rstrip(").,")
        if "127.0.0.1" in url or "localhost" in url:
            continue
        if any(host in url for host in ("trycloudflare.com", "ngrok", "loca.lt")):
            return url
    return ""


def start_tunnel(*, port: int | None = None, wait_seconds: float = 8.0) -> dict[str, Any]:
    port = port or _proxy_port()
    spec = _detect_tunnel_cmd(port)
    if spec is None:
        return {
            "ok": False,
            "error": "no tunnel binary found (install cloudflared or ngrok)",
            "hint": "cloudflared tunnel --url http://127.0.0.1:{port}  OR  ngrok http {port}".format(port=port),
        }

    binary, args, kind = spec
    proc = subprocess.Popen(
        [binary, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    TUNNEL_PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    captured: list[str] = []
    deadline = time.time() + max(3.0, wait_seconds)
    public_url = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        line = proc.stdout.readline() if proc.stdout else ""
        if line:
            captured.append(line)
            maybe = _extract_tunnel_url(line)
            if maybe:
                public_url = maybe
                break
        else:
            time.sleep(0.1)

    if not public_url:
        public_url = _extract_tunnel_url("".join(captured))

    state = load_state()
    state.update(
        {
            "proxy_port": port,
            "tunnel_kind": kind,
            "tunnel_pid": proc.pid,
            "public_url": public_url or None,
            "started_at": time.time(),
        }
    )
    save_state(state)

    return {
        "ok": bool(public_url),
        "tunnel_kind": kind,
        "tunnel_pid": proc.pid,
        "public_url": public_url or None,
        "local_url": f"http://127.0.0.1:{port}",
        "log_tail": "".join(captured[-20:]),
    }


def start_stack(*, host: str = "127.0.0.1", port: int | None = None, with_tunnel: bool = True) -> dict[str, Any]:
    port = port or _proxy_port()
    token = ensure_token(persist=True)

    proxy_pid = _read_pid(PROXY_PID_PATH)
    if proxy_pid is None or not _pid_alive(proxy_pid):
        proc = subprocess.Popen(
            [sys.executable, "-m", "arka.integrations.ollama_tunnel", "proxy", "--host", host, "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        PROXY_PID_PATH.write_text(str(proc.pid), encoding="utf-8")
        proxy_pid = proc.pid
        time.sleep(0.4)

    result: dict[str, Any] = {
        "ok": True,
        "proxy_pid": proxy_pid,
        "local_url": f"http://{host}:{port}",
        "auth_header": "Authorization: Bearer <OLLAMA_TUNNEL_TOKEN>",
        "token_configured": bool(token),
        "rate_limit_rpm": _rate_limit_rpm(),
        "upstream": _ollama_base_url(),
    }

    if with_tunnel:
        tunnel = start_tunnel(port=port)
        result["tunnel"] = tunnel
        result["public_url"] = tunnel.get("public_url")
        if tunnel.get("public_url"):
            result["endpoint"] = f"{tunnel['public_url']}/v1/chat/completions"
        else:
            result["endpoint"] = f"{result['local_url']}/v1/chat/completions"

    save_state(
        {
            **load_state(),
            "proxy_pid": proxy_pid,
            "proxy_port": port,
            "local_url": result["local_url"],
            "public_url": result.get("public_url"),
            "endpoint": result.get("endpoint"),
            "rate_limit_rpm": _rate_limit_rpm(),
        }
    )
    return result


def stop_stack() -> dict[str, Any]:
    stopped = {
        "proxy_pid": _stop_pid(PROXY_PID_PATH),
        "tunnel_pid": _stop_pid(TUNNEL_PID_PATH),
    }
    state = load_state()
    state["stopped_at"] = time.time()
    save_state(state)
    return {"ok": True, "stopped": stopped}


def status_payload() -> dict[str, Any]:
    state = load_state()
    proxy_pid = _read_pid(PROXY_PID_PATH)
    tunnel_pid = _read_pid(TUNNEL_PID_PATH)
    return {
        "proxy_running": bool(proxy_pid and _pid_alive(proxy_pid)),
        "proxy_pid": proxy_pid,
        "tunnel_running": bool(tunnel_pid and _pid_alive(tunnel_pid)),
        "tunnel_pid": tunnel_pid,
        "local_url": state.get("local_url") or f"http://127.0.0.1:{_proxy_port()}",
        "public_url": state.get("public_url"),
        "endpoint": state.get("endpoint"),
        "upstream": _ollama_base_url(),
        "token_configured": bool(_env("OLLAMA_TUNNEL_TOKEN")),
        "rate_limit_rpm": _rate_limit_rpm(),
        "env": {
            "OLLAMA_TUNNEL_PORT": str(_proxy_port()),
            "OLLAMA_TUNNEL_RPM": str(_rate_limit_rpm()),
            "OLLAMA_TUNNEL_TOKEN": "(set)" if _env("OLLAMA_TUNNEL_TOKEN") else "(unset)",
        },
        "tunnel_binary": (_detect_tunnel_cmd(_proxy_port()) or (None, None, None))[2],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka tunnel ollama",
        description=(
            "Expose local Ollama as an OpenAI-compatible endpoint with API key "
            "auth, rate limiting, and optional cloudflared/ngrok tunnel."
        ),
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show proxy/tunnel status")
    start = sub.add_parser("start", help="Start authenticated proxy and optional public tunnel")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=None)
    start.add_argument("--no-tunnel", action="store_true", help="Start proxy only (no cloudflared/ngrok)")
    sub.add_parser("stop", help="Stop proxy and tunnel")
    proxy = sub.add_parser("proxy", help=argparse.SUPPRESS)
    proxy.add_argument("--host", default="127.0.0.1")
    proxy.add_argument("--port", type=int, default=None)

    args = parser.parse_args(argv or ["status"])
    cmd = args.cmd or "status"

    if cmd == "status":
        print(json.dumps(status_payload(), indent=2))
        return 0
    if cmd == "start":
        print(
            json.dumps(
                start_stack(
                    host=args.host,
                    port=args.port,
                    with_tunnel=not bool(args.no_tunnel),
                ),
                indent=2,
            )
        )
        return 0
    if cmd == "stop":
        print(json.dumps(stop_stack(), indent=2))
        return 0
    if cmd == "proxy":
        return serve_proxy(host=args.host, port=args.port)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
