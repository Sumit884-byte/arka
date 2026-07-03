#!/usr/bin/env python3
"""Remote Arka server — phone does STT/TTS; PC runs the heavy agent."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
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
PID_PATH = CACHE / "arka_remote.pid"
ENV_PATH = Path.home() / ".config" / "fish" / ".env"

MOBILE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Arka Remote</title>
<style>
  :root { --bg:#0d1117; --fg:#e6edf3; --accent:#58a6ff; --muted:#8b949e; --ok:#3fb950; --err:#f85149; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,sans-serif; background:var(--bg); color:var(--fg);
         min-height:100dvh; display:flex; flex-direction:column; padding:1rem; }
  h1 { font-size:1.25rem; margin:0 0 .5rem; }
  .sub { color:var(--muted); font-size:.85rem; margin-bottom:1rem; }
  #token { width:100%; padding:.6rem; border:1px solid #30363d; border-radius:8px;
           background:#161b22; color:var(--fg); margin-bottom:.75rem; }
  #out { flex:1; overflow:auto; background:#161b22; border:1px solid #30363d; border-radius:8px;
         padding:.75rem; font-size:.9rem; white-space:pre-wrap; margin-bottom:1rem; min-height:8rem; }
  .mic { width:5rem; height:5rem; border-radius:50%; border:none; background:var(--accent);
         color:#fff; font-size:2rem; align-self:center; cursor:pointer; box-shadow:0 4px 20px #58a6ff44; }
  .mic.listening { background:var(--err); animation:pulse 1s infinite; }
  @keyframes pulse { 50% { transform:scale(1.05); } }
  .row { display:flex; gap:.5rem; margin-bottom:.75rem; }
  button.sec { flex:1; padding:.6rem; border:1px solid #30363d; border-radius:8px;
               background:#21262d; color:var(--fg); cursor:pointer; }
  .status { text-align:center; color:var(--muted); font-size:.8rem; min-height:1.2rem; margin-top:.5rem; }
  .hint { color:var(--muted); font-size:.75rem; margin-top:1rem; line-height:1.4; }
</style>
</head>
<body>
<h1>Arka Remote</h1>
<p class="sub">Speech on phone · heavy AI on your PC</p>
<input id="token" type="password" placeholder="Access token (from arka serve on PC)" autocomplete="off">
<div id="out">Tap the mic and say: "hey arka, what's the weather?"</div>
<div class="row">
  <button class="sec" id="saveTok">Save token</button>
  <button class="sec" id="clearOut">Clear</button>
</div>
<button class="mic" id="mic" title="Hold to speak">🎤</button>
<p class="status" id="status"></p>
<p class="hint">Uses your phone browser for speech-to-text and text-to-speech.
The PC runs agent, LLM, and installs. Same Wi‑Fi required. Token stays in this browser only.</p>
<script>
const out = document.getElementById('out');
const status = document.getElementById('status');
const mic = document.getElementById('mic');
const tokenEl = document.getElementById('token');
tokenEl.value = localStorage.getItem('arka_token') || '';
document.getElementById('saveTok').onclick = () => {
  localStorage.setItem('arka_token', tokenEl.value.trim());
  status.textContent = 'Token saved';
};
document.getElementById('clearOut').onclick = () => { out.textContent = ''; };

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SR) {
  status.textContent = 'Speech recognition not supported in this browser. Use Chrome on Android.';
  mic.disabled = true;
}

let rec = null;
let listening = false;

function speak(text) {
  if (!text || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = localStorage.getItem('arka_speak_lang') || 'en-IN';
  window.speechSynthesis.speak(u);
}

async function askArka(text) {
  const tok = tokenEl.value.trim() || localStorage.getItem('arka_token') || '';
  if (!tok) { status.textContent = 'Enter access token first'; return; }
  status.textContent = 'Thinking on PC...';
  out.textContent += '\\n\\nYou: ' + text + '\\n';
  try {
    const r = await fetch('/v1/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + tok },
      body: JSON.stringify({ text, remote_speak: true })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || r.statusText);
    out.textContent += 'Arka: ' + (data.output || '').trim() + '\\n';
    out.scrollTop = out.scrollHeight;
    status.textContent = data.ok ? 'Done' : 'Error';
    if (data.speak_text) speak(data.speak_text);
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    out.textContent += 'Error: ' + e.message + '\\n';
  }
}

function startListen() {
  if (!SR || listening) return;
  rec = new SR();
  rec.lang = localStorage.getItem('arka_stt_lang') || 'en-IN';
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = (ev) => {
    const t = ev.results[0][0].transcript.trim();
    if (t) askArka(t);
  };
  rec.onerror = (ev) => { status.textContent = ev.error; mic.classList.remove('listening'); listening = false; };
  rec.onend = () => { mic.classList.remove('listening'); listening = false; };
  listening = true;
  mic.classList.add('listening');
  status.textContent = 'Listening...';
  rec.start();
}

mic.onclick = () => {
  if (listening && rec) { rec.stop(); return; }
  startListen();
};
</script>
</body>
</html>
"""


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def extract_speak_text(raw: str) -> str:
    text = strip_ansi(raw)
    if "━━━ Answer ━━━" in text:
        text = text.split("━━━ Answer ━━━", 1)[1]
    text = " ".join(text.split())
    max_len = int(os.environ.get("AGENT_SPEAK_MAX", "450"))
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


