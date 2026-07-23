#!/usr/bin/env python3
"""Google Calendar and Gmail via OAuth — arka google login | gmail | calendar."""

from __future__ import annotations

import argparse
import base64
import os
import re
import shlex
import sys
import webbrowser
from email.message import EmailMessage
from html import unescape as html_unescape
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from arka.env import env_get
from arka.integrations import google_oauth as oauth

try:
    from arka.integrations import macos_calendar
except ImportError:
    macos_calendar = None  # type: ignore[assignment]

CONSOLE_CREDENTIALS = "https://console.cloud.google.com/apis/credentials"
CONSOLE_LIBRARY = "https://console.cloud.google.com/apis/library"


def _env_path() -> Path:
    try:
        from arka.paths import env_file

        return env_file()
    except ImportError:
        return Path.home() / ".config" / "arka" / ".env"


def _setup_instructions(*, open_console: bool = False) -> None:
    redirect = oauth.redirect_uri()
    env_path = _env_path()
    print(
        f"""Google Calendar + Gmail for Arka
================================

Before Arka can open a Google sign-in URL, you need an OAuth client ID
(Google requirement — every app must register its own client).

1. Open Google Cloud Console → Credentials:
   {CONSOLE_CREDENTIALS}

2. Enable APIs (Library):
   • Gmail API
   • Google Calendar API
   {CONSOLE_LIBRARY}

3. OAuth consent screen → External is fine for personal use.
   • App name: use something readable (e.g. "Arka") — not a single letter.
   • Publishing status: leave as **Testing** (no Google verification needed for personal use).
   • **Test users:** click Add users → add the Gmail address you sign in with.
     (Without this you get "has not completed the Google verification process".)

4. Create credentials → OAuth client ID → Web application
   Authorized redirect URI (copy exactly):
     {redirect}

5. Add to {env_path}:

   GOOGLE_OAUTH_CLIENT_ID=....apps.googleusercontent.com
   GOOGLE_OAUTH_CLIENT_SECRET=....

   Already have GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET? Arka uses those too —
   just add the redirect URI above to that same OAuth client.

6. Reload and sign in (this opens the Google URL in your browser):

   arka reload
   arka google login

After sign-in:
   arka google gmail --unread
   arka google calendar --today
"""
    )
    if open_console:
        try:
            webbrowser.open(CONSOLE_CREDENTIALS)
            print(f"Opened {CONSOLE_CREDENTIALS}")
        except OSError:
            pass


def _missing_credentials_message(*, open_console: bool = False) -> None:
    print(
        "Cannot open Google sign-in yet — OAuth client ID/secret not found in .env.\n"
        "(Google will not issue a sign-in URL without them.)\n"
    )
    _setup_instructions(open_console=open_console)


