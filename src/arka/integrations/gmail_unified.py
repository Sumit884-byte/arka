"""Unified Gmail inbox across multiple linked Google accounts."""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any

from arka.integrations import google_oauth as oauth
from arka.integrations.google_workspace import (
    _format_gmail_unread_header,
    _gmail_fetch_row,
    _gmail_max_results,
    _gmail_query_from_args,
    _gmail_summarize_cap,
    _gmail_summarize_chars,
    _list_gmail_message_ids,
    _parse_gmail_digest_sections,
    _render_gmail_section_body,
    _GMAIL_SECTION_ORDER,
)

_UNIFIED_INBOX_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:unified|combined|merged)\s+inbox\b"
    r"|\ball\s+(?:my\s+)?google\s+accounts?\b.*\b(?:unread|email|gmail|mail|inbox|summar)"
    r"|\b(?:multiple|both|all)\s+(?:google\s+)?accounts?\b.*\b(?:unread|email|gmail|mail|inbox|summar)"
    r"|\b(?:student|personal|work)\b.*\b(?:and|\+)\b.*\b(?:student|personal|work|account)\b.*\b(?:email|gmail|mail|inbox|unread|summar)"
    r"|\b(?:summarize|summary|digest|brief)\b.*\b(?:all|both|multiple)\b.*\b(?:google\s+)?accounts?\b"
    r"|\b(?:email|gmail|mail|inbox)\b.*\b(?:across|from)\b.*\b(?:all|both|multiple)\b.*\b(?:google\s+)?accounts?\b"
    r")"
)


def is_unified_inbox_request(text: str) -> bool:
    return bool(_UNIFIED_INBOX_RE.search(text or ""))


def _sender_email(sender: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", sender or "")
    return (match.group(0) if match else sender or "").strip().lower()


def _gmail_dedupe_key(row: dict[str, Any]) -> tuple[str, str, str]:
    subject = re.sub(r"\s+", " ", str(row.get("subject") or "")).strip().lower()
    sender = _sender_email(str(row.get("sender") or ""))
    date = str(row.get("date") or "").strip()[:16].lower()
    return subject, sender, date


def _account_label(key: str) -> str:
    for row in oauth.list_linked_accounts():
        if row["key"] == key:
            email = str(row.get("email") or "").strip()
            alias = str(row.get("alias") or "").strip()
            if email and alias and alias.lower() not in email.lower():
                return f"{email} ({alias})"
            return email or alias or key
    return key


def _missing_accounts_message() -> str:
    return (
        "No linked Google accounts for unified inbox.\n"
        "  1. arka google setup          # OAuth client in .env\n"
        "  2. arka google login          # first account\n"
        "  3. arka google login --add    # student/personal/work, etc.\n"
        "Optional: GOOGLE_ACCOUNTS=personal@gmail.com,student@school.edu"
    )


def fetch_unified_gmail_rows(
    args: argparse.Namespace,
    *,
    account_keys: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str], str, str, int, list[str]]:
    """Fetch and merge Gmail rows across linked accounts."""
    keys = account_keys if account_keys is not None else oauth.resolve_account_keys()
    if not keys:
        raise RuntimeError(_missing_accounts_message())

    query, range_label = _gmail_query_from_args(args)
    summarize = bool(getattr(args, "summarize", False))
    if summarize:
        cap = _gmail_summarize_cap()
        if args.all:
            max_results = _gmail_max_results(fetch_all=True, limit=0)
            max_results = min(max_results, cap)
        else:
            max_results = min(max(args.limit, 1), cap)
    else:
        max_results = _gmail_max_results(fetch_all=bool(args.all), limit=int(args.limit))

    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    account_emails: list[str] = []
    errors: list[str] = []
    total_unread = 0
    unread_query = bool(args.unread)

    for key in keys:
        label = _account_label(key)
        account_emails.append(label)
        try:
            with oauth.using_account(key):
                message_ids, estimate = _list_gmail_message_ids(query, max_results=max_results)
                if unread_query:
                    if estimate is not None:
                        total_unread += estimate
                    else:
                        total_unread += len(message_ids)
                include_body = summarize
                for mid in message_ids:
                    row = _gmail_fetch_row(mid, include_body=include_body)
                    row["account"] = label
                    row["account_key"] = key
                    dedupe = _gmail_dedupe_key(row)
                    existing = merged.get(dedupe)
                    if existing is None:
                        merged[dedupe] = row
                        continue
                    accounts = set(str(existing.get("accounts") or [existing.get("account")]).split(" · "))
                    accounts.add(label)
                    existing["accounts"] = " · ".join(sorted(accounts))
        except RuntimeError as exc:
            errors.append(f"{label}: {exc}")

    if errors and not merged:
        raise RuntimeError("\n".join(errors))

    rows = list(merged.values())
    rows.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
    if summarize and len(rows) > _gmail_summarize_cap():
        rows = rows[: _gmail_summarize_cap()]
    return rows, account_emails, query, range_label, total_unread, errors


