"""HTTP server for the interactive Arka Output Viewer."""

from __future__ import annotations

import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from arka.web.output_viewer.render import _load_shell, _wrap_view, render_content

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8790


def _viewer_host() -> str:
    return os.environ.get("ARKA_OUTPUT_VIEWER_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def _viewer_port() -> int:
    raw = os.environ.get("ARKA_OUTPUT_VIEWER_PORT", str(DEFAULT_PORT)).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PORT


def _read_local_path(path_text: str) -> tuple[str, str]:
    path = Path(path_text).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    content = path.read_text(encoding="utf-8", errors="replace")
    return content, path.name


class OutputViewerHandler(BaseHTTPRequestHandler):
    server_version = "ArkaOutputViewer/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/render":
            params = parse_qs(parsed.query)
            path_values = params.get("path") or params.get("file") or []
            if not path_values:
                self._json_error(400, "path query parameter is required")
                return
            try:
                content, filename = _read_local_path(path_values[0])
            except OSError as exc:
                self._json_error(400, str(exc))
                return
            payload = render_content(content, filename=filename)
            self._json_response(payload)
            return

        if route not in ("/", "/index.html"):
            self.send_error(404)
            return

        shell = _load_shell().replace("{{TITLE}}", "Arka Output Viewer")
        initial = "<div class='empty-state'>Paste data or load a file to begin.</div>"
        body = shell.replace("{{INITIAL_VIEW}}", initial).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/render":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json_error(400, "Invalid JSON body")
            return

        if not isinstance(data, dict):
            self._json_error(400, "Expected JSON object")
            return

        try:
            payload = self._render_request(data)
        except OSError as exc:
            self._json_error(400, str(exc))
            return

        self._json_response(payload)

    def _render_request(self, data: dict[str, Any]) -> dict[str, Any]:
        path_text = str(data.get("path") or data.get("file") or "").strip()
        content = data.get("content")
        filename = str(data.get("filename") or "").strip() or None
        fmt = str(data.get("format") or "").strip() or None
        title = str(data.get("title") or "").strip() or None

        if path_text:
            content, filename = _read_local_path(path_text)

        if content is None:
            raise ValueError("content or path is required")
        if not isinstance(content, str):
            content = json.dumps(content, indent=2, ensure_ascii=False)

        rendered = render_content(content, fmt=fmt, filename=filename, title=title)
        rendered["html"] = _wrap_view(rendered)
        return rendered

    def _json_response(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, code: int, message: str) -> None:
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(*, host: str | None = None, port: int | None = None) -> int:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    listen_host = host or _viewer_host()
    listen_port = port if port is not None else _viewer_port()
    httpd = ThreadingHTTPServer((listen_host, listen_port), OutputViewerHandler)
    url = f"http://{listen_host}:{listen_port}/"
    print(f"Arka Output Viewer listening on {url}", file=sys.stderr)
    print("API: POST /api/render  ·  GET /api/render?path=/abs/file.json", file=sys.stderr)

    def _stop(*_args: object) -> None:
        httpd.shutdown()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return 0