def cmd_status() -> int:
    if not oauth.credentials_configured():
        print("Google OAuth not configured in .env.")
        print("Set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET (or GOOGLE_OAUTH_* aliases).")
        print(f"Env file: {_env_path()}")
        return 1
    id_key, sec_key = oauth.credentials_source()
    if id_key:
        print(f"OAuth credentials loaded from {id_key}" + (f" + {sec_key}" if sec_key else ""))
    accounts = oauth.list_linked_accounts()
    if not accounts:
        print("Not signed in.")
        print("Run: arka google login")
        print("Add another account: arka google login --add")
        print(f"Redirect URI for Google Cloud: {oauth.redirect_uri()}")
        return 1
    print(f"Linked Google account(s): {len(accounts)}")
    for row in accounts:
        email = row.get("email") or "unknown"
        alias = str(row.get("alias") or "").strip()
        legacy = " (primary)" if row.get("legacy") else ""
        alias_note = f" [{alias}]" if alias else ""
        print(f"  • {email}{alias_note}{legacy}")
    print("Scopes: Gmail (read/compose/send), Calendar (read/events)")
    print("Unified inbox: arka google inbox --summarize --unread --all")
    print("Single email: arka google summarize --latest")
    print("Auto-draft replies: arka google auto-draft enable")
    print(f"Token dir: {oauth._cache()}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    if not oauth.credentials_configured():
        _missing_credentials_message(open_console=not args.no_browser)
        return 1
    account = str(getattr(args, "account", None) or "").strip() or None
    add_account = bool(getattr(args, "add", False))
    try:
        merged = oauth.run_login(
            open_browser=not args.no_browser,
            timeout=args.timeout,
            account=account,
            add_account=add_account or bool(account),
        )
    except RuntimeError as exc:
        err = str(exc)
        print(f"Sign-in failed: {err}", file=sys.stderr)
        if "invalid_client" in err.lower() or "invalid_grant" in err.lower():
            print(
                "\nTip: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be from the same\n"
                "  Web application OAuth client (not Desktop/Android/iOS).\n",
                file=sys.stderr,
            )
        if "redirect_uri" in err.lower():
            print(
                f"\nTip: add this redirect URI to your OAuth client in Google Cloud Console:\n"
                f"  {oauth.redirect_uri()}\n",
                file=sys.stderr,
            )
        if "401" in err and "UNAUTHENTICATED" in err:
            print(
                "\nTip: retry after arka reload — login now requests openid+email scopes.\n"
                "  If it persists, check GOOGLE_CLIENT_SECRET matches your Web OAuth client.\n",
                file=sys.stderr,
            )
        if "verification" in err.lower() or "access blocked" in err.lower() or "access_denied" in err.lower():
            print(
                "\nTip: OAuth consent screen → Test users → Add your Gmail address.\n"
                "  Leave the app in Testing mode (personal use). Full verification is only\n"
                "  required if you publish the app to all Google users.\n"
                "  https://console.cloud.google.com/apis/credentials/consent\n",
                file=sys.stderr,
            )
        return 1
    email = merged.get("email") or "your Google account"
    print(f"✓ Signed in as {email}")
    if add_account or account:
        print("Add another account anytime: arka google login --add")
    print("Try: arka google gmail --unread")
    print("     arka google inbox --summarize --unread --all")
    print("     arka google calendar --today")
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    account = str(getattr(args, "account", None) or "").strip() or None
    if getattr(args, "all", False):
        oauth.clear_all_tokens()
        print("Signed out of all Google accounts (local tokens removed).")
        return 0
    if account:
        oauth.clear_tokens(account)
        print(f"Signed out of Google account {account} (local tokens removed).")
        return 0
    oauth.clear_tokens(None)
    print("Signed out of Google (primary local tokens removed).")
    print("Other linked accounts remain — use: arka google logout --all")
    return 0


def _decode_header(payload: dict[str, Any], name: str) -> str:
    for row in payload.get("payload", {}).get("headers") or []:
        if (row.get("name") or "").lower() == name.lower():
            return str(row.get("value") or "")
    return ""


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def _decode_part_text(part: dict[str, Any]) -> tuple[str, str]:
    mime = part.get("mimeType") or ""
    body = part.get("body") or {}
    data = body.get("data")
    if not data:
        return mime, ""
    try:
        raw = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return mime, ""
    return mime, raw


def _decode_body(payload: dict[str, Any]) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime, text = _decode_part_text(part)
        if text:
            if mime.startswith("text/plain"):
                plain_parts.append(text)
            elif mime.startswith("text/html"):
                html_parts.append(text)
        for child in part.get("parts") or []:
            walk(child)

    walk(payload.get("payload") or {})
    if plain_parts:
        return re.sub(r"\n{3,}", "\n\n", "\n\n".join(plain_parts)).strip()
    if html_parts:
        return _html_to_text("\n\n".join(html_parts))
    return ""


def _gmail_local_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(_google_calendar_tz())
        return datetime.now(tz)
    except Exception:
        return datetime.now().astimezone()


def _gmail_day_range(*, days: int) -> tuple[str, str, str]:
    """Calendar-day window through today (local TZ). Returns after, before, label."""
    now = _gmail_local_now()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start_today + timedelta(days=1)
    d = max(int(days), 1)
    if d == 1:
        start = start_today
    else:
        start = start_today - timedelta(days=d)
    after = start.strftime("%Y/%m/%d")
    before = end.strftime("%Y/%m/%d")
    tz_name = _google_calendar_tz()
    if start.date() == start_today.date():
        label = f"today · {start_today.strftime('%a %b %d, %Y')} ({tz_name})"
    else:
        label = (
            f"{start.strftime('%a %b %d')} – {start_today.strftime('%a %b %d, %Y')} ({tz_name})"
        )
    return after, before, label


def _gmail_max_results(*, fetch_all: bool, limit: int) -> int:
    if fetch_all or limit <= 0:
        raw = env_get("GMAIL_MAX", "500")
        try:
            return max(1, int(raw))
        except ValueError:
            return 500
    return max(1, limit)


def _list_gmail_message_ids(query: str, *, max_results: int) -> tuple[list[str], int | None]:
    """Paginate Gmail message list; return (ids, resultSizeEstimate)."""
    ids: list[str] = []
    page_token: str | None = None
    estimate: int | None = None
    page_size = min(500, max_results)

    while len(ids) < max_results:
        batch = min(page_size, max_results - len(ids))
        params: list[tuple[str, str]] = [
            ("maxResults", str(batch)),
            ("q", query),
            ("includeSpamTrash", "false"),
        ]
        if page_token:
            params.append(("pageToken", page_token))
        query_str = urlencode(params)
        listing = oauth.api_request(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{query_str}"
        )
        if estimate is None:
            raw_est = listing.get("resultSizeEstimate")
            if isinstance(raw_est, int):
                estimate = raw_est
        for row in listing.get("messages") or []:
            mid = str(row.get("id") or "")
            if mid:
                ids.append(mid)
        page_token = listing.get("nextPageToken")
        if not page_token:
            break

    return ids, estimate


def _gmail_query_from_args(args: argparse.Namespace) -> tuple[str, str]:
    q_parts: list[str] = []
    range_label = ""
    if args.unread:
        q_parts.append("is:unread")
    if args.today:
        today = _gmail_local_now().strftime("%Y/%m/%d")
        q_parts.append(f"after:{today}")
        range_label = f"today · {_gmail_local_now().strftime('%a %b %d, %Y')}"
    elif args.days and args.days > 0:
        if args.rolling:
            q_parts.append(f"newer_than:{int(args.days)}d")
            range_label = f"last {int(args.days)} day(s) rolling"
        else:
            after, before, range_label = _gmail_day_range(days=int(args.days))
            q_parts.append(f"after:{after}")
            q_parts.append(f"before:{before}")
    elif args.hours and args.hours > 0:
        q_parts.append(f"newer_than:{int(args.hours)}h")
        range_label = f"last {int(args.hours)} hour(s)"
    if args.query:
        q_parts.append(args.query)
    query = " ".join(q_parts) or "in:inbox"
    return query, range_label


def _gmail_summarize_cap() -> int:
    raw = env_get("GMAIL_SUMMARIZE_MAX", "40")
    try:
        return max(1, int(raw))
    except ValueError:
        return 40


def _gmail_summarize_chars() -> int:
    raw = env_get("GMAIL_SUMMARIZE_CHARS", "120000")
    try:
        return max(8000, int(raw))
    except ValueError:
        return 120000


def _gmail_fetch_row(mid: str, *, include_body: bool = False) -> dict[str, Any]:
    fmt = "full" if include_body else "metadata"
    params = "&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
    detail = oauth.api_request(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}?format={fmt}{params}"
    )
    labels = detail.get("labelIds") or []
    row: dict[str, Any] = {
        "id": mid,
        "subject": _decode_header(detail, "Subject") or "(no subject)",
        "sender": _decode_header(detail, "From") or "unknown",
        "date": _decode_header(detail, "Date") or "",
        "unread": "UNREAD" in labels,
        "snippet": str(detail.get("snippet") or "").strip(),
    }
    if include_body:
        body = _decode_body(detail).strip()
        if body:
            row["body"] = body
        elif row["snippet"]:
            row["body"] = row["snippet"]
    return row


def _load_gmail_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], str, str, int | None]:
    query, range_label = _gmail_query_from_args(args)
    if getattr(args, "summarize", False):
        cap = _gmail_summarize_cap()
        if args.all:
            max_results = _gmail_max_results(fetch_all=True, limit=0)
            max_results = min(max_results, cap)
        else:
            max_results = min(max(args.limit, 1), cap)
    else:
        max_results = _gmail_max_results(fetch_all=bool(args.all), limit=int(args.limit))
    message_ids, estimate = _list_gmail_message_ids(query, max_results=max_results)
    include_body = bool(getattr(args, "summarize", False))
    rows = [_gmail_fetch_row(mid, include_body=include_body) for mid in message_ids]
    return rows, query, range_label, estimate


def _format_gmail_for_summary(row: dict[str, Any]) -> str:
    lines = [
        f"From: {row['sender']}",
        f"Date: {row['date']}",
        f"Subject: {row['subject']}",
        f"Unread: {'yes' if row.get('unread') else 'no'}",
    ]
    body = str(row.get("body") or row.get("body_preview") or row.get("snippet") or "").strip()
    if body:
        lines.append(f"Body:\n{body}")
    return "\n".join(lines)


_GMAIL_DIGEST_SECTIONS: tuple[tuple[str, str], ...] = (
    ("overview", "Overview"),
    ("summary", "Summary"),
    ("key details", "Key details"),
    ("suggested reply", "Suggested reply"),
    ("worth your attention", "Worth your attention"),
    ("needs action", "Worth your attention"),
    ("attention", "Worth your attention"),
    ("fyi", "FYI"),
    ("low priority", "FYI"),
    ("suggested next steps", "Next steps"),
    ("next steps", "Next steps"),
)

_GMAIL_SECTION_ORDER = ("Overview", "Worth your attention", "FYI", "Next steps")


def _normalize_gmail_section_title(raw: str) -> str | None:
    key = re.sub(r"[*_`]", "", raw).strip().lower()
    key = re.sub(r"\s*/\s*.*$", "", key).strip()
    for needle, label in _GMAIL_DIGEST_SECTIONS:
        if key == needle or key.startswith(needle):
            return label
    return None


