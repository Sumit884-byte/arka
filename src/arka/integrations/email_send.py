"""Transactional email delivery for Arka alerts (Resend, SendGrid, SMTP)."""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any

from arka.env import env_get


class EmailSendError(RuntimeError):
    """Raised when no provider is configured or delivery fails."""


def default_from_address() -> str:
    return (
        env_get("ALERT_EMAIL_FROM")
        or env_get("EMAIL_FROM")
        or env_get("SMTP_USER")
        or "arka@localhost"
    )


def configured_providers() -> list[str]:
    providers: list[str] = []
    if env_get("RESEND_API_KEY"):
        providers.append("resend")
    if env_get("SENDGRID_API_KEY"):
        providers.append("sendgrid")
    if env_get("SMTP_HOST"):
        providers.append("smtp")
    return providers


def _http_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise EmailSendError(f"HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise EmailSendError(str(exc)) from exc


def _send_via_resend(*, to: str, subject: str, body: str, from_addr: str) -> dict[str, Any]:
    api_key = env_get("RESEND_API_KEY")
    if not api_key:
        raise EmailSendError("RESEND_API_KEY not set")
    result = _http_json(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        payload={
            "from": from_addr,
            "to": [to],
            "subject": subject,
            "text": body,
        },
    )
    return {"ok": True, "provider": "resend", "id": result.get("id")}


def _send_via_sendgrid(*, to: str, subject: str, body: str, from_addr: str) -> dict[str, Any]:
    api_key = env_get("SENDGRID_API_KEY")
    if not api_key:
        raise EmailSendError("SENDGRID_API_KEY not set")
    _http_json(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        payload={
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": from_addr},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        },
    )
    return {"ok": True, "provider": "sendgrid"}


def _send_via_smtp(*, to: str, subject: str, body: str, from_addr: str) -> dict[str, Any]:
    host = env_get("SMTP_HOST")
    if not host:
        raise EmailSendError("SMTP_HOST not set")
    port = int(env_get("SMTP_PORT") or "587")
    user = env_get("SMTP_USER")
    password = env_get("SMTP_PASSWORD")
    use_tls = env_get("SMTP_USE_TLS", "1").strip().lower() not in {"0", "false", "no", "off"}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body)

    if port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
    return {"ok": True, "provider": "smtp"}


def send_email(
    to: str,
    subject: str,
    body: str,
    *,
    from_addr: str | None = None,
    provider: str = "auto",
) -> dict[str, Any]:
    """Send a plain-text email. Returns provider metadata on success."""
    to = (to or "").strip()
    subject = (subject or "Arka alert").strip()
    body = (body or "").strip()
    if not to:
        raise EmailSendError("recipient email is required")
    if not body:
        raise EmailSendError("email body is required")

    sender = (from_addr or default_from_address()).strip()
    order = configured_providers() if provider == "auto" else [provider.strip().lower()]
    if not order:
        raise EmailSendError(
            "No email provider configured. Set RESEND_API_KEY, SENDGRID_API_KEY, or SMTP_HOST "
            "in ~/.config/arka/.env"
        )

    errors: list[str] = []
    for name in order:
        try:
            if name == "resend":
                return _send_via_resend(to=to, subject=subject, body=body, from_addr=sender)
            if name == "sendgrid":
                return _send_via_sendgrid(to=to, subject=subject, body=body, from_addr=sender)
            if name == "smtp":
                return _send_via_smtp(to=to, subject=subject, body=body, from_addr=sender)
            errors.append(f"unknown provider: {name}")
        except EmailSendError as exc:
            errors.append(f"{name}: {exc}")
        except (OSError, smtplib.SMTPException) as exc:
            errors.append(f"{name}: {exc}")

    raise EmailSendError("; ".join(errors) or "email delivery failed")
