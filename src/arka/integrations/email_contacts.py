#!/usr/bin/env python3
"""Named email contacts and draft history — resolve aliases like ceo/painter and avoid repeats."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from arka.paths import config_dir, load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"


_CONTACTS_FILE = "email_contacts.json"
_HISTORY_FILE = "email_draft_history.json"
_MAX_CONTACTS = 200
_MAX_HISTORY = 150
_HISTORY_LOOKBACK_DAYS = 90
_DUPLICATE_LOOKBACK_DAYS = 30

_EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_RECIPIENT_SKIP = frozenset(
    {"an", "the", "my", "a", "email", "mail", "someone", "them", "him", "her", "it"}
)

_REMEMBER_RE = re.compile(
    r"(?i)(?:"
    r"(?:remember|save|store|add)\s+(?:email\s+)?contact\s+(?P<name1>[a-z][\w-]{0,31})\s+(?:is\s+)?(?P<email1>\S+@\S+)"
    r"|(?P<name2>[a-z][\w-]{0,31})(?:'s|\s+is)\s+email\s+(?:is|address\s+is)\s+(?P<email2>\S+@\S+)"
    r"|(?P<name3>[a-z][\w-]{0,31})\s+email\s+(?:is|address\s+is)\s+(?P<email3>\S+@\S+)"
    r")"
)
_LIST_RE = re.compile(
    r"(?i)\b(?:list|show)\s+(?:my\s+)?(?:email\s+)?contacts?\b"
)
_DELETE_RE = re.compile(
    r"(?i)\b(?:delete|remove)\s+(?:email\s+)?contact\s+(?P<name>[a-z][\w-]{0,31})\b"
)
_TRIGGER_RE = re.compile(r"(?i)\b(?:email\s+contacts?|contact\s+book|address\s+book)\b")

_CONTACT_IN_TEXT_RE = (
    r"(?i)\b(?:draft|compose|write)\s+(?:an?\s+)?email\s+(?:to|for)\s+(?P<n1>[a-z][\w-]{0,31})\b",
    r"(?i)\bemail\s+(?:to|for)\s+(?P<n2>[a-z][\w-]{0,31})\b",
    r"(?i)\bemail\s+(?P<n4>[a-z][\w-]{0,31})\s+(?:about|regarding)\b",
    r"(?i)\bsend\s+(?:an?\s+)?(?:email\s+)?to\s+(?P<n3>[a-z][\w-]{0,31})\b",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _contacts_path() -> Path:
    path = config_dir() / _CONTACTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _history_path() -> Path:
    path = config_dir() / _HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_contacts() -> list[dict]:
    path = _contacts_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save_contacts(rows: list[dict]) -> None:
    _contacts_path().write_text(
        json.dumps(rows[:_MAX_CONTACTS], indent=2), encoding="utf-8"
    )


def _load_history() -> list[dict]:
    path = _history_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save_history(rows: list[dict]) -> None:
    _history_path().write_text(
        json.dumps(rows[:_MAX_HISTORY], indent=2), encoding="utf-8"
    )


def _normalize_name(name: str) -> str:
    return re.sub(r"[\s_]+", "-", (name or "").strip().lower())


def _normalize_about(about: str) -> str:
    return re.sub(r"\s+", " ", (about or "").strip().lower())


def _word_set(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _about_similar(a: str, b: str) -> bool:
    a_n = _normalize_about(a)
    b_n = _normalize_about(b)
    if not a_n or not b_n:
        return False
    if a_n == b_n:
        return True
    if a_n in b_n or b_n in a_n:
        return min(len(a_n), len(b_n)) >= 8
    overlap = _word_set(a_n) & _word_set(b_n)
    union = _word_set(a_n) | _word_set(b_n)
    return bool(union) and len(overlap) / len(union) >= 0.7


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def add_contact(
    name: str,
    email: str,
    *,
    display: str = "",
    note: str = "",
) -> dict:
    """Add or update a named email contact."""
    key = _normalize_name(name)
    email = (email or "").strip()
    if not key:
        raise ValueError("Contact name is required")
    if not _EMAIL_ADDR.fullmatch(email):
        raise ValueError(f"Invalid email address: {email!r}")

    rows = _load_contacts()
    row = {
        "name": key,
        "email": email,
        "display": (display or name).strip(),
        "note": (note or "").strip(),
        "updated": _now_iso(),
    }
    replaced = False
    for idx, existing in enumerate(rows):
        if str(existing.get("name") or "").lower() == key:
            rows[idx] = row
            replaced = True
            break
    if not replaced:
        rows.insert(0, row)
    _save_contacts(rows)
    return row


def delete_contact(name: str) -> dict:
    key = _normalize_name(name)
    rows = _load_contacts()
    for idx, row in enumerate(rows):
        if str(row.get("name") or "").lower() == key:
            removed = rows.pop(idx)
            _save_contacts(rows)
            return removed
    raise ValueError(f"No email contact named {name!r}")


def get_contact(name: str) -> dict | None:
    key = _normalize_name(name)
    for row in _load_contacts():
        if str(row.get("name") or "").lower() == key:
            return row
    return None


def resolve_contact(name: str) -> str | None:
    row = get_contact(name)
    if not row:
        return None
    return str(row.get("email") or "").strip() or None


def list_contacts(*, limit: int = 50) -> list[dict]:
    return _load_contacts()[: max(1, limit)]


def extract_contact_name_from_text(text: str) -> str | None:
    """Return a contact alias token from a draft-style NL request."""
    if _EMAIL_ADDR.search(text or ""):
        return None
    for pat in _CONTACT_IN_TEXT_RE:
        match = re.search(pat, text or "")
        if not match:
            continue
        name = _normalize_name(next(g for g in match.groups() if g))
        if name and name not in _RECIPIENT_SKIP:
            return name
    return None


def resolve_recipient_from_text(text: str) -> tuple[str, str | None] | None:
    """Resolve draft recipient to (email, contact_name)."""
    clean = (text or "").strip()
    emails = _EMAIL_ADDR.findall(clean)
    if emails:
        email = emails[0]
        name = None
        alias = extract_contact_name_from_text(clean)
        if alias and resolve_contact(alias) == email:
            name = alias
        return email, name

    alias = extract_contact_name_from_text(clean)
    if not alias:
        return None
    email = resolve_contact(alias)
    if not email:
        return None
    return email, alias


def parse_contact_remember_request(text: str) -> dict[str, str] | None:
    match = _REMEMBER_RE.search(text or "")
    if not match:
        return None
    groups = match.groupdict()
    name = groups.get("name1") or groups.get("name2") or groups.get("name3") or ""
    email = groups.get("email1") or groups.get("email2") or groups.get("email3") or ""
    name = _normalize_name(name)
    email = email.strip().rstrip(".,;")
    if not name or not _EMAIL_ADDR.fullmatch(email):
        return None
    return {"name": name, "email": email}


def record_draft_history(
    *,
    to: str,
    subject: str,
    about: str,
    body: str,
    draft_id: str = "",
    account: str = "",
    contact_name: str | None = None,
) -> dict:
    entry = {
        "to": to.strip(),
        "contact_name": _normalize_name(contact_name) if contact_name else "",
        "subject": subject.strip(),
        "about": about.strip(),
        "body_preview": (body or "").strip()[:240],
        "draft_id": draft_id.strip(),
        "account": account.strip(),
        "ts": _now_iso(),
    }
    rows = _load_history()
    rows.insert(0, entry)
    cutoff = datetime.now(timezone.utc) - timedelta(days=_HISTORY_LOOKBACK_DAYS)
    kept: list[dict] = []
    for row in rows:
        ts = _parse_iso(str(row.get("ts") or ""))
        if ts and ts < cutoff:
            continue
        kept.append(row)
    _save_history(kept[:_MAX_HISTORY])
    return entry


def history_for_recipient(to: str, *, limit: int = 5) -> list[dict]:
    target = (to or "").strip().lower()
    if not target:
        return []
    hits: list[dict] = []
    for row in _load_history():
        if str(row.get("to") or "").strip().lower() == target:
            hits.append(row)
        if len(hits) >= limit:
            break
    return hits


def find_similar_draft(*, to: str, about: str) -> dict | None:
    target = (to or "").strip().lower()
    if not target:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=_DUPLICATE_LOOKBACK_DAYS)
    for row in _load_history():
        if str(row.get("to") or "").strip().lower() != target:
            continue
        ts = _parse_iso(str(row.get("ts") or ""))
        if ts and ts < cutoff:
            continue
        prior_about = str(row.get("about") or row.get("subject") or "")
        if _about_similar(about, prior_about):
            return row
    return None


def format_duplicate_warning(entry: dict) -> str:
    when = str(entry.get("ts") or "")[:10] or "recently"
    subject = str(entry.get("subject") or entry.get("about") or "similar topic")
    contact = str(entry.get("contact_name") or entry.get("to") or "recipient")
    return (
        f"Note: you already drafted email to {contact} about this ({subject}) on {when}. "
        "I'll write a fresh version — mention if you want the earlier draft instead."
    )


def compose_history_context(*, to: str, about: str, limit: int = 3) -> str:
    rows = history_for_recipient(to, limit=limit)
    if not rows:
        return ""
    lines = ["Recent emails drafted to this recipient (avoid repeating the same message):"]
    for row in rows:
        when = str(row.get("ts") or "")[:10]
        subject = str(row.get("subject") or "")
        topic = str(row.get("about") or subject)
        preview = str(row.get("body_preview") or "").replace("\n", " ").strip()
        if len(preview) > 120:
            preview = preview[:117] + "..."
        lines.append(f"- {when}: about {topic!r}" + (f" — {preview}" if preview else ""))
    if _about_similar(about, str(rows[0].get("about") or "")):
        lines.append("The current topic looks similar to the most recent draft — vary wording or add new details.")
    return "\n".join(lines)


def wants_email_contacts(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if parse_contact_remember_request(clean):
        return True
    if _LIST_RE.search(clean) or _DELETE_RE.search(clean):
        return True
    return bool(_TRIGGER_RE.search(clean))


def route_command(text: str) -> str:
    if not wants_email_contacts(text):
        return ""
    clean = (text or "").strip()
    parsed = parse_contact_remember_request(clean)
    if parsed:
        return "email_contacts add {} {}".format(
            shlex.quote(parsed["name"]),
            shlex.quote(parsed["email"]),
        )
    delete_m = _DELETE_RE.search(clean)
    if delete_m:
        return f"email_contacts delete {shlex.quote(delete_m.group('name'))}"
    if _LIST_RE.search(clean) or _TRIGGER_RE.search(clean):
        return "email_contacts list"
    return ""


def try_autodetect_contact(text: str) -> str | None:
    """Store a named contact from NL; return confirmation or None."""
    parsed = parse_contact_remember_request(text)
    if not parsed:
        return None
    row = add_contact(parsed["name"], parsed["email"])
    label = row.get("display") or row.get("name")
    return f"Saved email contact {label} → {row.get('email')}"


def cmd_add(args: argparse.Namespace) -> int:
    try:
        row = add_contact(args.name, args.email, display=args.display or "", note=args.note or "")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    label = row.get("display") or row.get("name")
    print(f"✓ Saved {label} → {row.get('email')}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    rows = list_contacts(limit=int(args.limit or 50))
    if not rows:
        print("No email contacts yet.")
        print('Try: arka email_contacts add ceo ceo@company.com')
        print('Or: remember ceo email is ceo@company.com')
        return 0
    print(f"Email contacts ({len(rows)}):")
    for row in rows:
        name = row.get("name") or "?"
        email = row.get("email") or "?"
        display = row.get("display") or ""
        extra = f" ({display})" if display and display.lower() != str(name).lower() else ""
        print(f"  • {name}{extra} → {email}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    try:
        removed = delete_contact(args.name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Deleted contact {removed.get('name')} ({removed.get('email')})")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    if args.name:
        email = resolve_contact(args.name)
        if not email:
            print(f"No contact named {args.name!r}", file=sys.stderr)
            return 1
        rows = history_for_recipient(email, limit=int(args.limit or 10))
        label = args.name
    elif args.email:
        rows = history_for_recipient(args.email, limit=int(args.limit or 10))
        label = args.email
    else:
        rows = _load_history()[: int(args.limit or 10)]
        label = "all recipients"
    if not rows:
        print(f"No draft history for {label}.")
        return 0
    print(f"Draft history ({label}):")
    for row in rows:
        when = str(row.get("ts") or "")[:16].replace("T", " ")
        contact = row.get("contact_name") or row.get("to") or "?"
        subject = row.get("subject") or row.get("about") or "?"
        print(f"  • {when} → {contact}: {subject}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Named email contacts and draft history")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to email_contacts command")
    p_route.add_argument("text", nargs="+")

    p_add = sub.add_parser("add", help="Save a named email contact")
    p_add.add_argument("name")
    p_add.add_argument("email")
    p_add.add_argument("--display")
    p_add.add_argument("--note")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List saved email contacts")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_list)

    p_del = sub.add_parser("delete", help="Delete a named contact")
    p_del.add_argument("name")
    p_del.set_defaults(func=cmd_delete)

    p_hist = sub.add_parser("history", help="Show recent draft history")
    p_hist.add_argument("--name", help="Contact alias")
    p_hist.add_argument("--email", help="Recipient email")
    p_hist.add_argument("--limit", type=int, default=10)
    p_hist.set_defaults(func=cmd_history)

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
