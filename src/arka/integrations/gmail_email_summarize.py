"""Summarize a single Gmail message (by id, latest, or search)."""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from arka.integrations import google_oauth as oauth
from arka.integrations.gmail_unified import _account_label, _missing_accounts_message
from arka.integrations.google_workspace import (
    _gmail_fetch_row,
    _gmail_summarize_chars,
    _list_gmail_message_ids,
    _parse_gmail_digest_sections,
    _render_gmail_section_body,
    _GMAIL_SECTION_ORDER,
)

_SINGLE_EMAIL_SUMMARIZE_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:summarize|summary|tldr|digest|brief|explain)\b.*\b(?:this|that|the|my\s+latest|latest|most\s+recent|newest)(?:\s+\w+){0,2}\s+email\b"
    r"|\b(?:summarize|summary|tldr|digest|brief)\s+(?:this|that|the|my\s+latest|latest|most\s+recent|newest)(?:\s+\w+){0,2}\s+email\b"
    r"|\bwhat\s+does\s+(?:this|that|the|my\s+latest|latest)(?:\s+\w+){0,2}\s+email\s+say\b"
    r"|\b(?:summarize|summary|tldr|digest|brief)\s+email\s+from\b"
    r"|\b(?:summarize|summary|tldr|digest|brief)\s+(?:the\s+)?email\s+about\b"
    r"|\b(?:summarize|summary|tldr|digest|brief)\s+(?:an?\s+)?email\b(?!\s*from\b)"
    r")"
)


def is_single_email_summarize_request(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    try:
        from arka.integrations.gmail_unified import is_unified_inbox_request

        if is_unified_inbox_request(t):
            return False
    except ImportError:
        pass
    if re.search(r"(?i)\b(?:draft|compose|write)\s+(?:an?\s+)?email\b", t):
        return False
    if re.search(r"(?i)\bemails\b", t) and not re.search(
        r"(?i)\b(?:this|that|the|my\s+latest|latest|most\s+recent|newest)\s+email\b", t
    ):
        return False
    if re.search(r"(?i)\b(?:all|unread)\s+emails\b", t):
        return False
    if re.search(r"(?i)\b(?:inbox|unread\s+mail)\b", t) and not re.search(
        r"(?i)\b(?:this|that|the|my\s+latest|latest)\s+email\b", t
    ):
        return False
    return bool(_SINGLE_EMAIL_SUMMARIZE_RE.search(t))


def parse_single_email_summarize_request(text: str) -> dict[str, str] | None:
    t = (text or "").strip()
    if not t or not is_single_email_summarize_request(t):
        return None

    parsed: dict[str, str] = {}
    lower = t.lower()

    thread_match = re.search(r"(?i)\bthread(?:\s+id)?\s+([0-9a-f]{10,})", t)
    if thread_match:
        parsed["thread_id"] = thread_match.group(1)

    id_match = re.search(r"(?i)\b(?:message|msg)\s+id\s+([0-9a-f]{10,})", t)
    if id_match:
        parsed["message_id"] = id_match.group(1)

    if re.search(r"(?i)\b(?:latest|most recent|newest)\s+unread\b", lower) or re.search(
        r"(?i)\bunread\s+(?:latest|most recent|newest)\b", lower
    ):
        parsed["latest_unread"] = "1"
    elif re.search(
        r"(?i)\b(?:latest|most recent|newest|this|that|the)(?:\s+\w+){0,2}\s+email\b", lower
    ) or re.search(r"(?i)\bthis\s+email\b", lower):
        parsed["latest"] = "1"

    from_match = re.search(
        r"(?i)\b(?:summarize|summary|tldr|digest|brief|explain)\s+(?:the\s+)?email\s+from\s+(.+?)(?:\s+about\b|\s+regarding\b|$)",
        t,
    )
    if not from_match:
        from_match = re.search(r"(?i)\b(?:from|by)\s+([^,.;\n]+?)(?:\s+about\b|\s+regarding\b|$)", t)
    if from_match:
        sender = from_match.group(1).strip()
        sender = re.sub(r"(?i)^(?:the\s+)?email\s+", "", sender).strip()
        sender = re.sub(r"(?i)\b(?:please|pls)\b", "", sender).strip()
        if sender and not re.fullmatch(r"(?i)(?:my|the|this|that|latest)", sender):
            parsed["from"] = sender

    about_match = re.search(r"(?i)\b(?:about|regarding|re:?|on\s+the\s+topic\s+of)\s+(.+)$", t)
    if about_match:
        about = about_match.group(1).strip()
        about = re.sub(r"(?i)\b(?:please|pls|can you|could you)\s*", "", about).strip()
        about = about.strip(" .,-")
        if about:
            parsed["about"] = about

    acct_match = re.search(
        r"(?i)\b(?:on|from|in)\s+(?:my\s+)?(student|personal|work)\s+account\b", t
    )
    if acct_match:
        parsed["account"] = acct_match.group(1).lower()

    if parsed:
        return parsed
    return {"latest": "1"}


def build_gmail_email_summarize_argv_from_nl(text: str) -> list[str]:
    parsed = parse_single_email_summarize_request(text)
    if not parsed:
        return []
    argv = ["summarize"]
    if parsed.get("message_id"):
        argv.append(parsed["message_id"])
    if parsed.get("thread_id"):
        argv.extend(["--thread", parsed["thread_id"]])
    if parsed.get("latest_unread"):
        argv.append("--latest-unread")
    elif parsed.get("latest"):
        argv.append("--latest")
    if parsed.get("from"):
        argv.extend(["--from", parsed["from"]])
    if parsed.get("about"):
        argv.extend(["--about", parsed["about"]])
    if parsed.get("account"):
        argv.extend(["--account", parsed["account"]])
    if len(argv) == 1:
        argv.append("--latest")
    return argv


def _resolve_account_keys(account: str | None) -> list[str]:
    if account:
        want = account.strip().lower()
        for row in oauth.list_linked_accounts():
            if row["key"].lower() == want:
                return [row["key"]]
            if str(row.get("email") or "").lower() == want:
                return [row["key"]]
            if str(row.get("alias") or "").lower() == want:
                return [row["key"]]
        raise RuntimeError(f"Unknown Google account: {account}")
    keys = oauth.resolve_account_keys()
    if not keys:
        raise RuntimeError(_missing_accounts_message())
    return keys


def _row_sort_date(row: dict[str, Any]) -> datetime:
    raw = str(row.get("date") or "").strip()
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError, IndexError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _fetch_row_from_thread(thread_id: str) -> dict[str, Any]:
    detail = oauth.api_request(
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}?format=full"
        "&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
    )
    messages = detail.get("messages") or []
    if not messages:
        raise RuntimeError(f"Thread {thread_id} has no messages")
    latest = messages[-1]
    mid = str(latest.get("id") or "")
    if not mid:
        raise RuntimeError(f"Thread {thread_id} has no message id")
    row = _gmail_fetch_row(mid, include_body=True)
    row["thread_id"] = thread_id
    return row


