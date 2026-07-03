#!/usr/bin/env python3
"""Google Calendar and Gmail via OAuth — arka google login | gmail | calendar."""

from __future__ import annotations

import argparse
import base64
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from arka.integrations import google_oauth as oauth

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
        print(f"Looking for GOOGLE_OAUTH_CLIENT_ID or GOOGLE_CLIENT_ID.")
        print(f"Env file: {_env_path()}")
        return 1
    tokens = oauth.load_tokens()
    if not tokens:
        print("Not signed in.")
        print(f"Run: arka google login")
        print(f"Redirect URI for Google Cloud: {oauth.redirect_uri()}")
        return 1
    email = tokens.get("email") or "unknown"
    print(f"Signed in as {email}")
    print(f"Scopes: Gmail (read/send), Calendar (read/events)")
    print(f"Token file: {oauth._token_file()}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    if not oauth.credentials_configured():
        _missing_credentials_message(open_console=not args.no_browser)
        return 1
    try:
        merged = oauth.run_login(open_browser=not args.no_browser, timeout=args.timeout)
    except RuntimeError as exc:
        err = str(exc)
        print(f"Sign-in failed: {err}", file=sys.stderr)
        if "redirect_uri" in err.lower() or "invalid_client" in err.lower():
            print(
                f"\nTip: add this redirect URI to your OAuth client in Google Cloud Console:\n"
                f"  {oauth.redirect_uri()}\n",
                file=sys.stderr,
            )
        return 1
    email = merged.get("email") or "your Google account"
    print(f"✓ Signed in as {email}")
    print("Try: arka google gmail --unread")
    print("     arka google calendar --today")
    return 0


def cmd_logout() -> int:
    oauth.clear_tokens()
    print("Signed out of Google (local tokens removed).")
    return 0


def _decode_header(payload: dict[str, Any], name: str) -> str:
    for row in payload.get("payload", {}).get("headers") or []:
        if (row.get("name") or "").lower() == name.lower():
            return str(row.get("value") or "")
    return ""


def _decode_body(payload: dict[str, Any]) -> str:
    def walk(part: dict[str, Any]) -> str:
        mime = part.get("mimeType") or ""
        body = part.get("body") or {}
        data = body.get("data")
        if data and mime.startswith("text/plain"):
            try:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            except Exception:
                return ""
        for child in part.get("parts") or []:
            text = walk(child)
            if text:
                return text
        return ""

    return walk(payload.get("payload") or {})


def cmd_gmail(args: argparse.Namespace) -> int:
    q_parts: list[str] = []
    if args.unread:
        q_parts.append("is:unread")
    if args.today:
        q_parts.append("newer_than:1d")
    if args.query:
        q_parts.append(args.query)
    query = " ".join(q_parts) or "in:inbox"

    params = f"maxResults={args.limit}&q={quote(query)}"
    listing = oauth.api_request(f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{params}")
    messages = listing.get("messages") or []
    if not messages:
        print("No matching emails.")
        return 0

    print(f"Gmail ({query}) — {len(messages)} message(s)\n")
    for row in messages:
        mid = row.get("id")
        if not mid:
            continue
        detail = oauth.api_request(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}?format=metadata"
            "&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
        )
        subject = _decode_header(detail, "Subject") or "(no subject)"
        sender = _decode_header(detail, "From") or "unknown"
        date = _decode_header(detail, "Date") or ""
        labels = ", ".join(detail.get("labelIds") or [])
        unread = "UNREAD" in labels
        mark = "●" if unread else " "
        print(f"{mark} {subject}")
        print(f"    From: {sender}")
        if date:
            print(f"    Date: {date}")
        if args.snippet:
            snippet = str(detail.get("snippet") or "").strip()
            if snippet:
                print(f"    {snippet[:200]}")
        print()
    return 0


def _parse_event_time(item: dict[str, Any]) -> tuple[datetime | None, str]:
    start = item.get("start") or {}
    raw = start.get("dateTime") or start.get("date") or ""
    if not raw:
        return None, ""
    if "T" in raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt, dt.astimezone().strftime("%a %b %d · %I:%M %p")
        except ValueError:
            pass
    return None, raw


def cmd_calendar(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    if args.week:
        end = now + timedelta(days=7)
        label = "next 7 days"
    else:
        local = datetime.now().astimezone()
        start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        now = start_local.astimezone(timezone.utc)
        end = end_local.astimezone(timezone.utc)
        label = "today"

    params = (
        "singleEvents=true"
        "&orderBy=startTime"
        f"&timeMin={quote(now.isoformat())}"
        f"&timeMax={quote(end.isoformat())}"
        f"&maxResults={args.limit}"
    )
    data = oauth.api_request(
        f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{params}"
    )
    events = data.get("items") or []
    if not events:
        print(f"No calendar events for {label}.")
        return 0

    print(f"Calendar ({label}) — {len(events)} event(s)\n")
    for ev in events:
        _, when = _parse_event_time(ev)
        title = ev.get("summary") or "(no title)"
        loc = ev.get("location") or ""
        print(f"• {when}  {title}")
        if loc:
            print(f"    {loc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Google Calendar and Gmail — sign in via browser URL",
        prog="arka google",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("setup", help="Show Google Cloud OAuth setup steps")

    p_login = sub.add_parser("login", help="Sign in with Google (opens browser URL)")
    p_login.add_argument("--no-browser", action="store_true", help="Print URL only; do not open browser")
    p_login.add_argument("--timeout", type=int, default=180, help="Seconds to wait for callback")

    p_setup = sub.add_parser("setup", help="Show Google Cloud OAuth setup steps")
    p_setup.add_argument("--no-browser", action="store_true", help="Do not open Google Cloud Console")

    sub.add_parser("status", help="Show sign-in status")
    sub.add_parser("logout", help="Remove stored Google tokens")

    p_gmail = sub.add_parser("gmail", help="List Gmail messages")
    p_gmail.add_argument("--unread", action="store_true", help="Unread only")
    p_gmail.add_argument("--today", action="store_true", help="From the last 24 hours")
    p_gmail.add_argument("-q", "--query", help="Extra Gmail search query")
    p_gmail.add_argument("-n", "--limit", type=int, default=10, help="Max messages")
    p_gmail.add_argument("--snippet", action="store_true", help="Show snippet preview")

    p_cal = sub.add_parser("calendar", aliases=["cal"], help="List calendar events")
    p_cal.add_argument("--today", action="store_true", help="Events today (default)")
    p_cal.add_argument("--week", action="store_true", help="Events in the next 7 days")
    p_cal.add_argument("-n", "--limit", type=int, default=20, help="Max events")

    args = parser.parse_args(argv)
    if not args.cmd or args.cmd == "help":
        parser.print_help()
        return 0

    if args.cmd == "setup":
        _setup_instructions(open_console=not getattr(args, "no_browser", False))
        return 0
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "login":
        return cmd_login(args)
    if args.cmd == "logout":
        return cmd_logout()
    if args.cmd == "gmail":
        try:
            return cmd_gmail(args)
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
