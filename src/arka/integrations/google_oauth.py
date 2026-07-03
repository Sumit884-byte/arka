"""Google OAuth 2.0 for Gmail and Calendar (local loopback sign-in)."""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

try:
    from arka.env import env_get
    from arka.paths import cache_dir, load_env_file
except ImportError:
    cache_dir = None  # type: ignore[assignment]
    env_get = None  # type: ignore[assignment]
    load_env_file = None  # type: ignore[assignment]

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
USERINFO_URI = "https://www.googleapis.com/oauth2/v2/userinfo"

SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)

DEFAULT_PORT = 8766
DEFAULT_REDIRECT_PATH = "/oauth2callback"


def _cache() -> Path:
    if cache_dir is not None:
        d = cache_dir()
    else:
        d = Path.home() / ".cache" / "arka"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _token_file() -> Path:
    return _cache() / "google_oauth.json"


def _key_file() -> Path:
    return _cache() / "google_oauth.key"


def _ensure_env() -> None:
    if load_env_file is not None:
        load_env_file()


def _getenv(key: str, default: str = "") -> str:
    _ensure_env()
    if env_get is not None:
        return env_get(key, default)
    return os.environ.get(key, default).strip() or default


def _first_env(*keys: str) -> str:
    for key in keys:
        val = _getenv(key)
        if val:
            return val
    return ""


def client_id() -> str:
    return _first_env("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_CLIENT_ID")


def client_secret() -> str:
    return _first_env("GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_CLIENT_SECRET")


def redirect_uri() -> str:
    custom = _getenv("GOOGLE_OAUTH_REDIRECT_URI")
    if custom:
        return custom
    port = int(_getenv("GOOGLE_OAUTH_PORT", str(DEFAULT_PORT)) or DEFAULT_PORT)
    return f"http://127.0.0.1:{port}{DEFAULT_REDIRECT_PATH}"


def oauth_port() -> int:
    uri = redirect_uri()
    parsed = urllib.parse.urlparse(uri)
    if parsed.port:
        return parsed.port
    return DEFAULT_PORT


def _fernet():
    from cryptography.fernet import Fernet

    raw = _getenv("GOOGLE_OAUTH_KEY")
    if not raw:
        kf = _key_file()
        if kf.is_file():
            raw = kf.read_text(encoding="utf-8").strip()
        else:
            raw = Fernet.generate_key().decode()
            kf.write_text(raw + "\n", encoding="utf-8")
            try:
                kf.chmod(0o600)
            except OSError:
                pass
    return Fernet(raw.encode() if isinstance(raw, str) else raw)