def _build_search_query(args: argparse.Namespace) -> str:
    parts: list[str] = ["in:inbox"]
    if getattr(args, "latest_unread", False):
        parts.insert(0, "is:unread")
    sender = str(getattr(args, "sender", None) or "").strip()
    if sender:
        parts.append(f"from:{sender}")
    about = str(getattr(args, "about", None) or "").strip()
    if about:
        parts.append(about)
    extra = str(getattr(args, "query", None) or "").strip()
    if extra:
        parts.append(extra)
    return " ".join(parts)


def resolve_single_gmail_row(args: argparse.Namespace) -> dict[str, Any]:
    account = str(getattr(args, "account", None) or "").strip() or None
    keys = _resolve_account_keys(account)
    message_id = str(getattr(args, "message_id", None) or "").strip()
    thread_id = str(getattr(args, "thread", None) or "").strip()

    if message_id:
        errors: list[str] = []
        for key in keys:
            label = _account_label(key)
            try:
                with oauth.using_account(key):
                    row = _gmail_fetch_row(message_id, include_body=True)
                    row["account"] = label
                    row["account_key"] = key
                    return row
            except RuntimeError as exc:
                errors.append(f"{label}: {exc}")
        raise RuntimeError("\n".join(errors) if errors else f"Message {message_id} not found")

    if thread_id:
        errors = []
        for key in keys:
            label = _account_label(key)
            try:
                with oauth.using_account(key):
                    row = _fetch_row_from_thread(thread_id)
                    row["account"] = label
                    row["account_key"] = key
                    return row
            except RuntimeError as exc:
                errors.append(f"{label}: {exc}")
        raise RuntimeError("\n".join(errors) if errors else f"Thread {thread_id} not found")

    query = _build_search_query(args)
    candidates: list[dict[str, Any]] = []
    errors = []
    for key in keys:
        label = _account_label(key)
        try:
            with oauth.using_account(key):
                ids, _estimate = _list_gmail_message_ids(query, max_results=5)
                if not ids:
                    continue
                row = _gmail_fetch_row(ids[0], include_body=True)
                row["account"] = label
                row["account_key"] = key
                candidates.append(row)
        except RuntimeError as exc:
            errors.append(f"{label}: {exc}")

    if not candidates:
        hint = f"No matching email found (query: {query})."
        if errors:
            hint += "\n" + "\n".join(errors)
        raise RuntimeError(hint)

    candidates.sort(key=_row_sort_date, reverse=True)
    return candidates[0]


