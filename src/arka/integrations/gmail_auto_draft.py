#!/usr/bin/env python3
"""Auto-draft Gmail replies when new inbound email arrives (poll via routines)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arka.env import env_get
from arka.integrations import google_oauth as oauth
from arka.integrations.google_workspace import (
    _gmail_fetch_row,
    _list_gmail_message_ids,
    compose_draft_email,
    create_gmail_draft,
)

try:
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"


_STATE_FILE = "gmail_auto_draft.json"
_EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w.-]+\.\w+", re.I)
_SKIP_SENDER_RE = re.compile(
    r"(?i)(?:"
    r"noreply|no-reply|donotreply|do-not-reply|mailer-daemon|"
    r"notifications?|newsletter|marketing|bounce|automated"
    r")"
)

_AUTO_DRAFT_TRIGGER = re.compile(
    r"(?i)(?:"
    r"\bauto[\s-]?draft(?:\s+(?:email|reply|replies|gmail|inbox))?\b"
    r"|\b(?:draft|compose)\s+(?:a\s+)?reply\s+(?:automatically|auto)\b"
    r"|\bautomatic(?:ally)?\s+draft\s+(?:email\s+)?repl(?:y|ies)\b"
    r")"
)
_ENABLE_RE = re.compile(r"(?i)\b(?:enable|turn\s+on|start)\b.*\bauto[\s-]?draft")
_DISABLE_RE = re.compile(r"(?i)\b(?:disable|turn\s+off|stop)\b.*\bauto[\s-]?draft")
_STATUS_RE = re.compile(r"(?i)\b(?:status|check)\b.*\bauto[\s-]?draft")


def _state_path() -> Path:
    path = cache_dir() / _STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"enabled": False, "accounts": {}, "stats": {"drafts_created": 0}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"enabled": False, "accounts": {}, "stats": {"drafts_created": 0}}
    if not isinstance(data, dict):
        return {"enabled": False, "accounts": {}, "stats": {"drafts_created": 0}}
    data.setdefault("accounts", {})
    data.setdefault("stats", {"drafts_created": 0})
    return data


def save_state(state: dict[str, Any]) -> None:
    for acct in state.get("accounts", {}).values():
        if not isinstance(acct, dict):
            continue
        seen = acct.get("seen_ids") or []
        drafted = acct.get("drafted_ids") or []
        if len(seen) > 500:
            acct["seen_ids"] = seen[-500:]
        if len(drafted) > 500:
            acct["drafted_ids"] = drafted[-500:]
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def _sender_email(sender: str) -> str:
    match = _EMAIL_ADDR.search(sender or "")
    return (match.group(0) if match else "").strip().lower()


def _reply_subject(subject: str) -> str:
    clean = (subject or "").strip() or "(no subject)"
    if re.match(r"(?i)^re:\s", clean):
        return clean
    return f"Re: {clean}"


def _max_per_tick() -> int:
    raw = env_get("GMAIL_AUTO_DRAFT_MAX", "5")
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def _poll_query() -> str:
    return (os.environ.get("GMAIL_AUTO_DRAFT_QUERY") or "is:unread in:inbox").strip()


def _notify_enabled() -> bool:
    raw = os.environ.get("GMAIL_AUTO_DRAFT_NOTIFY", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _should_skip_sender(sender: str, *, account_email: str) -> str | None:
    email = _sender_email(sender)
    if not email:
        return "missing sender email"
    if account_email and email == account_email.lower():
        return "self-sent"
    if _SKIP_SENDER_RE.search(email) or _SKIP_SENDER_RE.search(sender):
        return "automated sender"
    block = (os.environ.get("GMAIL_AUTO_DRAFT_BLOCK") or "").strip()
    if block:
        blocked = {part.strip().lower() for part in block.split(",") if part.strip()}
        if email in blocked:
            return "blocked sender"
    allow = (os.environ.get("GMAIL_AUTO_DRAFT_ALLOW") or "").strip()
    if allow:
        allowed = {part.strip().lower() for part in allow.split(",") if part.strip()}
        if email not in allowed:
            return "not in allowlist"
    return None


def _compose_inbound_reply(
    *,
    to: str,
    inbound_subject: str,
    inbound_body: str,
    inbound_sender: str,
    sender_email: str,
) -> tuple[str, str, str]:
    excerpt = (inbound_body or "").strip()
    if len(excerpt) > 2500:
        excerpt = excerpt[:2497].rstrip() + "..."
    about = (
        "Write a helpful reply to this inbound email. Be concise and address their message directly.\n"
        f"From: {inbound_sender}\n"
        f"Subject: {inbound_subject}\n\n"
        f"{excerpt or '(no body)'}"
    )
    _subject, body, composer = compose_draft_email(
        to=to,
        about=about,
        sender_email=sender_email,
    )
    return _reply_subject(inbound_subject), body, composer


def _notify(title: str, body: str) -> None:
    if not _notify_enabled():
        return
    try:
        from arka.integrations.remind import _notify as remind_notify

        remind_notify(title, body)
    except Exception:
        print(f"\n✉ {title}: {body}", flush=True)


def _account_state(state: dict[str, Any], account_key: str) -> dict[str, Any]:
    accounts = state.setdefault("accounts", {})
    row = accounts.setdefault(
        account_key,
        {"seen_ids": [], "drafted_ids": [], "bootstrapped": False, "last_check": ""},
    )
    if not isinstance(row, dict):
        row = {"seen_ids": [], "drafted_ids": [], "bootstrapped": False, "last_check": ""}
        accounts[account_key] = row
    row.setdefault("seen_ids", [])
    row.setdefault("drafted_ids", [])
    row.setdefault("bootstrapped", False)
    return row


def auto_draft_tick(
    *,
    dry_run: bool = False,
    force: bool = False,
    bootstrap: bool = False,
    account: str | None = None,
) -> dict[str, Any]:
    """Poll unread inbox mail and draft replies for newly seen messages."""
    state = load_state()
    if not state.get("enabled") and not force and not bootstrap:
        return {"skipped": "disabled", "drafts": [], "bootstrapped": []}

    if not oauth.credentials_configured():
        raise RuntimeError("Google OAuth not configured — run: arka google setup")
    keys = oauth.resolve_account_keys(account)
    if not keys:
        raise RuntimeError("Not signed in — run: arka google login")

    max_drafts = _max_per_tick()
    query = _poll_query()
    created: list[dict[str, str]] = []
    bootstrapped: list[str] = []
    skipped: list[dict[str, str]] = []
    drafted_this_tick = 0

    for account_key in keys:
        with oauth.using_account(account_key):
            account_email = (oauth.signed_in_email() or "").strip().lower()
            acct = _account_state(state, account_key)
            seen = set(str(x) for x in acct.get("seen_ids") or [])
            drafted_ids = set(str(x) for x in acct.get("drafted_ids") or [])

            ids, _estimate = _list_gmail_message_ids(query, max_results=30)
            acct["last_check"] = _now_iso()

            if bootstrap or (not acct.get("bootstrapped") and not seen):
                acct["seen_ids"] = list(seen | set(ids))[-500:]
                acct["bootstrapped"] = True
                bootstrapped.append(account_key)
                continue

            new_ids = [mid for mid in ids if mid not in seen]
            for mid in new_ids:
                seen.add(mid)
                if drafted_this_tick >= max_drafts:
                    skipped.append({"id": mid, "reason": "tick limit reached"})
                    continue

                row = _gmail_fetch_row(mid, include_body=True)
                sender_display = str(row.get("sender") or "unknown")
                sender = _sender_email(sender_display)
                subject = str(row.get("subject") or "(no subject)")
                body = str(row.get("body") or row.get("snippet") or "")

                skip_reason = _should_skip_sender(sender_display, account_email=account_email)
                if skip_reason:
                    skipped.append({"id": mid, "sender": sender, "reason": skip_reason})
                    continue
                if mid in drafted_ids:
                    skipped.append({"id": mid, "sender": sender, "reason": "already drafted"})
                    continue

                try:
                    from arka.integrations.email_contacts import find_similar_draft

                    similar = find_similar_draft(to=sender, about=subject)
                    if similar:
                        skipped.append({"id": mid, "sender": sender, "reason": "similar draft exists"})
                        drafted_ids.add(mid)
                        acct["drafted_ids"] = list(drafted_ids)[-500:]
                        continue
                except ImportError:
                    pass

                reply_subject, reply_body, composer = _compose_inbound_reply(
                    to=sender,
                    inbound_subject=subject,
                    inbound_body=body,
                    inbound_sender=sender_display,
                    sender_email=account_email,
                )

                if dry_run:
                    created.append(
                        {
                            "account": account_key,
                            "to": sender,
                            "subject": reply_subject,
                            "composer": composer,
                            "dry_run": "1",
                        }
                    )
                    drafted_ids.add(mid)
                    drafted_this_tick += 1
                    continue

                draft_id = create_gmail_draft(
                    to=sender,
                    subject=reply_subject,
                    body=reply_body,
                    sender=account_email,
                )
                drafted_ids.add(mid)
                drafted_this_tick += 1
                stats = state.setdefault("stats", {"drafts_created": 0})
                stats["drafts_created"] = int(stats.get("drafts_created") or 0) + 1

                try:
                    from arka.integrations.email_contacts import record_draft_history

                    record_draft_history(
                        to=sender,
                        subject=reply_subject,
                        about=f"auto-reply: {subject}",
                        body=reply_body,
                        draft_id=draft_id,
                        account=account_email,
                    )
                except ImportError:
                    pass

                created.append(
                    {
                        "account": account_key,
                        "to": sender,
                        "subject": reply_subject,
                        "draft_id": draft_id,
                        "composer": composer,
                    }
                )
                _notify("Gmail auto-draft", f"Reply draft for {sender}: {reply_subject}")

            acct["seen_ids"] = list(seen)[-500:]
            acct["drafted_ids"] = list(drafted_ids)[-500:]

    state["last_tick"] = _now_iso()
    save_state(state)
    return {
        "drafts": created,
        "bootstrapped": bootstrapped,
        "skipped": skipped,
        "enabled": bool(state.get("enabled")),
    }


def set_enabled(enabled: bool) -> dict[str, Any]:
    state = load_state()
    state["enabled"] = enabled
    state["updated"] = _now_iso()
    save_state(state)
    return state


def format_status(state: dict[str, Any] | None = None) -> str:
    state = state or load_state()
    lines = [
        f"Auto-draft: {'enabled' if state.get('enabled') else 'disabled'}",
        f"Poll query: {_poll_query()}",
        f"Drafts created (total): {int((state.get('stats') or {}).get('drafts_created') or 0)}",
    ]
    if state.get("last_tick"):
        lines.append(f"Last check: {state['last_tick']}")
    accounts = state.get("accounts") or {}
    if accounts:
        lines.append("Accounts:")
        for key, acct in accounts.items():
            if not isinstance(acct, dict):
                continue
            seen_n = len(acct.get("seen_ids") or [])
            drafted_n = len(acct.get("drafted_ids") or [])
            boot = "bootstrapped" if acct.get("bootstrapped") else "not bootstrapped"
            lines.append(f"  • {key}: seen={seen_n}, drafted={drafted_n}, {boot}")
    else:
        lines.append("No accounts checked yet.")
    lines.append("")
    lines.append("Enable:  arka google auto-draft enable")
    lines.append("Schedule: arka every 5 minutes google auto-draft tick")
    return "\n".join(lines)


def wants_auto_draft(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if _ENABLE_RE.search(clean) or _DISABLE_RE.search(clean) or _STATUS_RE.search(clean):
        return True
    return bool(_AUTO_DRAFT_TRIGGER.search(clean))


def route_command(text: str) -> str:
    clean = (text or "").strip()
    if not wants_auto_draft(clean):
        return ""
    if _ENABLE_RE.search(clean):
        return "google auto-draft enable"
    if _DISABLE_RE.search(clean):
        return "google auto-draft disable"
    if _STATUS_RE.search(clean):
        return "google auto-draft status"
    if re.search(r"(?i)\bbootstrap\b", clean):
        return "google auto-draft bootstrap"
    if re.search(r"(?i)\b(?:schedule|every)\b", clean):
        m = re.search(r"(?i)every\s+(\d+)\s+(minute|minutes|hour|hours)", clean)
        if m:
            qty = m.group(1)
            unit = m.group(2).lower()
            sched = f"every {qty}m" if unit.startswith("minute") else f"every {qty}h"
            return f"routines add {sched} \"google auto-draft tick\""
        return 'routines add every 5m "google auto-draft tick"'
    return "google auto-draft tick"


def cmd_enable(_args: argparse.Namespace) -> int:
    set_enabled(True)
    print("✓ Gmail auto-draft enabled.")
    print(format_status())
    print("\nNext: arka every 5 minutes google auto-draft tick")
    return 0


def cmd_disable(_args: argparse.Namespace) -> int:
    set_enabled(False)
    print("✓ Gmail auto-draft disabled.")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    print(format_status())
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    try:
        result = auto_draft_tick(
            bootstrap=True,
            force=True,
            account=getattr(args, "account", None),
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    accounts = result.get("bootstrapped") or []
    if accounts:
        print(f"✓ Bootstrapped {len(accounts)} account(s) — existing unread mail marked seen (no drafts).")
        for key in accounts:
            print(f"  • {key}")
    else:
        print("No accounts bootstrapped.")
    return 0


def cmd_tick(args: argparse.Namespace) -> int:
    try:
        result = auto_draft_tick(
            dry_run=bool(getattr(args, "dry_run", False)),
            force=bool(getattr(args, "force", False)),
            account=getattr(args, "account", None),
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if result.get("skipped") == "disabled":
        print("Gmail auto-draft is disabled.")
        print("Run: arka google auto-draft enable")
        return 0

    drafts = result.get("drafts") or []
    bootstrapped = result.get("bootstrapped") or []
    if bootstrapped:
        print(
            f"First run: marked {len(bootstrapped)} account(s) as bootstrapped "
            "(existing unread skipped). New mail will get drafts."
        )
        for key in bootstrapped:
            print(f"  • {key}")
        return 0

    if not drafts:
        print("No new emails needed auto-drafts.")
        return 0

    label = "Would draft" if getattr(args, "dry_run", False) else "Drafted"
    print(f"{label} {len(drafts)} reply draft(s):")
    for row in drafts:
        acct = row.get("account") or "?"
        to = row.get("to") or "?"
        subject = row.get("subject") or "?"
        print(f"  • [{acct}] {to} — {subject}")
        if row.get("draft_id"):
            print(f"    draft id: {row['draft_id']}")
    print("Open Gmail → Drafts to review before sending.")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Auto-draft Gmail replies for new inbound mail")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to auto-draft command")
    p_route.add_argument("text", nargs="+")

    p_enable = sub.add_parser("enable", help="Enable auto-draft polling")
    p_enable.set_defaults(func=cmd_enable)

    p_disable = sub.add_parser("disable", help="Disable auto-draft polling")
    p_disable.set_defaults(func=cmd_disable)

    p_status = sub.add_parser("status", help="Show auto-draft state")
    p_status.set_defaults(func=cmd_status)

    p_boot = sub.add_parser("bootstrap", help="Mark current unread as seen without drafting")
    p_boot.add_argument("--account", help="Single linked account key")
    p_boot.set_defaults(func=cmd_bootstrap)

    p_tick = sub.add_parser("tick", help="Check inbox and draft replies for new mail")
    p_tick.add_argument("--dry-run", action="store_true", help="Compose without saving drafts")
    p_tick.add_argument("--force", action="store_true", help="Run even when disabled")
    p_tick.add_argument("--account", help="Single linked account key")
    p_tick.set_defaults(func=cmd_tick)

    args = parser.parse_args(argv)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    func = getattr(args, "func", None)
    if not func:
        parser.print_help()
        return 0
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