def run_agent_remote(text: str) -> tuple[str, str, int]:
    """Run fish agent_hear without local TTS; return (full_output, speak_text, exit_code)."""
    text = text.strip()
    if not text:
        return "", "", 1

    env = os.environ.copy()
    env["AGENT_SPEAK"] = "0"

    cmd = f"agent_hear {shlex.quote(text)}"
    try:
        proc = subprocess.run(
            ["fish", "-ic", cmd],
            capture_output=True,
            text=True,
            env=env,
            timeout=int(os.environ.get("ARKA_REMOTE_TIMEOUT", "600")),
        )
    except subprocess.TimeoutExpired:
        return "", "Sorry, that took too long.", 124

    output = (proc.stdout or "") + (proc.stderr or "")
    speak_text = extract_speak_text(output)
    return output.strip(), speak_text, proc.returncode


def transcribe_wav(wav_bytes: bytes) -> str:
    """Optional server-side STT when phone sends audio instead of text."""
    venv_py = Path.home() / ".config" / "fish" / "venv-arka" / "bin" / "python3"
    tmp = CACHE / "upload.wav"
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(wav_bytes)
    code = f"""
import json, sys, wave
from pathlib import Path
from vosk import KaldiRecognizer, Model
wav_path = Path({str(tmp)!r})
model_dir = Path.home() / ".cache" / "vosk-model-small-en-us"
model = Model(str(model_dir))
with wave.open(str(wav_path), "rb") as wf:
    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(False)
    while True:
        data = wf.readframes(4000)
        if not data:
            break
        rec.AcceptWaveform(data)
    print(json.loads(rec.FinalResult()).get("text", ""))
"""
    py = str(venv_py if venv_py.exists() else sys.executable)
    proc = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "transcription failed")
    return proc.stdout.strip()


