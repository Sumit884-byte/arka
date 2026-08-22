"""Email OTP sign-in and demo sessions for Arka web UIs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_STORE_LOCK = threading.Lock()
_OTP_STORE: dict[str, dict[str, Any]] = {}


def _truthy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in {"0", "false", "no", "off"}


def auth_enabled() -> bool:
    return _truthy("ARKA_WEB_AUTH", "1")


def demo_enabled() -> bool:
    return _truthy("ARKA_DEMO_MODE", "1")


def otp_enabled() -> bool:
    if not _truthy("ARKA_AUTH_OTP", "1"):
        return False
    try:
        from arka.integrations.email_send import configured_providers

        return bool(configured_providers()) or _truthy("ARKA_AUTH_DEV", "0")
    except ImportError:
        return _truthy("ARKA_AUTH_DEV", "0")


def otp_ttl_sec() -> int:
    try:
        return max(60, int(os.environ.get("ARKA_OTP_TTL_SEC", "600")))
    except ValueError:
        return 600


def session_ttl_sec(*, demo: bool = False) -> int:
    key = "ARKA_DEMO_SESSION_TTL_SEC" if demo else "ARKA_SESSION_TTL_SEC"
    default = "3600" if demo else "604800"
    try:
        return max(300, int(os.environ.get(key, default)))
    except ValueError:
        return 3600 if demo else 604800


def _pepper() -> str:
    try:
        from arka.core.unified_api import api_token

        return api_token() or "arka-auth-dev"
    except ImportError:
        return os.environ.get("REMOTE_TOKEN") or os.environ.get("API_TOKEN") or "arka-auth-dev"


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _otp_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "arka" / "auth"
    base.mkdir(parents=True, exist_ok=True)
    return base / "otp.json"


def _persist_otp() -> None:
    try:
        _otp_path().write_text(json.dumps(_OTP_STORE), encoding="utf-8")
    except OSError:
        pass


def _load_otp() -> None:
    global _OTP_STORE
    path = _otp_path()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            _OTP_STORE = raw
    except (OSError, json.JSONDecodeError):
        pass


def _purge_expired() -> None:
    now = time.time()
    dead = [key for key, row in _OTP_STORE.items() if float(row.get("exp", 0)) <= now]
    for key in dead:
        _OTP_STORE.pop(key, None)


def _otp_key(email: str) -> str:
    return hashlib.sha256(f"{_pepper()}:{email}".encode()).hexdigest()


def _hash_code(email: str, code: str) -> str:
    return hmac.new(_pepper().encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _encode_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_payload(body: str) -> dict[str, Any] | None:
    try:
        padded = body + "=" * (-len(body) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None


def _sign_body(body: str) -> str:
    return hmac.new(_pepper().encode(), body.encode(), hashlib.sha256).hexdigest()[:32]


def _make_session_token(*, email: str, demo: bool) -> str:
    prefix = "arka_demo_" if demo else "arka_sess_"
    payload = {"email": email, "demo": demo, "exp": time.time() + session_ttl_sec(demo=demo)}
    body = _encode_payload(payload)
    return f"{prefix}{body}.{_sign_body(body)}"


def public_config() -> dict[str, Any]:
    _load_otp()
    _purge_expired()
    return {
        "ok": True,
        "auth_enabled": auth_enabled(),
        "otp_enabled": otp_enabled(),
        "demo_enabled": demo_enabled(),
        "otp_ttl_sec": otp_ttl_sec(),
    }


def request_otp(email: str) -> dict[str, Any]:
    if not auth_enabled():
        return {"ok": False, "error": "web auth is disabled"}
    if not otp_enabled():
        return {"ok": False, "error": "email OTP is not configured (set RESEND_API_KEY or SMTP_HOST)"}

    addr = _normalize_email(email)
    if not _EMAIL_RE.match(addr):
        return {"ok": False, "error": "enter a valid email address"}

    code = f"{secrets.randbelow(1_000_000):06d}"
    exp = time.time() + otp_ttl_sec()
    row = {"hash": _hash_code(addr, code), "exp": exp, "attempts": 0}

    with _STORE_LOCK:
        _load_otp()
        _purge_expired()
        _OTP_STORE[_otp_key(addr)] = row
        _persist_otp()

    subject = "Your Arka sign-in code"
    body = (
        f"Your Arka verification code is: {code}\n\n"
        f"It expires in {otp_ttl_sec() // 60} minutes.\n"
        "If you did not request this, you can ignore this email."
    )
    dev_code: str | None = None
    try:
        from arka.integrations.email_send import send_email

        send_email(addr, subject, body)
    except Exception as exc:
        if _truthy("ARKA_AUTH_DEV", "0"):
            dev_code = code
        else:
            return {"ok": False, "error": f"could not send email: {exc}"}

    out: dict[str, Any] = {"ok": True, "email": addr, "expires_in": otp_ttl_sec()}
    if dev_code:
        out["dev_code"] = dev_code
    return out


def verify_otp(email: str, code: str) -> dict[str, Any]:
    if not auth_enabled():
        return {"ok": False, "error": "web auth is disabled"}
    addr = _normalize_email(email)
    otp = (code or "").strip()
    if not _EMAIL_RE.match(addr) or not otp:
        return {"ok": False, "error": "email and code are required"}

    with _STORE_LOCK:
        _load_otp()
        _purge_expired()
        row = _OTP_STORE.get(_otp_key(addr))
        if not row:
            return {"ok": False, "error": "no code pending — request a new one"}
        if float(row.get("exp", 0)) <= time.time():
            _OTP_STORE.pop(_otp_key(addr), None)
            _persist_otp()
            return {"ok": False, "error": "code expired — request a new one"}
        attempts = int(row.get("attempts") or 0) + 1
        row["attempts"] = attempts
        if attempts > 5:
            _OTP_STORE.pop(_otp_key(addr), None)
            _persist_otp()
            return {"ok": False, "error": "too many attempts — request a new code"}
        if not hmac.compare_digest(str(row.get("hash") or ""), _hash_code(addr, otp)):
            _persist_otp()
            return {"ok": False, "error": "incorrect code"}
        _OTP_STORE.pop(_otp_key(addr), None)
        _persist_otp()

    return _issue_session(email=addr, demo=False)


def demo_session() -> dict[str, Any]:
    if not auth_enabled():
        return {"ok": False, "error": "web auth is disabled"}
    if not demo_enabled():
        return {"ok": False, "error": "demo mode is disabled"}
    return _issue_session(email="demo@arka.local", demo=True)


def _issue_session(*, email: str, demo: bool) -> dict[str, Any]:
    token = _make_session_token(email=email, demo=demo)
    row = session_info(token) or {}
    exp = float(row.get("exp") or time.time())
    return {
        "ok": True,
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": max(0, int(exp - time.time())),
        "email": email,
        "demo": demo,
    }


def session_info(token: str) -> dict[str, Any] | None:
    raw = (token or "").strip()
    if raw.startswith("arka_demo_"):
        demo = True
        rest = raw[len("arka_demo_") :]
    elif raw.startswith("arka_sess_"):
        demo = False
        rest = raw[len("arka_sess_") :]
    else:
        return None
    if "." not in rest:
        return None
    body, sig = rest.rsplit(".", 1)
    if not hmac.compare_digest(_sign_body(body), sig):
        return None
    payload = _decode_payload(body)
    if not payload:
        return None
    if float(payload.get("exp", 0)) <= time.time():
        return None
    return {
        "email": str(payload.get("email") or ""),
        "demo": bool(payload.get("demo", demo)),
        "exp": float(payload.get("exp", 0)),
    }


def is_valid_access_token(token: str) -> bool:
    return session_info(token) is not None


def me_payload(token: str) -> dict[str, Any]:
    row = session_info(token)
    if not row:
        return {"ok": False, "error": "invalid or expired session"}
    return {
        "ok": True,
        "email": row.get("email"),
        "demo": bool(row.get("demo")),
        "expires_in": max(0, int(float(row.get("exp", 0)) - time.time())),
    }