def _format_unified_gmail_for_summary(row: dict[str, Any]) -> str:
    accounts = str(row.get("accounts") or row.get("account") or "unknown")
    lines = [
        f"Account: {accounts}",
        f"From: {row['sender']}",
        f"Date: {row['date']}",
        f"Subject: {row['subject']}",
        f"Unread: {'yes' if row.get('unread') else 'no'}",
    ]
    body = str(row.get("body") or row.get("body_preview") or row.get("snippet") or "").strip()
    if body:
        lines.append(f"Body:\n{body}")
    return "\n".join(lines)


def _summarize_unified_gmail_rows(
    rows: list[dict[str, Any]],
    *,
    query: str,
    range_label: str,
    accounts: list[str],
    focus: str,
    total_unread: int | None = None,
    errors: list[str] | None = None,
) -> str:
    from arka.llm.cli import llm_complete

    unread_n = sum(1 for row in rows if row.get("unread"))
    total = total_unread if total_unread is not None else unread_n
    blocks = [
        f"--- Email {idx} ---\n{_format_unified_gmail_for_summary(row)}"
        for idx, row in enumerate(rows, 1)
    ]
    corpus = "\n\n".join(blocks)
    char_cap = _gmail_summarize_chars()
    if len(corpus) > char_cap:
        corpus = corpus[:char_cap] + "\n\n[... truncated for model context ...]"

    system = (
        "You are a calm inbox assistant. Summarize the user's Gmail messages accurately.\n\n"
        "Messages may come from multiple Google accounts — keep account labels when helpful.\n"
        "Each email includes the full message body when available.\n\n"
        "Output markdown using EXACTLY these section headers (omit any empty section):\n\n"
        "### Overview\n"
        "One or two sentences on what arrived across all accounts. Do not repeat message counts.\n\n"
        "### Worth your attention\n"
        "Items worth reading or acting on soon: deadlines, replies, policy changes, schedule updates.\n"
        "Use a calm tone — avoid words like 'urgent' unless something is literally due within hours today.\n"
        "Each bullet: **Sender** — subject: one short line on why it matters (note account if not obvious).\n\n"
        "### FYI\n"
        "Newsletters, promos, automated notices, achievements, low-priority informational mail.\n\n"
        "### Next steps\n"
        "Two to four optional, concrete actions. Helpful, not alarmist.\n\n"
        "Rules: use only facts from the email bodies; never invent emails or deadlines."
    )
    meta = "Accounts: " + ", ".join(accounts)
    meta += f"\nQuery: {query}"
    if range_label:
        meta += f"\nRange: {range_label}"
    meta += f"\nTotal messages: {len(rows)} ({total} unread across accounts)"
    if errors:
        meta += "\nWarnings: " + "; ".join(errors)
    user = f"{meta}\nFocus: {focus or 'Summarize these emails across all linked Google accounts.'}\n\n{corpus}"
    return llm_complete(system, user, temperature=0.2, task="summarize").strip()