def _format_single_email_for_summary(row: dict[str, Any]) -> str:
    lines = [
        f"Account: {row.get('account') or 'unknown'}",
        f"From: {row['sender']}",
        f"Date: {row['date']}",
        f"Subject: {row['subject']}",
        f"Unread: {'yes' if row.get('unread') else 'no'}",
    ]
    body = str(row.get("body") or row.get("snippet") or "").strip()
    if body:
        lines.append(f"Body:\n{body}")
    return "\n".join(lines)


def summarize_single_gmail_row(row: dict[str, Any], *, focus: str = "") -> str:
    from arka.llm.cli import llm_complete

    corpus = _format_single_email_for_summary(row)
    char_cap = _gmail_summarize_chars()
    if len(corpus) > char_cap:
        corpus = corpus[:char_cap] + "\n\n[... truncated for model context ...]"

    system = (
        "You summarize one email clearly and accurately.\n\n"
        "Output markdown using EXACTLY these section headers (omit any empty section):\n\n"
        "### Summary\n"
        "Two to four sentences on the main point and tone.\n\n"
        "### Key details\n"
        "Bullets for names, dates, amounts, deadlines, links, or requests.\n\n"
        "### Suggested reply\n"
        "One or two optional reply angles if a response seems expected.\n\n"
        "Rules: use only facts from the email; never invent information."
    )
    meta = (
        f"Account: {row.get('account') or 'unknown'}\n"
        f"From: {row['sender']}\n"
        f"Subject: {row['subject']}"
    )
    user = f"{meta}\nFocus: {focus or 'Summarize this email.'}\n\n{corpus}"
    return llm_complete(system, user, temperature=0.2, task="summarize").strip()


def _print_single_email_summary(row: dict[str, Any], summary: str) -> None:
    print("━━━ Email summary ━━━")
    print()
    print(f"  From: {row['sender']}")
    print(f"  Subject: {row['subject']}")
    if row.get("date"):
        print(f"  Date: {row['date']}")
    if row.get("account"):
        print(f"  Account: {row['account']}")
    print()

    sections = _parse_gmail_digest_sections(summary)
    order = ("Summary", "Key details", "Suggested reply")
    for label in order:
        body = sections.get(label, "").strip()
        if not body and label == "Summary":
            body = sections.get("Overview", "").strip()
        if not body:
            continue
        rule = "─" * len(label)
        print(f"  {label}")
        print(f"  {rule}")
        for line in _render_gmail_section_body(body):
            print(line or "")
        print()

    for label, body in sections.items():
        if label in order or label in _GMAIL_SECTION_ORDER or not body.strip():
            continue
        rule = "─" * len(label)
        print(f"  {label}")
        print(f"  {rule}")
        for line in _render_gmail_section_body(body):
            print(line or "")
        print()


def cmd_gmail_email_summarize(args: argparse.Namespace) -> int:
    if not any(
        (
            getattr(args, "message_id", None),
            getattr(args, "thread", None),
            getattr(args, "latest", False),
            getattr(args, "latest_unread", False),
            getattr(args, "sender", None),
            getattr(args, "about", None),
            getattr(args, "query", None),
        )
    ):
        print(
            "Usage: arka google summarize --latest\n"
            "       arka google summarize --latest-unread\n"
            "       arka google summarize MESSAGE_ID\n"
            "       arka google summarize --thread THREAD_ID\n"
            "       arka google summarize --from john --about project\n"
            "       arka google summarize --account student --latest",
            file=sys.stderr,
        )
        return 1

    try:
        row = resolve_single_gmail_row(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    focus = str(getattr(args, "focus", None) or "").strip()
    summary = summarize_single_gmail_row(row, focus=focus)
    _print_single_email_summary(row, summary)
    return 0


def cmd_parse_email_summary(args: argparse.Namespace) -> int:
    text = " ".join(getattr(args, "text", []) or []).strip()
    argv = build_gmail_email_summarize_argv_from_nl(text)
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def main(argv: list[str] | None = None) -> int:
    from arka.integrations.google_workspace import main as google_main

    extra = list(argv or [])
    if not extra:
        extra = ["--latest"]
    return google_main(["summarize", *extra])
