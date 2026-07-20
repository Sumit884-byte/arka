#!/usr/bin/env python3
"""Terminal client for the Arka remote/backend HTTP API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

DEFAULT_BACKEND_URL = "http://127.0.0.1:8765"


def backend_url() -> str:
    return (
        os.environ.get("ARKA_BACKEND_URL")
        or os.environ.get("ARKA_REMOTE_URL")
        or os.environ.get("REMOTE_URL")
        or DEFAULT_BACKEND_URL
    ).rstrip("/")


def backend_token() -> str:
    return (
        os.environ.get("ARKA_BACKEND_TOKEN")
        or os.environ.get("ARKA_REMOTE_TOKEN")
        or os.environ.get("REMOTE_TOKEN")
        or ""
    ).strip()


def _endpoint(base: str, path: str) -> str:
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def request_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    url: str | None = None,
    token: str | None = None,
    timeout: int = 600,
) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    tok = token if token is not None else backend_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(_endpoint(url or backend_url(), path), data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        return 0, {"ok": False, "error": f"could not reach backend: {exc.reason}"}


def cmd_status(args: argparse.Namespace) -> int:
    status, data = request_json("/v1/health", url=args.url, token="", timeout=args.timeout)
    if args.json:
        print(json.dumps({"status": status, **data}, indent=2))
    elif data.get("ok"):
        print(f"Arka backend OK: {args.url or backend_url()}")
        print(f"Agent: {data.get('agent', 'arka')}")
    else:
        print(data.get("error") or f"backend health failed ({status})", file=sys.stderr)
    return 0 if data.get("ok") else 1


def cmd_ask(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("Usage: arka backend ask <prompt>", file=sys.stderr)
        return 2
    tok = args.token or backend_token()
    if not tok:
        print(
            "Missing backend token. Set ARKA_BACKEND_TOKEN or REMOTE_TOKEN, "
            "or pass --token <token>.",
            file=sys.stderr,
        )
        return 2
    status, data = request_json(
        "/v1/agent",
        method="POST",
        payload={"text": text, "remote_speak": args.speak},
        url=args.url,
        token=tok,
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps({"status": status, **data}, indent=2))
    else:
        if "output" in data:
            print(str(data.get("output") or "").rstrip())
        elif data.get("error"):
            print(str(data["error"]), file=sys.stderr)
        else:
            print(json.dumps(data, indent=2))
    return 0 if data.get("ok") else 1


def cmd_media(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser()
    if not path.is_file():
        print(f"Media file not found: {path}", file=sys.stderr)
        return 2
    tok = args.token or backend_token()
    if not tok:
        print("Missing backend token. Set ARKA_BACKEND_TOKEN or REMOTE_TOKEN.", file=sys.stderr)
        return 2
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    status, payload = request_json(
        "/v1/media",
        method="POST",
        payload={"name": path.name, "type": args.type or "application/octet-stream", "data": data},
        url=args.url,
        token=tok,
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps({"status": status, **payload}, indent=2))
    elif payload.get("ok"):
        media = payload["media"]
        print(f"Uploaded: {media['name']}")
        print(f"Path: {media['path']}")
    else:
        print(payload.get("error") or f"upload failed ({status})", file=sys.stderr)
    return 0 if payload.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arka backend",
        description="Use an Arka remote/backend server directly from the terminal.",
    )
    parser.add_argument("--url", default=None, help="Backend URL (default: ARKA_BACKEND_URL or localhost)")
    parser.add_argument("--token", default=None, help="Backend token (default: ARKA_BACKEND_TOKEN/REMOTE_TOKEN)")
    parser.add_argument("--timeout", type=int, default=600)
    sub = parser.add_subparsers(dest="cmd")

    status = sub.add_parser("status", help="Check /v1/health")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    ask = sub.add_parser("ask", help="Send a prompt to /v1/agent")
    ask.add_argument("--json", action="store_true")
    ask.add_argument("--speak", action="store_true", help="Ask backend to return speak_text")
    ask.add_argument("text", nargs=argparse.REMAINDER)
    ask.set_defaults(func=cmd_ask)

    media = sub.add_parser("media", help="Upload a file to /v1/media")
    media.add_argument("--json", action="store_true")
    media.add_argument("--type", default=None, help="MIME type")
    media.add_argument("path")
    media.set_defaults(func=cmd_media)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
