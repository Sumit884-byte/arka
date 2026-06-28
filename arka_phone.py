#!/usr/bin/env python3
"""Arka phone client — local STT/TTS on phone, agent runs on your PC."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_env() -> None:
    for env_path in (
        Path.home() / ".arka" / "env",
        Path.home() / ".config" / "fish" / ".env",
    ):
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            if val.startswith("export "):
                val = val[7:].strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


def api_request(url: str, token: str, path: str, payload: dict | None = None, timeout: int = 600) -> dict:
    base = url.rstrip("/")
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            err = json.loads(body)
            raise RuntimeError(err.get("error", body)) from exc
        except json.JSONDecodeError:
            raise RuntimeError(body[:300]) from exc


def termux_stt() -> str:
    for cmd in (
        ["termux-speech-to-text"],
        ["termux-speech-to-text", "-l", "en-IN"],
    ):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("Install Termux:API and termux-speech-to-text on your phone")


def termux_tts(text: str, lang: str = "en-IN") -> None:
    text = text.strip()
    if not text:
        return
    for cmd in (
        ["termux-tts-speak", "-l", lang, text],
        ["termux-tts-speak", text],
    ):
        try:
            subprocess.run(cmd, check=True, timeout=120)
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    print(text)


def ask_pc(url: str, token: str, text: str) -> dict:
    return api_request(url, token, "/v1/agent", {"text": text, "remote_speak": True})


def cmd_health(url: str, token: str) -> int:
    base = url.rstrip("/")
    req = urllib.request.Request(f"{base}/v1/health")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print(json.dumps(data, indent=2))
    return 0


def cmd_ask(url: str, token: str, text: str, no_speak: bool) -> int:
    print(f"You: {text}")
    data = ask_pc(url, token, text)
    print(data.get("output", ""))
    if not no_speak:
        speak = data.get("speak_text", "")
        if speak:
            lang = os.environ.get("ARKA_SPEAK_LANG", "en-IN")
            termux_tts(speak, lang)
    return 0 if data.get("ok") else 1


def cmd_listen(url: str, token: str) -> int:
    lang = os.environ.get("ARKA_SPEAK_LANG", "en-IN")
    print(f"Arka phone client → {url}")
    print("Press Enter, then speak. Ctrl+C to quit.")
    while True:
        try:
            input("\n[Enter to speak] ")
        except EOFError:
            break
        try:
            text = termux_stt()
        except RuntimeError as exc:
            print(f"STT error: {exc}", file=sys.stderr)
            continue
        if not text:
            print("No speech detected.")
            continue
        try:
            data = ask_pc(url, token, text)
        except RuntimeError as exc:
            print(f"PC error: {exc}", file=sys.stderr)
            continue
        print(data.get("output", ""))
        speak = data.get("speak_text", "")
        if speak:
            termux_tts(speak, lang)


def phone_matches(a: str, b: str) -> bool:
    da = re.sub(r"\D", "", a or "")
    db = re.sub(r"\D", "", b or "")
    if not da or not db:
        return False
    return da == db or da.endswith(db) or db.endswith(da)


def cmd_sms_watch(url: str, token: str) -> int:
    """Poll Termux SMS inbox and forward allowed senders to PC /v1/inbox."""
    from_num = os.environ.get("ARKA_WHATSAPP_FROM", "+919073153257")
    poll = float(os.environ.get("ARKA_WHATSAPP_POLL", "5"))
    seen: set[str] = set()
    print(f"SMS watch → {url} for {from_num} (poll {poll}s)")
    while True:
        try:
            proc = subprocess.run(
                ["termux-sms-inbox", "-l", "10"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                time.sleep(poll)
                continue
            rows = json.loads(proc.stdout or "[]")
            for row in reversed(rows):
                sender = row.get("number") or row.get("address") or ""
                body = (row.get("body") or "").strip()
                msg_id = str(row.get("_id") or row.get("id") or "")
                if not body or not sender:
                    continue
                key = msg_id or f"{sender}:{body}"
                if key in seen:
                    continue
                if not phone_matches(sender, from_num):
                    continue
                seen.add(key)
                payload = {"from": sender, "text": body, "source": "sms"}
                api_request(url, token, "/v1/inbox", payload)
                print(f"Forwarded SMS: {body[:80]}")
        except (RuntimeError, json.JSONDecodeError, FileNotFoundError) as exc:
            print(f"SMS watch error: {exc}", file=sys.stderr)
        time.sleep(poll)


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Arka phone client (Termux)")
    parser.add_argument("--url", default=os.environ.get("ARKA_REMOTE_URL", ""), help="PC server URL")
    parser.add_argument("--token", default=os.environ.get("ARKA_REMOTE_TOKEN", ""), help="Access token")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("health")
    p_ask = sub.add_parser("ask")
    p_ask.add_argument("text", nargs="+")
    p_ask.add_argument("--no-speak", action="store_true")

    sub.add_parser("listen")
    sub.add_parser("sms-watch")

    args = parser.parse_args()
    url = (args.url or "").strip()
    token = (args.token or "").strip()
    if not url:
        print("Set --url http://PC_IP:8765 or ARKA_REMOTE_URL in .env", file=sys.stderr)
        return 1
    if not token and args.cmd != "health":
        print("Set --token or ARKA_REMOTE_TOKEN", file=sys.stderr)
        return 1

    if args.cmd == "health":
        return cmd_health(url, token)
    if args.cmd == "ask":
        return cmd_ask(url, token, " ".join(args.text), args.no_speak)
    if args.cmd == "listen":
        return cmd_listen(url, token)
    if args.cmd == "sms-watch":
        return cmd_sms_watch(url, token)

    parser.print_help()
    print("\nExamples:")
    print("  python arka_phone.py --url http://192.168.1.5:8765 ask what is the weather")
    print("  python arka_phone.py listen")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