def load_tokens() -> dict[str, Any] | None:
    path = _token_file()
    if not path.is_file():
        return None
    try:
        payload = json.loads(_fernet().decrypt(path.read_bytes()).decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def save_tokens(data: dict[str, Any]) -> None:
    path = _token_file()
    path.write_bytes(_fernet().encrypt(json.dumps(data).encode("utf-8")))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def clear_tokens() -> None:
    path = _token_file()
    if path.is_file():
        path.unlink()


def _http_json(
    url: str,
    *,
    method: str = "GET",
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    body = None
    hdrs = dict(headers or {})
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def build_auth_url(state: str) -> str:
    cid = client_id()
    if not cid:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID not set — run: arka google setup")
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return AUTH_URI + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> dict[str, Any]:
    secret = client_secret()
    if not secret:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_SECRET not set — run: arka google setup")
    payload = _http_json(
        TOKEN_URI,
        method="POST",
        data={
            "code": code,
            "client_id": client_id(),
            "client_secret": secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        },
    )
    if "error" in payload:
        raise RuntimeError(str(payload.get("error_description") or payload.get("error")))
    return payload


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    secret = client_secret()
    payload = _http_json(
        TOKEN_URI,
        method="POST",
        data={
            "client_id": client_id(),
            "client_secret": secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if "error" in payload:
        raise RuntimeError(str(payload.get("error_description") or payload.get("error")))
    return payload


def fetch_user_email(access_token: str) -> str:
    info = _http_json(
        USERINFO_URI,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return str(info.get("email") or info.get("name") or "")


def _merge_token_response(existing: dict[str, Any] | None, fresh: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing or {})
    out.update({k: v for k, v in fresh.items() if v})
    expires_in = int(fresh.get("expires_in") or 3600)
    out["expires_at"] = time.time() + expires_in - 30
    if "refresh_token" not in fresh and existing and existing.get("refresh_token"):
        out["refresh_token"] = existing["refresh_token"]
    return out


def get_access_token(*, force_refresh: bool = False) -> str:
    tokens = load_tokens()
    if not tokens:
        raise RuntimeError("Not signed in — run: arka google login")

    access = str(tokens.get("access_token") or "")
    expires_at = float(tokens.get("expires_at") or 0)
    if access and not force_refresh and expires_at > time.time():
        return access

    refresh = str(tokens.get("refresh_token") or "")
    if not refresh:
        raise RuntimeError("Session expired — run: arka google login")

    fresh = refresh_access_token(refresh)
    merged = _merge_token_response(tokens, fresh)
    if not merged.get("email") and merged.get("access_token"):
        merged["email"] = fetch_user_email(str(merged["access_token"]))
    save_tokens(merged)
    access = str(merged.get("access_token") or "")
    if not access:
        raise RuntimeError("Could not refresh Google token — run: arka google login")
    return access


def api_request(url: str, *, method: str = "GET", body: dict | None = None) -> dict[str, Any]:
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            token = get_access_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        else:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Google API HTTP {exc.code}: {detail}") from exc
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def run_login(*, open_browser: bool = True, timeout: int = 180) -> dict[str, Any]:
    state = secrets.token_urlsafe(16)
    auth_url = build_auth_url(state)
    result: dict[str, Any] = {"code": None, "error": None}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != urllib.parse.urlparse(redirect_uri()).path:
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("state", [""])[0] != state:
                result["error"] = "OAuth state mismatch — try again"
                self._respond("Sign-in failed (state mismatch). You can close this tab.")
                done.set()
                return
            if "error" in qs:
                result["error"] = qs["error"][0]
                self._respond(f"Sign-in denied: {result['error']}")
                done.set()
                return
            code = (qs.get("code") or [""])[0]
            if not code:
                result["error"] = "missing code"
                self._respond("Sign-in failed (no authorization code).")
                done.set()
                return
            result["code"] = code
            self._respond("Google sign-in complete. You can close this tab and return to the terminal.")
            done.set()

        def _respond(self, message: str) -> None:
            body = f"""<!doctype html><html><head><meta charset="utf-8"><title>Arka · Google</title>
<style>body{{font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem;color:#1a1a1a}}
h1{{font-size:1.25rem}}</style></head><body><h1>{message}</h1></body></html>"""
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    port = oauth_port()
    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"Sign in with Google (Gmail + Calendar):\n  {auth_url}\n")
    if open_browser:
        try:
            webbrowser.open(auth_url)
            print("Opened your browser — complete sign-in there.")
        except OSError:
            print("Open the URL above in your browser.")
    else:
        print("Open the URL above in your browser.")

    if not done.wait(timeout):
        server.shutdown()
        raise RuntimeError(f"Sign-in timed out after {timeout}s — run: arka google login")

    server.shutdown()
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    code = result.get("code")
    if not code:
        raise RuntimeError("Sign-in did not return an authorization code")

    token_payload = exchange_code(str(code))
    merged = _merge_token_response(None, token_payload)
    email = fetch_user_email(str(merged["access_token"]))
    merged["email"] = email
    merged["scopes"] = " ".join(SCOPES)
    save_tokens(merged)
    return merged


def credentials_configured() -> bool:
    return bool(client_id() and client_secret())