def _parse_gmail_digest_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        header = re.match(r"^#{1,3}\s+(.+?)\s*$", line.strip())
        if not header:
            header = re.match(r"^\*\*(.+?)\*\*\s*$", line.strip())
        if header:
            if current and buf:
                sections[current] = "\n".join(buf).strip()
            current = _normalize_gmail_section_title(header.group(1))
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if current and buf:
        sections[current] = "\n".join(buf).strip()
    if not sections:
        cleaned = re.sub(r"^You have \*\*\d+ unread messages?\*\*.*?\n+", "", text.strip(), flags=re.I | re.S)
        sections["Overview"] = cleaned.strip()
    return sections


def _render_gmail_bullet_line(line: str, *, indent: str = "    ") -> list[str]:
    raw = line.rstrip()
    stripped = raw.strip()
    if not stripped:
        return [""]
    m = re.match(r"^[-*•]\s+\*\*(.+?)\*\*[:\s—–-]+(.+)$", stripped)
    if m:
        return [f"{indent}• {m.group(1).strip()} — {m.group(2).strip()}"]
    m = re.match(r"^[-*•]\s+\*\*(.+?)\*\*\s*$", stripped)
    if m:
        return [f"{indent}• {m.group(1).strip()}"]
    m = re.match(r"^[-*•]\s+(.+)$", stripped)
    if m:
        body = re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(1))
        return [f"{indent}• {body.strip()}"]
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
    return [f"{indent}{body}"]


def _render_gmail_section_body(body: str) -> list[str]:
    out: list[str] = []
    for line in body.splitlines():
        if re.match(r"^[-*•]\s+", line.strip()):
            out.extend(_render_gmail_bullet_line(line))
        elif not line.strip():
            if out and out[-1] != "":
                out.append("")
        else:
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", line.strip())
            out.append(f"    {text}")
    while out and out[-1] == "":
        out.pop()
    return out


def _gmail_unread_total(
    rows: list[dict[str, Any]],
    estimate: int | None,
    *,
    unread_query: bool,
) -> int:
    if unread_query and estimate is not None:
        return estimate
    return sum(1 for row in rows if row.get("unread"))


def _format_gmail_unread_header(
    shown: int,
    total_unread: int,
    *,
    unread_query: bool,
) -> str:
    if not unread_query:
        return f"{shown} message{'s' if shown != 1 else ''}"
    word = "email" if total_unread == 1 else "emails"
    if total_unread > shown:
        return f"{total_unread} unread {word} (showing {shown})"
    return f"{total_unread} unread {word}"


def _print_gmail_digest(
    summary: str,
    *,
    count: int,
    unread: int,
    total_unread: int | None,
    unread_query: bool,
    range_label: str,
    email: str,
) -> None:
    title = "Gmail digest"
    if range_label:
        title += f" · {range_label}"
    print(f"━━━ {title} ━━━")
    print()
    total = total_unread if total_unread is not None else unread
    print(f"  {_format_gmail_unread_header(count, total, unread_query=unread_query)}")
    if email:
        print(f"  {email}")
    print()

    sections = _parse_gmail_digest_sections(summary)
    for label in _GMAIL_SECTION_ORDER:
        body = sections.get(label, "").strip()
        if not body:
            continue
        rule = "─" * len(label)
        print(f"  {label}")
        print(f"  {rule}")
        for line in _render_gmail_section_body(body):
            print(line or "")
        print()

    for label, body in sections.items():
        if label in _GMAIL_SECTION_ORDER or not body.strip():
            continue
        rule = "─" * len(label)
        print(f"  {label}")
        print(f"  {rule}")
        for line in _render_gmail_section_body(body):
            print(line or "")
        print()


def _summarize_gmail_rows(
    rows: list[dict[str, Any]],
    *,
    query: str,
    range_label: str,
    email: str,
    focus: str,
    total_unread: int | None = None,
) -> str:
    from arka.llm.cli import llm_complete

    unread_n = sum(1 for row in rows if row.get("unread"))
    total = total_unread if total_unread is not None else unread_n
    blocks = [f"--- Email {idx} ---\n{_format_gmail_for_summary(row)}" for idx, row in enumerate(rows, 1)]
    corpus = "\n\n".join(blocks)
    char_cap = _gmail_summarize_chars()
    if len(corpus) > char_cap:
        corpus = corpus[:char_cap] + "\n\n[... truncated for model context ...]"

    system = (
        "You are a calm inbox assistant. Summarize the user's Gmail messages accurately.\n\n"
        "Each email includes the full message body when available.\n\n"
        "Output markdown using EXACTLY these section headers (omit any empty section):\n\n"
        "### Overview\n"
        "One or two sentences on what arrived. Do not repeat message counts.\n\n"
        "### Worth your attention\n"
        "Items worth reading or acting on soon: deadlines, replies, policy changes, schedule updates.\n"
        "Use a calm tone — avoid words like 'urgent' unless something is literally due within hours today.\n"
        "Each bullet: **Sender** — subject: one short line on why it matters.\n\n"
        "### FYI\n"
        "Newsletters, promos, automated notices, achievements, low-priority informational mail.\n\n"
        "### Next steps\n"
        "Two to four optional, concrete actions. Helpful, not alarmist.\n\n"
        "Rules: use only facts from the email bodies; never invent emails or deadlines."
    )
    meta = f"Account: {email or 'unknown'}\nQuery: {query}"
    if range_label:
        meta += f"\nRange: {range_label}"
    meta += f"\nTotal messages: {len(rows)} ({total} unread)"
    user = f"{meta}\nFocus: {focus or 'Summarize these emails.'}\n\n{corpus}"
    return llm_complete(system, user, temperature=0.2, task="summarize").strip()