def _print_unified_gmail_digest(
    summary: str,
    *,
    count: int,
    unread: int,
    total_unread: int | None,
    unread_query: bool,
    range_label: str,
    accounts: list[str],
    errors: list[str],
) -> None:
    title = "Unified inbox digest"
    if range_label:
        title += f" · {range_label}"
    print(f"━━━ {title} ━━━")
    print()
    total = total_unread if total_unread is not None else unread
    print(f"  {_format_gmail_unread_header(count, total, unread_query=unread_query)}")
    if accounts:
        print(f"  Accounts: {', '.join(accounts)}")
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

    if errors:
        print("Warnings:", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)


def build_unified_inbox_argv_from_nl(text: str, *, summarize: bool = True) -> list[str]:
    t = text.strip()
    lower = t.lower()
    argv = ["inbox"]
    if summarize:
        argv.append("--summarize")
    if re.search(r"\bunread\b", lower):
        argv.append("--unread")
    from arka.integrations.google_workspace import _parse_gmail_days_from_text

    days = _parse_gmail_days_from_text(lower)
    if days:
        argv.extend(["--days", str(days)])
    elif re.search(r"\btoday\b", lower):
        argv.append("--today")
    if re.search(r"\ball\b", lower) or re.search(r"\bunread\b", lower) or summarize:
        argv.append("--all")
    if summarize and not days and "today" not in lower and not re.search(r"\bunread\b", lower):
        argv.extend(["--days", "2", "--all"])
    return argv


def cmd_unified_inbox(args: argparse.Namespace) -> int:
    try:
        rows, accounts, query, range_label, total_unread, errors = fetch_unified_gmail_rows(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not rows:
        print("No matching emails across linked Google accounts.")
        if accounts:
            print(f"Accounts checked: {', '.join(accounts)}", file=sys.stderr)
        if range_label:
            print(f"Range: {range_label}", file=sys.stderr)
        if errors:
            for err in errors:
                print(f"Warning: {err}", file=sys.stderr)
        return 0

    unread_query = bool(args.unread)
    unread_n = sum(1 for row in rows if row.get("unread"))

    if getattr(args, "summarize", False):
        focus = str(getattr(args, "focus", None) or "").strip() or (
            "Summarize unread email across all linked Google accounts."
        )
        summary = _summarize_unified_gmail_rows(
            rows,
            query=query,
            range_label=range_label,
            accounts=accounts,
            focus=focus,
            total_unread=total_unread if unread_query else None,
            errors=errors,
        )
        _print_unified_gmail_digest(
            summary,
            count=len(rows),
            unread=unread_n,
            total_unread=total_unread,
            unread_query=unread_query,
            range_label=range_label,
            accounts=accounts,
            errors=errors,
        )
        return 0

    header = f"Unified inbox — {len(rows)} message(s)"
    if unread_query:
        header = f"Unified inbox — {_format_gmail_unread_header(len(rows), total_unread, unread_query=True)}"
    if range_label:
        header += f" · {range_label}"
    header += f"\nQuery: {query}"
    if accounts:
        header += f"\nAccounts: {', '.join(accounts)}"
    print(f"{header}\n")

    for row in rows:
        mark = "●" if row.get("unread") else " "
        acct = str(row.get("account") or "")
        acct_tag = f"[{acct}] " if acct else ""
        print(f"{mark} {acct_tag}{row['subject']}")
        print(f"    From: {row['sender']}")
        if row.get("date"):
            print(f"    Date: {row['date']}")
        if args.snippet:
            snippet = str(row.get("snippet") or "").strip()
            if snippet:
                print(f"    {snippet[:200]}")
        print()
    if errors:
        for err in errors:
            print(f"Warning: {err}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    from arka.integrations.google_workspace import main as google_main

    extra = list(argv or [])
    if not extra:
        extra = ["--summarize", "--unread", "--all"]
    return google_main(["inbox", *extra])
