#!/usr/bin/env python3
"""OpenAI Responses API bridge → Arka fish agent (for HF speech-to-speech)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

HOST = os.environ.get("ARKA_HF_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ARKA_HF_BRIDGE_PORT", "8787"))
PID_FILE = os.path.expanduser("~/.cache/fish-agent/arka_hf_bridge.pid")


def _extract_user_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("input") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message" or item.get("role") not in ("user", "User"):
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict):
                text = block.get("text") or block.get("input_text")
                if text:
                    parts.append(str(text).strip())
            elif isinstance(block, str) and block.strip():
                parts.append(block.strip())
    return " ".join(parts).strip()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _clean_agent_output(raw: str) -> str:
    text = _strip_ansi(raw).strip()
    for marker in (
        "━━━ Answer ━━━",
        "━━━ PDF answer ━━━",
        "━━━ Essay ━━━",
        "━━━ Weather ━━━",
    ):
        text = text.replace(marker, "")
    text = re.sub(r"^\[(FROM SEARCH|FROM MEMORY)\]\s*", "", text, flags=re.I)
    text = re.sub(r"^💡.*\n", "", text, flags=re.M)
    text = re.sub(r"^→ Interpreted:.*\n", "", text, flags=re.M)
    text = re.sub(r"^▶ Running.*\n", "", text, flags=re.M)
    text = re.sub(r"^🔎.*\n", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def run_arka_agent(question: str) -> str:
    question = question.strip()
    if not question:
        return "I didn't catch that."
    cmd = f"agent {_shell_quote(question)}"
    proc = subprocess.run(
        ["fish", "-ic", cmd],
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("ARKA_HF_BRIDGE_TIMEOUT", "180")),
        env=os.environ.copy(),
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    answer = _clean_agent_output(out)
    if answer:
        return answer
    if proc.returncode != 0:
        return "Sorry, that command failed."
    return "Done."


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _response_obj(text: str, model: str) -> dict[str, Any]:
    rid = f"resp_{uuid.uuid4().hex[:24]}"
    return {
        "id": rid,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": f"msg_{uuid.uuid4().hex[:16]}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "output_text": text,
        "usage": {"input_tokens": 0, "output_tokens": max(1, len(text.split()))},
    }


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _stream_events(text: str, model: str) -> list[bytes]:
    rid = f"resp_{uuid.uuid4().hex[:24]}"
    msg_id = f"msg_{uuid.uuid4().hex[:16]}"
    chunks: list[bytes] = []
    chunks.append(
        _sse(
            "response.created",
            {
                "type": "response.created",
                "response": {
                    "id": rid,
                    "object": "response",
                    "status": "in_progress",
                    "model": model,
                },
            },
        )
    )
    for word in text.split():
        chunks.append(
            _sse(
                "response.output_text.delta",
                {
                    "type": "response.output_text.delta",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": word + " ",
                },
            )
        )
    chunks.append(
        _sse(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text}],
                },
            },
        )
    )
    chunks.append(
        _sse(
            "response.completed",
            {
                "type": "response.completed",
                "response": _response_obj(text, model),
            },
        )
    )
    return chunks


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "ArkaHFBridge/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[arka-hf-bridge] {self.address_string()} - {fmt % args}", flush=True)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        if urlparse(self.path).path in ("/", "/health", "/v1/health"):
            body = json.dumps({"ok": True, "service": "arka-hf-bridge"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/v1/responses", "/v1/chat/completions"):
            self.send_error(404)
            return
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        if path == "/v1/chat/completions":
            question = ""
            for msg in payload.get("messages") or []:
                if msg.get("role") == "user":
                    question = str(msg.get("content") or "").strip()
        else:
            question = _extract_user_text(payload)

        model = str(payload.get("model") or "arka")
        stream = bool(payload.get("stream"))
        answer = run_arka_agent(question)

        if path == "/v1/chat/completions":
            body = {
                "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
            }
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            for chunk in _stream_events(answer, model):
                self.wfile.write(chunk)
                self.wfile.flush()
            return

        body = json.dumps(_response_obj(answer, model)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def write_pid() -> None:
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def remove_pid() -> None:
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka ↔ HF speech-to-speech LLM bridge")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    write_pid()
    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    print(f"[arka-hf-bridge] Listening on http://{args.host}:{args.port}/v1/responses", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        remove_pid()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