class ArkaRemoteHandler(BaseHTTPRequestHandler):
    server_version = "ArkaRemote/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[arka-remote] {self.address_string()} - {fmt % args}", flush=True)

    def _check_auth(self) -> bool:
        token = os.environ.get("ARKA_REMOTE_TOKEN", "").strip()
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
        if path in ("/", "/app", "/mobile"):
            body = MOBILE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/v1/health":
            self._json(
                200,
                {
                    "ok": True,
                    "agent": os.environ.get("AGENT_NAME", "arka"),
                    "speak_lang": os.environ.get("ARKA_SPEAK_LANG", "en-IN"),
                },
            )
            return
        if path == "/v1/handoff":
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.agent.core import handoff_api_list

            items = handoff_api_list()
            self._json(200, {"ok": True, "items": items[-20:]})
            return
        if path == "/v1/notifications":
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.agent.talents import handoff_notifications_list

            unread = urlparse(self.path).query.find("unread=1") >= 0
            items = handoff_notifications_list(unread_only=unread)
            self._json(200, {"ok": True, "items": items[-10:]})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._check_auth():
            self._json(401, {"ok": False, "error": "unauthorized — set ARKA_REMOTE_TOKEN on PC"})
            return

        path = urlparse(self.path).path

        if path == "/v1/agent":
            try:
                data = json.loads(self._read_body().decode("utf-8"))
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return

            text = (data.get("text") or "").strip()
            if not text:
                self._json(400, {"ok": False, "error": "missing text"})
                return

            output, speak_text, code = run_agent_remote(text)
            remote_speak = data.get("remote_speak", True)
            self._json(
                200,
                {
                    "ok": code == 0,
                    "exit_code": code,
                    "output": output,
                    "speak_text": speak_text if remote_speak else "",
                },
            )
            return

        if path == "/v1/transcribe":
            ct = self.headers.get("Content-Type", "")
            body = self._read_body()
            if len(body) > 10 * 1024 * 1024:
                self._json(413, {"ok": False, "error": "audio too large (max 10MB)"})
                return
            try:
                if "json" in ct:
                    payload = json.loads(body.decode("utf-8"))
                    import base64

                    audio = base64.b64decode(payload.get("audio", ""))
                else:
                    audio = body
                text = transcribe_wav(audio)
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "text": text})
            return

        if path == "/v1/handoff":
            try:
                data = json.loads(self._read_body().decode("utf-8"))
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.agent.core import handoff_api_add, handoff_api_list

            action = (data.get("action") or "add").strip().lower()
            if action == "list":
                items = handoff_api_list(data.get("status"))
                self._json(200, {"ok": True, "items": items})
                return
            text = (data.get("text") or "").strip()
            if not text:
                self._json(400, {"ok": False, "error": "missing text"})
                return
            item = handoff_api_add(text, source=data.get("source") or "phone")
            self._json(200, {"ok": True, "item": item})
            return

        if path == "/v1/notifications/read":
            try:
                data = json.loads(self._read_body().decode("utf-8")) if self.headers.get("Content-Length") else {}
            except json.JSONDecodeError:
                data = {}
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.agent.talents import handoff_notifications_mark_read

            handoff_notifications_mark_read(data.get("id") or None)
            self._json(200, {"ok": True})
            return

        if path == "/v1/inbox":
            try:
                data = json.loads(self._read_body().decode("utf-8"))
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return
            from_num = (data.get("from") or data.get("phone") or "").strip()
            text = (data.get("text") or data.get("message") or "").strip()
            source = (data.get("source") or "whatsapp").strip()
            if not from_num or not text:
                self._json(400, {"ok": False, "error": "missing from or text"})
                return
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.integrations.whatsapp_inbox import handle_inbox_message

            result = handle_inbox_message(from_num, text, source=source)
            code = 200 if result.get("ok") else 403
            self._json(code, result)
            return

        self._json(404, {"ok": False, "error": "not found"})


def ensure_token() -> str:
    token = os.environ.get("ARKA_REMOTE_TOKEN", "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(24)
    line = f"ARKA_REMOTE_TOKEN={token}\n"
    if ENV_PATH.exists():
        content = ENV_PATH.read_text()
        if "ARKA_REMOTE_TOKEN=" not in content:
            with ENV_PATH.open("a") as fh:
                fh.write(line)
    else:
        ENV_PATH.write_text(line)
    os.environ["ARKA_REMOTE_TOKEN"] = token
    print(f"[arka-remote] Generated ARKA_REMOTE_TOKEN and saved to {ENV_PATH}", flush=True)
    return token


def local_ip() -> str:
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def write_pid() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))


def remove_pid() -> None:
    PID_PATH.unlink(missing_ok=True)


def serve() -> int:
    host = os.environ.get("ARKA_REMOTE_HOST", "0.0.0.0")
    port = int(os.environ.get("ARKA_REMOTE_PORT", "8765"))
    token = ensure_token()

    write_pid()

    def _stop(_signum, _frame):
        print("[arka-remote] Stopping", flush=True)
        remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    httpd = ThreadingHTTPServer((host, port), ArkaRemoteHandler)
    ip = local_ip()
    print(f"[arka-remote] Listening on http://{ip}:{port}/", flush=True)
    print(f"[arka-remote] Mobile UI: http://{ip}:{port}/", flush=True)
    print(f"[arka-remote] Token: {token}", flush=True)
    print("[arka-remote] Phone does STT/TTS · PC runs agent", flush=True)

    try:
        httpd.serve_forever()
    finally:
        remove_pid()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka remote server")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    sub.add_parser("stop")
    args = parser.parse_args()

    if args.cmd == "serve":
        return serve()
    if args.cmd == "stop":
        if not PID_PATH.exists():
            return 0
        pid = int(PID_PATH.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        PID_PATH.unlink(missing_ok=True)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