def _parse_gmail_days_from_text(text: str) -> int | None:
    t = text.lower()
    for pat in (
        r"(?:within|last|past)\s+(\d+)\s+days?",
        r"\b(\d+)\s+days?\b",
        r"(?:within|last|past)\s+(\d+)\s+hours?",
    ):
        m = re.search(pat, t, re.I)
        if not m:
            continue
        val = int(m.group(1))
        if "hour" in pat:
            return max(1, (val + 23) // 24)
        return val
    return None


def _parse_gmail_focus(text: str) -> str:
    focus = re.sub(
        r"(?i)^(?:summarize|summary|tldr|digest|brief)\s+(?:my\s+)?(?:unread\s+)?(?:all\s+)?"
        r"(?:gmail|gmails|emails|email|mail|inbox)(?:\s+messages?)?\s*",
        "",
        text.strip(),
    )
    focus = re.sub(
        r"(?i)^(?:my\s+)?(?:unread\s+)?(?:all\s+)?"
        r"(?:gmail|gmails|emails|email|mail|inbox)(?:\s+messages?)?\s*",
        "",
        focus,
    )
    focus = re.sub(
        r"(?i)(?:within|in|from|during|over)\s+(?:the\s+)?(?:last\s+)?(?:past\s+)?"
        r"\d+\s+(?:days?|hours?)\b",
        "",
        focus,
    )
    focus = re.sub(r"(?i)\b(today|unread|all)\b", "", focus)
    focus = focus.strip(" .,-")
    if re.fullmatch(
        r"(?i)(?:my\s+)?(?:unread\s+)?(?:all\s+)?(?:gmail|gmails|emails|email|mail|inbox)s?",
        focus,
    ):
        return ""
    return focus


_DRAFT_TRIGGER = re.compile(
    r"(?i)(?:"
    r"\b(?:draft|compose|write)\s+(?:an?\s+)?email\b"
    r"|\bemail\s+(?:to|for)\s+"
    r"|\bemail\s+[a-z][\w-]{0,31}\s+(?:about|regarding)\b"
    r"|\bsend\s+(?:an?\s+)?(?:email\s+)?to\s+"
    r")"
)
_EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_BIRTHDAY_INTENT = re.compile(
    r"(?i)^(?:happy\s+birthday|birthday\s+wishes?|birthday\s+greeting|wish(?:ing)?\s+(?:them\s+)?(?:a\s+)?happy\s+birthday)(?:[!.\s]*)$"
)
_THANK_YOU_INTENT = re.compile(r"(?i)^(?:thank\s+you|thanks)(?:\s+for\s+.+)?[!.\s]*$")


def _sender_signoff(sender_email: str) -> str:
    if not sender_email or "@" not in sender_email:
        return "Best wishes,"
    local = sender_email.split("@", 1)[0]
    name = re.split(r"[._+-]", local)[0]
    if len(name) >= 2 and not re.fullmatch(r"\d+", name):
        return f"Best wishes,\n{name[:1].upper()}{name[1:]}"
    return "Best wishes,"


def _normalize_draft_about(about: str) -> str:
    """Strip shell-quote damage from fish naive space-splitting."""
    topic = about.strip().strip("'\"")
    if topic.lower() == "happy":
        return "happy birthday"
    if topic.lower().startswith("happy ") and "birthday" not in topic.lower():
        return f"{topic} birthday"
    return topic


def _draft_intent_template(about: str, *, sender_email: str = "") -> tuple[str, str] | None:
    """Deterministic drafts for short, unambiguous intents (skip LLM drift)."""
    topic = _normalize_draft_about(about)
    if not topic:
        return None
    signoff = _sender_signoff(sender_email)
    if _BIRTHDAY_INTENT.match(topic) or topic.lower() in {"birthday", "happy birthday"}:
        return (
            "Happy Birthday!",
            f"Hi,\n\nWishing you a very happy birthday! Hope your day is filled with joy, laughter, and everything you love.\n\n{signoff}",
        )
    if _THANK_YOU_INTENT.match(topic):
        detail = re.sub(r"(?i)^thank\s+you\s+", "", topic).strip() or "your help"
        if detail.lower().startswith("for "):
            detail = detail[4:].strip()
        return (
            "Thank you",
            f"Hi,\n\nThank you for {detail}. I really appreciate it.\n\n{signoff}",
        )
    return None


def _draft_recipient_token(t: str) -> tuple[str, str | None]:
    """Return ``(to_email, contact_name)`` for a draft NL request."""
    emails = _EMAIL_ADDR.findall(t)
    if emails:
        to_addr = emails[0]
        contact_name: str | None = None
        try:
            from arka.integrations.email_contacts import extract_contact_name_from_text, resolve_contact

            alias = extract_contact_name_from_text(t)
            if alias and resolve_contact(alias) == to_addr:
                contact_name = alias
        except ImportError:
            pass
        return to_addr, contact_name

    try:
        from arka.integrations.email_contacts import resolve_recipient_from_text

        resolved = resolve_recipient_from_text(t)
        if resolved:
            return resolved
    except ImportError:
        pass
    return "", None


def parse_gmail_draft_request(text: str) -> dict[str, str] | None:
    """Parse NL like ``draft an email to a@b.com about …`` or ``send to ceo …``."""
    t = text.strip()
    if not t or not _DRAFT_TRIGGER.search(t):
        return None
    if re.search(r"(?i)\b(?:unread|inbox|summarize|check\s+(?:my\s+)?(?:mail|email|gmail))\b", t):
        return None
    to_addr, contact_name = _draft_recipient_token(t)
    if not to_addr:
        return None
    about = ""
    for pat in (
        r"(?i)\b(?:about|regarding|re:|on the topic of)\s+(.+)",
        r"(?i)\b(?:to|for)\s+\S+@\S+\s+(?:about|regarding)\s+(.+)",
    ):
        match = re.search(pat, t)
        if match:
            about = match.group(1).strip()
            break
    if not about and contact_name:
        for pat in (
            r"(?i)\b(?:to|for)\s+" + re.escape(contact_name) + r"\s+(?:about|regarding)\s+(.+)",
            r"(?i)\b(?:to|for)\s+" + re.escape(contact_name) + r"\s+(.+)",
            r"(?i)\bemail\s+" + re.escape(contact_name) + r"\s+(?:about|regarding)\s+(.+)",
            r"(?i)\bsend\s+(?:an?\s+)?(?:email\s+)?to\s+" + re.escape(contact_name) + r"\s+(.+)",
        ):
            match = re.search(pat, t)
            if match:
                about = match.group(1).strip()
                break
    if not about:
        for pat in (
            r"(?i)\b(?:to|for)\s+" + re.escape(to_addr) + r"\s+(.+)",
        ):
            match = re.search(pat, t)
            if match:
                about = match.group(1).strip()
                break
    if not about:
        about = _DRAFT_TRIGGER.sub("", t).strip()
        about = re.sub(r"(?i)\bto\s+" + re.escape(to_addr) + r"\b", "", about).strip()
        if contact_name:
            about = re.sub(
                r"(?i)\b(?:to|for)\s+" + re.escape(contact_name) + r"\b",
                "",
                about,
            ).strip()
    about = about.strip(" .,-")
    if len(about) < 3:
        return None
    result = {"to": to_addr, "about": about}
    if contact_name:
        result["contact_name"] = contact_name
    return result


def build_gmail_draft_argv_from_nl(text: str) -> list[str]:
    parsed = parse_gmail_draft_request(text)
    if not parsed:
        return []
    return ["gmail", "--draft", "--to", parsed["to"], "--about", parsed["about"]]


def _parse_compose_output(text: str) -> tuple[str, str]:
    subject = ""
    body_lines: list[str] = []
    mode = "seek"
    for line in text.splitlines():
        stripped = line.strip()
        if mode == "seek":
            subj = re.match(r"(?i)^subject:\s*(.+)", stripped)
            if subj:
                subject = subj.group(1).strip()
                mode = "body"
                continue
            if re.match(r"(?i)^body:\s*$", stripped):
                mode = "body"
                continue
        if mode == "body":
            if re.match(r"(?i)^body:\s*$", stripped):
                continue
            body_lines.append(line.rstrip())
    body = "\n".join(body_lines).strip()
    if not subject and not body:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return "", ""
        if len(lines) == 1:
            return lines[0][:120], lines[0]
        return lines[0][:120], "\n".join(lines[1:]).strip()
    return subject, body


def compose_draft_email(*, to: str, about: str, sender_email: str = "") -> tuple[str, str, str]:
    about = _normalize_draft_about(about)
    history_context = ""
    try:
        from arka.integrations.email_contacts import compose_history_context

        history_context = compose_history_context(to=to, about=about)
    except ImportError:
        pass
    templated = _draft_intent_template(about, sender_email=sender_email)
    if templated:
        return templated[0], templated[1], "built-in template (no LLM)"

    from arka.llm.cli import llm_complete

    sender = sender_email or "the sender"
    system = (
        "You write email drafts. The user's topic is the PRIMARY intent — follow it literally.\n"
        "Match tone to the topic: warm/casual for birthdays and thanks, professional for work.\n"
        "Output EXACTLY:\n"
        "Subject: <one line that reflects the topic>\n"
        "Body:\n<plain-text email body>\n\n"
        "Rules: no markdown, no essay, no text after the body. Under 200 words unless needed. "
        "Do not change or ignore the user's topic."
    )
    if history_context:
        system += (
            "\nIf prior drafts to this recipient are listed below, do not repeat the same wording "
            "or send an identical message — add new detail or a clearly different angle."
        )
    user = (
        f"To: {to}\n"
        f"From: {sender}\n"
        f"Write an email about this topic (subject and body must match it): {about}"
    )
    if history_context:
        user += f"\n\n{history_context}"
    raw = llm_complete(system, user, temperature=0.3, task="summarize").strip()
    subject, body = _parse_compose_output(raw)
    if not subject:
        subject = about[:80].strip().rstrip(".") or "Message"
    if not body:
        body = raw.strip()
    composer = "unknown model"
    try:
        from arka.output import active_model_label
        from arka.llm.fallback import model_label

        composer = active_model_label() or model_label(task="summarize") or composer
    except Exception:
        pass
    return subject, body, composer


def _encode_draft_raw(*, to: str, subject: str, body: str, sender: str = "") -> str:
    msg = EmailMessage()
    if sender:
        msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")


def _gmail_draft_error_hint(exc: RuntimeError) -> str:
    msg = str(exc).lower()
    if "403" in msg and any(k in msg for k in ("insufficient", "scope", "permission", "access not configured")):
        return "Tip: re-authorize Gmail compose — run: arka google login"
    return ""


def create_gmail_draft(*, to: str, subject: str, body: str, sender: str = "") -> str:
    raw = _encode_draft_raw(to=to, subject=subject, body=body, sender=sender)
    try:
        result = oauth.api_request(
            "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
            method="POST",
            body={"message": {"raw": raw}},
        )
    except RuntimeError as exc:
        hint = _gmail_draft_error_hint(exc)
        if hint:
            raise RuntimeError(f"{exc}\n{hint}") from exc
        raise
    draft_id = str(result.get("id") or "")
    if not draft_id:
        raise RuntimeError("Gmail API did not return a draft id")
    return draft_id


def cmd_gmail_draft(args: argparse.Namespace) -> int:
    to = str(getattr(args, "to", None) or "").strip()
    about = str(getattr(args, "about", None) or "").strip()
    subject = str(getattr(args, "subject", None) or "").strip()
    body = str(getattr(args, "body", None) or "").strip()
    nl_text = " ".join(getattr(args, "draft_text", []) or []).strip()
    contact_name = ""

    if not to and nl_text:
        parsed = parse_gmail_draft_request(nl_text)
        if parsed:
            to = parsed["to"]
            about = parsed["about"]
            contact_name = str(parsed.get("contact_name") or "")
    if not to:
        unknown = ""
        try:
            from arka.integrations.email_contacts import extract_contact_name_from_text

            alias = extract_contact_name_from_text(nl_text)
            if alias:
                unknown = (
                    f"\nUnknown contact {alias!r}. Save it with:\n"
                    f"  arka email_contacts add {alias} {alias}@example.com\n"
                    f"Or: remember {alias} email is {alias}@example.com"
                )
        except ImportError:
            pass
        print(
            "Usage: arka google gmail --draft --to EMAIL --about \"topic\"\n"
            "       arka google gmail --draft \"email to you@example.com about …\"\n"
            "       arka google gmail --draft \"send to ceo about project update\""
            + unknown,
            file=sys.stderr,
        )
        return 1
    if not about and not body:
        print("Provide --about or --body for the draft content.", file=sys.stderr)
        return 1

    if not contact_name:
        try:
            from arka.integrations.email_contacts import extract_contact_name_from_text, resolve_contact

            alias = extract_contact_name_from_text(nl_text) or ""
            if alias and resolve_contact(alias) == to:
                contact_name = alias
        except ImportError:
            pass

    try:
        from arka.integrations.email_contacts import find_similar_draft, format_duplicate_warning

        similar = find_similar_draft(to=to, about=about)
        if similar:
            print(format_duplicate_warning(similar))
    except ImportError:
        pass

    email = oauth.signed_in_email() or ""
    composer = ""
    if not body:
        gen_subject, gen_body, composer = compose_draft_email(to=to, about=about, sender_email=email)
        if not subject:
            subject = gen_subject
        body = gen_body

    if getattr(args, "dry_run", False):
        print(f"To: {to}")
        if contact_name:
            print(f"Contact: {contact_name}")
        print(f"Subject: {subject}")
        if composer:
            print(f"Composer: {composer}")
        print()
        print(body)
        return 0

    draft_id = create_gmail_draft(to=to, subject=subject, body=body, sender=email)
    try:
        from arka.integrations.email_contacts import record_draft_history

        record_draft_history(
            to=to,
            subject=subject,
            about=about,
            body=body,
            draft_id=draft_id,
            account=email,
            contact_name=contact_name or None,
        )
    except ImportError:
        pass
    print(f"✓ Gmail draft saved (id: {draft_id})")
    print(f"  To: {to}")
    if contact_name:
        print(f"  Contact: {contact_name}")
    print(f"  Subject: {subject}")
    if composer:
        print(f"  Composer: {composer}")
    if email:
        print(f"  Account: {email}")
    print("  Open Gmail → Drafts to review before sending.")
    return 0


def cmd_parse_draft(args: argparse.Namespace) -> int:
    argv = build_gmail_draft_argv_from_nl(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_gmail_argv_from_nl(text: str, *, summarize: bool = False) -> list[str]:
    """Turn natural language into ``gmail`` CLI args."""
    t = text.strip()
    lower = t.lower()
    argv = ["gmail"]
    if summarize:
        argv.append("--summarize")
    unread = bool(re.search(r"\bunread\b", lower))
    if unread:
        argv.append("--unread")
    days = _parse_gmail_days_from_text(lower)
    if days:
        argv.extend(["--days", str(days)])
    elif re.search(r"\btoday\b", lower):
        argv.append("--today")
    if re.search(r"\ball\b", lower):
        argv.append("--all")
    elif unread and not days and "today" not in lower:
        argv.append("--all")
    elif summarize:
        argv.append("--all")
    elif days:
        argv.extend(["--limit", "100"])
    focus = _parse_gmail_focus(t) if summarize else ""
    if focus:
        argv.extend(["--focus", focus])
    if summarize and not days and "today" not in lower and not unread:
        argv.extend(["--days", "2", "--all"])
    return argv


def cmd_gmail(args: argparse.Namespace) -> int:
    if getattr(args, "draft", False):
        return cmd_gmail_draft(args)

    rows, query, range_label, estimate = _load_gmail_rows(args)
    email = oauth.signed_in_email()

    if not rows:
        print("No matching emails.")
        if email:
            print(f"Account: {email}", file=sys.stderr)
        if range_label:
            print(f"Range: {range_label}", file=sys.stderr)
        return 0

    unread_query = bool(args.unread)
    total_unread = _gmail_unread_total(rows, estimate, unread_query=unread_query)

    if getattr(args, "summarize", False):
        focus = str(getattr(args, "focus", None) or "").strip() or "Summarize these emails."
        unread_n = sum(1 for row in rows if row.get("unread"))
        if estimate is not None and estimate > len(rows):
            print(
                f"(Summarized first {len(rows)} of ~{estimate}; "
                f"raise GMAIL_SUMMARIZE_MAX for more.)",
                file=sys.stderr,
            )
        summary = _summarize_gmail_rows(
            rows,
            query=query,
            range_label=range_label,
            email=email or "",
            focus=focus,
            total_unread=total_unread if unread_query else None,
        )
        _print_gmail_digest(
            summary,
            count=len(rows),
            unread=unread_n,
            total_unread=total_unread,
            unread_query=unread_query,
            range_label=range_label,
            email=email or "",
        )
        return 0

    if unread_query:
        header = f"Gmail — {_format_gmail_unread_header(len(rows), total_unread, unread_query=True)}"
    else:
        header = f"Gmail — {len(rows)} message(s)"
    if range_label:
        header += f" · {range_label}"
    header += f"\nQuery: {query}"
    if email:
        header += f"\nAccount: {email}"
    if not unread_query and estimate is not None and estimate > len(rows):
        header += f"\n(Gmail estimates ~{estimate}; raise GMAIL_MAX or use --all)"
    print(f"{header}\n")

    for row in rows:
        mark = "●" if row.get("unread") else " "
        print(f"{mark} {row['subject']}")
        print(f"    From: {row['sender']}")
        if row.get("date"):
            print(f"    Date: {row['date']}")
        if args.snippet:
            snippet = str(row.get("snippet") or "").strip()
            if snippet:
                print(f"    {snippet[:200]}")
        print()
    return 0


_CALENDAR_EVENT_TYPES = (
    "default",
    "focusTime",
    "outOfOffice",
    "workingLocation",
    "fromGmail",
    "birthday",
)


def _local_iana_tz() -> str:
    """IANA timezone fallback when Google Calendar settings are unavailable."""
    override = os.environ.get("ARKA_TZ", "").strip() or os.environ.get("TZ", "").strip()
    if override and override not in ("UTC", "GMT"):
        return override
    try:
        link = Path("/etc/localtime").resolve()
        parts = link.parts
        if "zoneinfo" in parts:
            idx = parts.index("zoneinfo")
            return "/".join(parts[idx + 1 :])
    except OSError:
        pass
    tzinfo = datetime.now().astimezone().tzinfo
    if tzinfo is not None and getattr(tzinfo, "key", None):
        return str(tzinfo.key)
    return "UTC"


def _google_calendar_tz() -> str:
    """Prefer timezone from Google Calendar account settings."""
    try:
        data = oauth.api_request(
            "https://www.googleapis.com/calendar/v3/users/me/settings/timezone"
        )
        tz = str(data.get("value") or "").strip()
        if tz:
            return tz
    except RuntimeError:
        pass
    return _local_iana_tz()


def _calendar_window(*, week: bool) -> tuple[datetime, datetime, str, str]:
    """Local start/end for today or next 7 days, plus label and IANA tz."""
    tz_name = _google_calendar_tz()
    local_now = datetime.now().astimezone()
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    if week:
        end_local = start_local + timedelta(days=7)
        label = f"next 7 days · from {start_local.strftime('%a %b %d, %Y')}"
    else:
        end_local = start_local + timedelta(days=1)
        label = f"today · {start_local.strftime('%a %b %d, %Y')}"
    return start_local, end_local, label, tz_name


def _list_calendars(*, include_unselected: bool = False) -> list[tuple[str, str]]:
    """Return (calendar_id, summary) for readable calendars on the signed-in account."""
    data = oauth.api_request(
        "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=250"
    )
    rows: list[tuple[str, str]] = []
    for item in data.get("items") or []:
        if item.get("deleted"):
            continue
        if item.get("hidden") and not item.get("primary"):
            continue
        if not include_unselected and item.get("selected") is False:
            continue
        cal_id = str(item.get("id") or "").strip()
        if not cal_id:
            continue
        name = str(item.get("summary") or item.get("summaryOverride") or cal_id)
        rows.append((cal_id, name))
    if not rows:
        rows.append(("primary", "Primary"))
    return rows


def _event_dedupe_key(item: dict[str, Any]) -> tuple[str, str, str]:
    start = item.get("start") or {}
    end = item.get("end") or {}
    title = str(item.get("summary") or "").strip().lower()
    start_raw = str(start.get("dateTime") or start.get("date") or "")
    end_raw = str(end.get("dateTime") or end.get("date") or "")
    return title, start_raw, end_raw


def _event_start_sort_key(item: dict[str, Any]) -> str:
    start = item.get("start") or {}
    if start.get("dateTime"):
        return str(start["dateTime"])
    day = start.get("date") or "9999-12-31"
    return f"{day}T00:00:00"


def _fetch_calendar_events(
    cal_id: str,
    *,
    time_min: datetime,
    time_max: datetime,
    tz_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    cal_enc = quote(cal_id, safe="")
    base = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "maxResults": "250",
        "timeZone": tz_name,
        "showDeleted": "false",
        "showHiddenInvitations": "true",
    }
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while len(items) < max(limit, 1):
        params: list[tuple[str, str]] = [(k, v) for k, v in base.items()]
        for event_type in _CALENDAR_EVENT_TYPES:
            params.append(("eventTypes", event_type))
        if page_token:
            params.append(("pageToken", page_token))
        query = urlencode(params)
        data = oauth.api_request(
            f"https://www.googleapis.com/calendar/v3/calendars/{cal_enc}/events?{query}"
        )
        items.extend(data.get("items") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items[: max(limit, 1)]


_CALENDAR_COHORT_PREFIX = re.compile(
    r"^(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{4}\s*[-–—]\s*",
    re.IGNORECASE,
)


def _short_calendar_label(name: str) -> str:
    """Drop cohort prefixes like 'May 2026 - ' so July events don't look dated wrong."""
    cleaned = _CALENDAR_COHORT_PREFIX.sub("", (name or "").strip()).strip()
    return cleaned or (name or "").strip()


def _event_when_label(dt: datetime, *, dt_end: datetime | None = None) -> str:
    local = dt.astimezone()
    label = local.strftime("%a %b %d, %Y · %I:%M %p")
    if dt_end is not None:
        end_local = dt_end.astimezone()
        if end_local.date() == local.date():
            label += " – " + end_local.strftime("%I:%M %p")
    return label


def _parse_event_time(item: dict[str, Any]) -> tuple[datetime | None, str]:
    start = item.get("start") or {}
    end = item.get("end") or {}
    raw_start = start.get("dateTime") or start.get("date") or ""
    raw_end = end.get("dateTime") or end.get("date") or ""
    if not raw_start:
        return None, ""
    if "T" in raw_start:
        try:
            dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            dt_end = None
            if raw_end and "T" in raw_end:
                dt_end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
            return dt, _event_when_label(dt, dt_end=dt_end)
        except ValueError:
            pass
    # All-day event (date only)
    try:
        day = datetime.strptime(raw_start, "%Y-%m-%d").date()
        label = day.strftime("%a %b %d, %Y") + " · all day"
        return datetime.combine(day, datetime.min.time()), label
    except ValueError:
        return None, raw_start


def _calendar_sources(*, macos_only: bool = False, google_only: bool = False) -> list[str]:
    if macos_only:
        return ["macos"]
    if google_only:
        return ["google"]
    raw = os.environ.get("ARKA_CALENDAR_SOURCES", "").strip().lower()
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip() in {"google", "macos"}]
    if sys.platform == "darwin":
        return ["google", "macos"]
    return ["google"]


def _merge_display_key(*, summary: str, when: str) -> tuple[str, str]:
    return summary.strip().lower(), when.strip()


def _google_events_for_window(
    args: argparse.Namespace,
    *,
    start_local: datetime,
    end_local: datetime,
    tz_name: str,
) -> tuple[list[dict[str, Any]], list[tuple[str, int]], list[tuple[str, str]]]:
    calendars = _list_calendars(include_unselected=bool(args.all_calendars))
    per_cal_limit = 250 if not args.week else max(args.limit, 1)
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    debug_counts: list[tuple[str, int]] = []

    for cal_id, cal_name in calendars:
        try:
            items = _fetch_calendar_events(
                cal_id,
                time_min=start_local,
                time_max=end_local,
                tz_name=tz_name,
                limit=per_cal_limit,
            )
        except RuntimeError as exc:
            print(f"Warning: could not read {cal_name}: {exc}", file=sys.stderr)
            debug_counts.append((cal_name, -1))
            continue
        debug_counts.append((cal_name, len(items)))
        for ev in items:
            key = _event_dedupe_key(ev)
            if not key[0] and not key[1]:
                continue
            if key in merged:
                continue
            _, when = _parse_event_time(ev)
            merged[key] = {
                "summary": ev.get("summary") or "(no title)",
                "when": when,
                "location": ev.get("location") or "",
                "tag": cal_name,
                "source": "google",
                "sort_key": _event_start_sort_key(ev),
            }

    rows = sorted(merged.values(), key=lambda row: row["sort_key"])
    return rows, debug_counts, calendars


def _macos_events_for_today() -> tuple[list[dict[str, Any]], str | None]:
    if macos_calendar is None or not macos_calendar._available():
        return [], None
    return macos_calendar.fetch_today_events()


def cmd_calendar(args: argparse.Namespace) -> int:
    email = oauth.signed_in_email()
    start_local, end_local, label, tz_name = _calendar_window(week=bool(args.week))
    sources = _calendar_sources(
        macos_only=bool(args.macos),
        google_only=bool(args.google_only),
    )

    display: dict[tuple[str, str], dict[str, Any]] = {}
    debug_counts: list[tuple[str, int]] = []
    google_calendars: list[tuple[str, str]] = []
    macos_err: str | None = None

    if "google" in sources:
        try:
            oauth.get_access_token()
        except RuntimeError as exc:
            if sources == ["google"]:
                print(f"Google Calendar: {exc}", file=sys.stderr)
                return 1
            print(f"Warning: Google Calendar unavailable: {exc}", file=sys.stderr)
        else:
            g_rows, debug_counts, google_calendars = _google_events_for_window(
                args,
                start_local=start_local,
                end_local=end_local,
                tz_name=tz_name,
            )
            for row in g_rows:
                key = _merge_display_key(summary=row["summary"], when=row["when"])
                if key not in display:
                    display[key] = row

    if "macos" in sources and not args.week:
        mac_rows, macos_err = _macos_events_for_today()
        if args.debug and macos_err:
            print(f"macOS Calendar: {macos_err}", file=sys.stderr)
        for row in mac_rows:
            key = _merge_display_key(summary=row["summary"], when=row["when"])
            if key not in display:
                display[key] = {
                    "summary": row["summary"],
                    "when": row["when"],
                    "location": "",
                    "tag": row["calendar"],
                    "source": "macos",
                    "sort_key": (
                        row["start"].isoformat()
                        if row.get("start") is not None
                        else row["when"]
                    ),
                }

    events = sorted(display.values(), key=lambda row: row["sort_key"])
    account_line = f"Google: {email}" if email else "Google: (not signed in — arka google login)"

    if args.debug:
        if "google" in sources:
            print(account_line, file=sys.stderr)
            print(
                f"Window: {start_local.isoformat()} → {end_local.isoformat()} ({tz_name})",
                file=sys.stderr,
            )
            for cal_name, count in debug_counts:
                if count < 0:
                    print(f"  ✗ {cal_name}", file=sys.stderr)
                else:
                    print(f"  • {cal_name}: {count} raw event(s)", file=sys.stderr)
        if "macos" in sources and not args.week:
            print(f"macOS Calendar: {len(events)} merged row(s)", file=sys.stderr)
            if macos_err:
                print(f"  {macos_err}", file=sys.stderr)

    if not events:
        print(f"No calendar events for {label}.")
        if "google" in sources:
            print(account_line, file=sys.stderr)
        if macos_err:
            print(f"macOS: {macos_err}", file=sys.stderr)
        print(
            f"(Sources: {', '.join(sources)}. Timezone: {tz_name}. "
            f"Wrong Google account? Run: arka google login)",
            file=sys.stderr,
        )
        return 0

    print(f"Calendar ({label}) — {len(events)} event(s)")
    if "google" in sources and email:
        print(f"{account_line}")
    if args.debug and len(sources) > 1:
        print(f"Sources: {', '.join(sources)}", file=sys.stderr)
    print()

    contributing_tags = {_short_calendar_label(row["tag"]) for row in events}
    show_cal_tags = bool(args.calendars) or len(contributing_tags) > 1
    mixed_sources = (
        len(sources) > 1
        and any(row["source"] == "macos" for row in events)
        and any(row["source"] == "google" for row in events)
    )
    for row in events:
        title = row["summary"]
        when = row["when"]
        loc = row["location"]
        tag = ""
        if show_cal_tags:
            cal_label = _short_calendar_label(row["tag"])
            if mixed_sources:
                src = "macOS" if row["source"] == "macos" else "Google"
                tag = f"[{src}: {cal_label}] "
            else:
                tag = f"[{cal_label}] "
        print(f"• {when}  {tag}{title}")
        if loc:
            print(f"    {loc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Google Calendar and Gmail — sign in via browser URL",
        prog="arka google",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_setup = sub.add_parser("setup", help="Show Google Cloud OAuth setup steps")
    p_setup.add_argument("--no-browser", action="store_true", help="Do not open Google Cloud Console")

    p_login = sub.add_parser("login", help="Sign in with Google (opens browser URL)")
    p_login.add_argument("--no-browser", action="store_true", help="Print URL only; do not open browser")
    p_login.add_argument("--timeout", type=int, default=180, help="Seconds to wait for callback")
    p_login.add_argument(
        "--add",
        action="store_true",
        help="Link an additional Google account (stored separately from primary login)",
    )
    p_login.add_argument(
        "--account",
        help="Optional account alias for --add (e.g. student, personal, work)",
    )

    sub.add_parser("status", help="Show sign-in status")
    p_logout = sub.add_parser("logout", help="Remove stored Google tokens")
    p_logout.add_argument("--account", help="Remove one linked account by alias/email key")
    p_logout.add_argument("--all", action="store_true", help="Remove all linked Google tokens")

    p_gmail = sub.add_parser("gmail", help="List Gmail messages")
    p_gmail.add_argument("--unread", action="store_true", help="Unread only")
    p_gmail.add_argument("--today", action="store_true", help="From the last 24 hours")
    p_gmail.add_argument("--days", type=int, default=0, help="Messages from the last N calendar days")
    p_gmail.add_argument("--hours", type=int, default=0, help="Messages from the last N hours")
    p_gmail.add_argument(
        "--rolling",
        action="store_true",
        help="Use rolling newer_than window instead of calendar days",
    )
    p_gmail.add_argument("-q", "--query", help="Extra Gmail search query")
    p_gmail.add_argument(
        "--all",
        action="store_true",
        help="Fetch all matching messages (paginated, up to GMAIL_MAX)",
    )
    p_gmail.add_argument("-n", "--limit", type=int, default=10, help="Max messages (ignored with --all)")
    p_gmail.add_argument("--snippet", action="store_true", help="Show snippet preview")
    p_gmail.add_argument(
        "--summarize",
        action="store_true",
        help="Summarize matching emails with AI (reads full message bodies)",
    )
    p_gmail.add_argument(
        "--focus",
        help="Focus for --summarize (default: general inbox summary)",
    )
    p_gmail.add_argument(
        "--draft",
        action="store_true",
        help="Compose with AI and save a Gmail draft (requires login)",
    )
    p_gmail.add_argument("--to", help="Draft recipient email (with --draft)")
    p_gmail.add_argument("--about", help="What the draft should say (with --draft)")
    p_gmail.add_argument("--subject", help="Override draft subject (with --draft)")
    p_gmail.add_argument("--body", help="Use this body instead of AI (with --draft)")
    p_gmail.add_argument(
        "--dry-run",
        action="store_true",
        help="Print draft without saving to Gmail",
    )
    p_gmail.add_argument(
        "draft_text",
        nargs="*",
        help="Natural-language draft request when using --draft without --to/--about",
    )

    p_inbox = sub.add_parser(
        "inbox",
        aliases=["unified-inbox", "unified_inbox"],
        help="Unified unread inbox across all linked Google accounts",
    )
    p_inbox.add_argument("--unread", action="store_true", help="Unread only")
    p_inbox.add_argument("--today", action="store_true", help="From the last 24 hours")
    p_inbox.add_argument("--days", type=int, default=0, help="Messages from the last N calendar days")
    p_inbox.add_argument("--hours", type=int, default=0, help="Messages from the last N hours")
    p_inbox.add_argument(
        "--rolling",
        action="store_true",
        help="Use rolling newer_than window instead of calendar days",
    )
    p_inbox.add_argument("-q", "--query", help="Extra Gmail search query")
    p_inbox.add_argument(
        "--all",
        action="store_true",
        help="Fetch all matching messages (paginated, up to GMAIL_MAX)",
    )
    p_inbox.add_argument("-n", "--limit", type=int, default=10, help="Max messages per account")
    p_inbox.add_argument("--snippet", action="store_true", help="Show snippet preview")
    p_inbox.add_argument(
        "--summarize",
        action="store_true",
        help="Summarize matching emails with AI across all linked accounts",
    )
    p_inbox.add_argument(
        "--focus",
        help="Focus for --summarize (default: unified inbox summary)",
    )

    p_parse_draft = sub.add_parser("parse-draft", help="Parse NL → gmail --draft args (internal)")
    p_parse_draft.add_argument("text", nargs="+")
    p_parse_draft.set_defaults(func=cmd_parse_draft)

    p_parse_email = sub.add_parser(
        "parse-email-summary",
        help="Parse NL → summarize args (internal)",
    )
    p_parse_email.add_argument("text", nargs="+")

    p_auto = sub.add_parser(
        "auto-draft",
        aliases=["auto_draft"],
        help="Auto-draft Gmail replies when new inbound mail arrives",
    )
    p_auto.add_argument("auto_args", nargs=argparse.REMAINDER)

    p_sum = sub.add_parser("summarize", help="Summarize a single Gmail message with AI")
    p_sum.add_argument("message_id", nargs="?", help="Gmail message ID")
    p_sum.add_argument("--latest", action="store_true", help="Most recent inbox message")
    p_sum.add_argument("--latest-unread", action="store_true", help="Most recent unread message")
    p_sum.add_argument("--thread", help="Gmail thread ID")
    p_sum.add_argument("--from", dest="sender", help="Sender name or email")
    p_sum.add_argument("--about", help="Subject/body search terms")
    p_sum.add_argument("-q", "--query", help="Extra Gmail search query")
    p_sum.add_argument("--account", help="Linked account alias or email key")
    p_sum.add_argument("--focus", help="Optional focus for the summary")

    p_cal = sub.add_parser("calendar", aliases=["cal"], help="List calendar events")
    p_cal.add_argument("--today", action="store_true", help="Events today (default)")
    p_cal.add_argument("--week", action="store_true", help="Events in the next 7 days")
    p_cal.add_argument(
        "--all-calendars",
        action="store_true",
        help="Include calendars unchecked in Google Calendar sidebar",
    )
    p_cal.add_argument(
        "--google-only",
        action="store_true",
        help="Only query Google Calendar (skip macOS Calendar.app)",
    )
    p_cal.add_argument(
        "--macos",
        action="store_true",
        help="Only query macOS Calendar.app",
    )
    p_cal.add_argument(
        "--calendars",
        action="store_true",
        help="Show which calendar each event came from",
    )
    p_cal.add_argument("--debug", action="store_true", help="Print calendar fetch diagnostics")
    p_cal.add_argument("-n", "--limit", type=int, default=20, help="Max events (week mode)")

    args = parser.parse_args(argv)
    if not args.cmd or args.cmd == "help":
        parser.print_help()
        return 0

    if args.cmd == "parse-draft":
        return cmd_parse_draft(args)
    if args.cmd == "parse-email-summary":
        from arka.integrations.gmail_email_summarize import cmd_parse_email_summary

        return cmd_parse_email_summary(args)

    if args.cmd == "setup":
        _setup_instructions(open_console=not getattr(args, "no_browser", False))
        return 0
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "login":
        return cmd_login(args)
    if args.cmd == "logout":
        return cmd_logout(args)
    if args.cmd in ("inbox", "unified-inbox", "unified_inbox"):
        from arka.integrations.gmail_unified import cmd_unified_inbox

        try:
            return cmd_unified_inbox(args)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.cmd in ("auto-draft", "auto_draft"):
        from arka.integrations.gmail_auto_draft import main as auto_draft_main

        auto_args = [a for a in (getattr(args, "auto_args", None) or []) if a != "--"]
        return auto_draft_main(auto_args or None)
    if args.cmd == "gmail":
        try:
            return cmd_gmail(args)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.cmd == "summarize":
        from arka.integrations.gmail_email_summarize import cmd_gmail_email_summarize

        try:
            return cmd_gmail_email_summarize(args)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.cmd in ("calendar", "cal"):
        try:
            return cmd_calendar(args)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
