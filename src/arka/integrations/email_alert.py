#!/usr/bin/env python3
"""Email alerts — cross-platform notifications for selections, credits, and deadlines."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from arka.env import env_get

try:
    from arka.paths import cache_dir, config_dir
except ImportError:
    config_dir = lambda: Path.home() / ".config" / "arka"  # noqa: E731
    cache_dir = lambda: Path.home() / ".cache" / "arka"  # noqa: E731

_CONFIG_NAME = "email_alerts.json"
_HISTORY_NAME = "email_alerts_history.json"

CATEGORIES = ("selection", "credits", "hackathon", "studies", "billing", "ci", "general")

_CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "selection",
        re.compile(
            r"(?i)\b(?:selected|accepted|admitted|shortlisted|chosen|enrolled|"
            r"offer\s+(?:letter|extended|received)|hired|you(?:'re|\s+are)\s+in|"
            r"got\s+into|cohort|program\s+acceptance)\b"
        ),
    ),
    (
        "credits",
        re.compile(
            r"(?i)\b(?:credits?\s+(?:given|awarded|added|granted|received)|"
            r"(?:free|bonus|promo)\s+credits?|tokens?\s+(?:given|awarded|added)|"
            r"balance\s+(?:updated|added|credited)|coupon\s+(?:applied|redeemed)|"
            r"reward(?:s)?\s+(?:awarded|earned|received))\b"
        ),
    ),
    (
        "hackathon",
        re.compile(
            r"(?i)\b(?:hackathon|devpost|hack\s+athon|submission\s+deadline|"
            r"demo\s+day|hacking\s+event)\b"
        ),
    ),
    (
        "studies",
        re.compile(
            r"(?i)\b(?:assignment|homework|exam|midterm|final|coursework|"
            r"study\s+deadline|application\s+deadline|scholarship|thesis|"
            r"paper\s+due|class\s+project|university|college|education|"
            r"enrollment|due\s+date|due\s+tomorrow)\b"
        ),
    ),
    (
        "billing",
        re.compile(
            r"(?i)\b(?:invoice|payment\s+failed|subscription\s+(?:expired|renewed|cancelled)|"
            r"billing\s+(?:issue|alert|failed)|card\s+(?:declined|expired)|"
            r"charge(?:d|s)?\s+(?:failed|declined))\b"
        ),
    ),
    (
        "ci",
        re.compile(
            r"(?i)\b(?:ci\s+(?:failed|failure|broken)|build\s+failed|deploy(?:ment)?\s+failed|"
            r"pipeline\s+failed|tests?\s+failed|check\s+run\s+failed|"
            r"github\s+actions?\s+failed)\b"
        ),
    ),
]

# Auto-alert rules — fired when auto mode is on (default) and text matches.
_AUTO_ALERT_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "selection",
        "Selection / acceptance",
        re.compile(
            r"(?i)\b(?:you(?:'re|\s+have\s+been|\s+are)?\s+(?:selected|accepted|admitted|"
            r"shortlisted|chosen|enrolled|hired)|(?:selected|accepted|admitted|shortlisted|"
            r"hired)\s+(?:for|into|by)|offer\s+(?:letter|extended|received)|"
            r"got\s+(?:into|accepted\s+to|hired)|(?:you\s+)?got\s+hired)\b"
        ),
    ),
    (
        "credits",
        "Credits / rewards",
        re.compile(
            r"(?i)\b(?:(?:\d+\s+)?credits?\s+(?:given|awarded|added|granted|received)|"
            r"(?:free|bonus|promo)\s+credits?|tokens?\s+(?:given|awarded|added)|"
            r"balance\s+(?:updated|added|credited)|coupon\s+(?:applied|redeemed)|"
            r"reward(?:s)?\s+(?:awarded|earned|received))\b"
        ),
    ),
    (
        "hackathon",
        "Hackathon / event",
        re.compile(
            r"(?i)\b(?:hackathon|devpost|hack\s+athon|submission\s+deadline|"
            r"demo\s+day|hacking\s+event)\b"
        ),
    ),
    (
        "studies",
        "Studies / deadline",
        re.compile(
            r"(?i)\b(?:assignment|homework|exam|midterm|final|coursework|"
            r"application\s+deadline|enrollment\s+deadline|due\s+date|due\s+tomorrow|"
            r"paper\s+due|class\s+project)\b"
        ),
    ),
    (
        "studies",
        "Deadline",
        re.compile(
            r"(?i)\b(?:deadline|expires(?:\s+on|\s+in)?|last\s+day|due\s+tomorrow|"
            r"closing\s+(?:date|soon))\b"
        ),
    ),
    (
        "billing",
        "Billing / payment",
        re.compile(
            r"(?i)\b(?:invoice|payment\s+failed|subscription\s+(?:expired|renewed|cancelled)|"
            r"billing\s+(?:issue|alert|failed)|card\s+(?:declined|expired))\b"
        ),
    ),
    (
        "ci",
        "CI / deploy failure",
        re.compile(
            r"(?i)\b(?:ci\s+(?:failed|failure|broken)|build\s+failed|deploy(?:ment)?\s+failed|"
            r"pipeline\s+failed|tests?\s+failed|check\s+run\s+failed|"
            r"github\s+actions?\s+failed)\b"
        ),
    ),
]

_AUTO_SKIP_QUESTION_RE = re.compile(
    r"^(?:what|who|where|when|why|how|which|can you|could you|would you|"
    r"do you|does|did|is|are|was|were|tell me about|explain)\b",
    re.I,
)
_AUTO_SKIP_COMMAND_RE = re.compile(
    r"^(?:alert|email\s+alert|notify|remind|schedule|send|test|list|status|config|"
    r"search|find|show|open|run|install|help)\b",
    re.I,
)
_AUTO_SKIP_HYPOTHETICAL_RE = re.compile(r"\b(?:if i|what if|suppose i|would i)\b", re.I)
_AUTO_DEDUPE_SEC = 3600

_KNOWN_CMDS = frozenset(
    {"send", "schedule", "list", "config", "test", "status", "parse", "route", "enable", "disable"}
)


def _config_path() -> Path:
    return config_dir() / _CONFIG_NAME


def _history_path() -> Path:
    return cache_dir() / _HISTORY_NAME


def _load_json(path: Path, default: Any) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def default_config() -> dict[str, Any]:
    return {
        "to": env_get("ALERT_EMAIL_TO") or env_get("EMAIL_ALERT_TO"),
        "auto": True,
        "categories": {name: True for name in CATEGORIES},
        "channels": ["email", "os"],
    }


def load_config() -> dict[str, Any]:
    stored = _load_json(_config_path(), {})
    cfg = default_config()
    if isinstance(stored, dict):
        if stored.get("to"):
            cfg["to"] = str(stored["to"]).strip()
        cats = stored.get("categories")
        if isinstance(cats, dict):
            for name in CATEGORIES:
                if name in cats:
                    cfg["categories"][name] = bool(cats[name])
        channels = stored.get("channels")
        if isinstance(channels, list) and channels:
            cfg["channels"] = [str(c).strip().lower() for c in channels if str(c).strip()]
        if "auto" in stored:
            cfg["auto"] = bool(stored["auto"])
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    _save_json(_config_path(), cfg)


def alert_to_email(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or load_config()
    return str(cfg.get("to") or env_get("ALERT_EMAIL_TO") or env_get("EMAIL_ALERT_TO") or "").strip()


def alerts_enabled() -> bool:
    if env_get("ALERT_EMAIL_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool(alert_to_email())


def auto_alert_enabled(cfg: dict[str, Any] | None = None) -> bool:
    """Return True when background auto-alerts are enabled (default on)."""
    raw = env_get("ALERT_AUTO", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    cfg = cfg or load_config()
    return bool(cfg.get("auto", True))


def set_auto_alert(enabled: bool) -> None:
    cfg = load_config()
    cfg["auto"] = bool(enabled)
    save_config(cfg)


def _auto_alert_skip_reason(text: str) -> str | None:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or len(t) < 8:
        return "too_short"
    if _AUTO_SKIP_HYPOTHETICAL_RE.search(t):
        return "hypothetical"
    if t.endswith("?"):
        return "question"
    if _AUTO_SKIP_QUESTION_RE.search(t) and not re.search(
        r"(?i)\b(?:i\s+(?:was|am|got|have\s+been)|my\s+(?:invoice|subscription|payment))\b",
        t,
    ):
        return "question"
    if _AUTO_SKIP_COMMAND_RE.search(t):
        return "command"
    if re.search(r"(?i)\b(?:email\s+alert|alert\s+email|notify\s+me\s+by\s+email)\b", t):
        return "explicit_alert"
    return None


def detect_auto_alert(text: str) -> dict[str, str] | None:
    """Return auto-alert match metadata or None."""
    if _auto_alert_skip_reason(text):
        return None
    t = re.sub(r"\s+", " ", text.strip())
    for category, label, pattern in _AUTO_ALERT_RULES:
        if pattern.search(t):
            title = label
            body = t[:500]
            return {"category": category, "title": title, "body": body, "rule": label}
    return None


def _recent_auto_duplicate(text: str) -> bool:
    norm = re.sub(r"\s+", " ", text.strip().lower())
    if not norm:
        return True
    now = int(time.time())
    for row in list_history(limit=30):
        if row.get("source") != "auto":
            continue
        if now - int(row.get("created_at") or 0) > _AUTO_DEDUPE_SEC:
            continue
        prior = re.sub(r"\s+", " ", str(row.get("body") or row.get("title") or "").strip().lower())
        if not prior:
            continue
        if norm == prior or norm in prior or prior in norm:
            return True
    return False


def maybe_auto_alert(
    text: str,
    *,
    source: str | None = "auto",
    quiet: bool = True,
) -> dict[str, Any] | None:
    """Pattern-match common events and send alerts when auto mode is on."""
    if not auto_alert_enabled():
        return None
    match = detect_auto_alert(text)
    if not match:
        return None
    if _recent_auto_duplicate(match["body"]):
        return None
    row = send_alert(
        match["title"],
        match["body"],
        category=match["category"],
        source=source or "auto",
    )
    if not quiet and not row.get("skipped"):
        channels = ", ".join(row.get("channels") or ["none"])
        print(f"✓ Auto-alert ({channels}) — {match['category']}: {match['body'][:80]}", flush=True)
    return row


def classify_event(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "general"
    for name, pattern in _CATEGORY_PATTERNS:
        if pattern.search(t):
            return name
    if re.search(r"(?i)\b(?:deadline|expires|last\s+day|due\s+tomorrow)\b", t):
        return "studies"
    return "general"


def is_category_enabled(category: str | None, cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_config()
    cat = (category or "general").strip().lower()
    cats = cfg.get("categories") if isinstance(cfg.get("categories"), dict) else {}
    return bool(cats.get(cat, cats.get("general", True)))


def _append_history(row: dict[str, Any]) -> None:
    items = _load_json(_history_path(), [])
    if not isinstance(items, list):
        items = []
    items.append(row)
    items = items[-200:]
    _save_json(_history_path(), items)


def _local_notify(title: str, body: str) -> None:
    try:
        from arka.integrations.remind import _notify

        _notify(title, body)
    except ImportError:
        print(f"\n⏰ {title}: {body}", flush=True)


def _format_subject(category: str | None, title: str) -> str:
    label = (category or "general").strip().capitalize()
    prefix = f"[Arka {label}]"
    title = (title or "Alert").strip()
    if title.lower().startswith("[arka"):
        return title
    return f"{prefix} {title}"


def send_alert(
    title: str,
    body: str,
    *,
    category: str | None = None,
    source: str | None = None,
    also_os: bool | None = None,
) -> dict[str, Any]:
    """Send an immediate alert via configured channels."""
    cfg = load_config()
    cat = (category or classify_event(f"{title} {body}")).strip().lower()
    if not is_category_enabled(cat, cfg):
        return {
            "ok": False,
            "skipped": True,
            "reason": f"category {cat!r} is disabled",
            "category": cat,
        }

    message = (body or title or "").strip()
    subject = _format_subject(cat, title or message[:80])
    if source:
        message = f"{message}\n\nSource: {source}".strip()

    row: dict[str, Any] = {
        "id": uuid.uuid4().hex[:8],
        "kind": "immediate",
        "category": cat,
        "title": title,
        "body": message,
        "source": source,
        "created_at": int(time.time()),
        "channels": [],
    }

    channels = cfg.get("channels") if isinstance(cfg.get("channels"), list) else ["email", "os"]
    use_os = also_os if also_os is not None else "os" in channels

    email_result: dict[str, Any] | None = None
    email_error: str | None = None
    if "email" in channels and alerts_enabled():
        to = alert_to_email(cfg)
        if not to:
            email_error = "ALERT_EMAIL_TO not set"
        else:
            try:
                from arka.integrations.email_send import send_email

                email_result = send_email(to, subject, message)
                row["channels"].append("email")
                row["email"] = {"to": to, **email_result}
            except Exception as exc:
                email_error = str(exc)

    if use_os:
        _local_notify(subject, message)
        row["channels"].append("os")

    row["ok"] = bool(email_result) or (use_os and not alerts_enabled()) or (
        use_os and email_error is not None
    )
    if email_error:
        row["email_error"] = email_error
    if not row["ok"] and email_error and not use_os:
        raise RuntimeError(email_error)

    _append_history(row)
    return row


def deliver_scheduled_reminder(rem: dict[str, Any], *, kind: str) -> dict[str, Any] | None:
    """Email hook for remind._fire when reminder has email=True."""
    if not rem.get("email"):
        return None
    text = str(rem.get("text") or "Reminder")
    category = str(rem.get("category") or classify_event(text))
    title = "Reminder" if kind == "at_time" else "Reminder (you're back)"
    return send_alert(title, text, category=category, also_os=False)


def schedule_alert(
    text: str,
    *,
    at: str | None = None,
    in_spec: str | None = None,
    category: str | None = None,
    start: bool = True,
) -> tuple[dict[str, Any] | None, str | None]:
    """Schedule a deadline alert (email + OS via remind daemon)."""
    message = (text or "").strip()
    if not message and not at and not in_spec:
        return None, "text is required (or provide --at / --in)"
    cat = (category or classify_event(message)).strip().lower()
    if not is_category_enabled(cat):
        return None, f"category {cat!r} is disabled in email alert config"

    try:
        from arka.core.security import verify_user_prompt

        gate = verify_user_prompt(message or "email alert")
        if gate.status == "block":
            return None, gate.reason
    except ImportError:
        pass

    try:
        from arka.integrations.remind import _add_reminder, _reminder_row, start_daemon
    except ImportError as exc:
        return None, f"remind unavailable: {exc}"

    rem, used_default = _add_reminder(message, at=at, in_spec=in_spec, email=True, category=cat)
    if start:
        try:
            start_daemon()
        except Exception:
            pass
    row = _reminder_row(rem)
    row["used_default_delay"] = used_default
    row["email"] = True
    row["category"] = cat
    return row, None


def list_history(*, limit: int = 20) -> list[dict[str, Any]]:
    items = _load_json(_history_path(), [])
    if not isinstance(items, list):
        return []
    return list(reversed(items[-max(1, min(limit, 200)) :]))


def status_payload() -> dict[str, Any]:
    from arka.integrations.email_send import configured_providers, default_from_address

    cfg = load_config()
    cats = cfg.get("categories") if isinstance(cfg.get("categories"), dict) else {}
    active_categories = [name for name in CATEGORIES if cats.get(name, name == "general")]
    return {
        "enabled": alerts_enabled(),
        "auto": auto_alert_enabled(cfg),
        "to": alert_to_email(cfg) or None,
        "from": default_from_address(),
        "providers": configured_providers(),
        "config_path": str(_config_path()),
        "categories": cats,
        "active_categories": active_categories,
        "channels": cfg.get("channels"),
    }


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    low = t.lower()
    if re.search(r"(?i)\b(?:list|show)\s+(?:my\s+)?(?:email\s+)?alerts?\b", low):
        return ["list"]
    if re.search(r"(?i)\b(?:test|ping)\s+(?:email\s+)?alert\b", low) or low in {
        "alert test",
        "test alert email",
    }:
        return ["test"]
    if re.search(r"(?i)\b(?:alert|email)\s+status\b", low):
        return ["status"]
    sched = re.search(
        r"(?i)\b(?:email\s+alert|alert\s+by\s+email|notify\s+me\s+by\s+email)\s+(?:me\s+)?(?:when|at|on)\s+(.+)$",
        t,
    )
    if sched:
        return ["schedule", sched.group(1).strip()]
    if re.search(r"(?i)\b(?:alert|notify|remind)\s+me\s+when\b", t):
        return []
    if detect_auto_alert(t):
        return ["send", t]
    if re.search(
        r"(?i)\b(?:selected|accepted|admitted|credits?\s+(?:given|awarded)|hackathon)\b",
        t,
    ):
        return ["send", t]
    if re.search(r"(?i)\bdeadline\b", t) and not re.search(r"(?i)\b(?:when|whenever)\b", t):
        return ["send", t]
    if re.search(r"(?i)\b(?:email\s+alert|alert\s+email|notify\s+me\s+by\s+email)\b", low):
        cleaned = re.sub(
            r"(?i)\b(?:email\s+alert|alert\s+email|notify\s+me\s+by\s+email)\s*",
            "",
            t,
        ).strip()
        if cleaned:
            return ["send", cleaned]
    return []


def route_command(text: str) -> str | None:
    argv = nl_to_argv(text.strip())
    if not argv:
        return None
    return "alert " + " ".join(shlex.quote(a) for a in argv)


def _cmd_send(args: argparse.Namespace) -> int:
    text = " ".join(args.message).strip()
    title = (args.title or "").strip() or text[:120] or "Arka alert"
    body = (args.body or "").strip() or text
    category = (args.category or "").strip().lower() or None
    row = send_alert(title, body, category=category, source=args.source)
    if row.get("skipped"):
        print(f"Skipped: {row.get('reason')}", file=sys.stderr)
        return 2
    if row.get("email_error") and "email" not in row.get("channels", []):
        print(f"Email failed: {row['email_error']}", file=sys.stderr)
        return 1
    channels = ", ".join(row.get("channels") or ["none"])
    print(f"✓ Alert sent ({channels}) — id {row.get('id')} [{row.get('category')}]")
    if row.get("email_error"):
        print(f"  Email note: {row['email_error']}", file=sys.stderr)
    return 0


def _cmd_schedule(args: argparse.Namespace) -> int:
    text = " ".join(args.message).strip()
    row, err = schedule_alert(
        text,
        at=args.at,
        in_spec=args.in_spec,
        category=(args.category or "").strip().lower() or None,
        start=not args.no_start,
    )
    if err or row is None:
        raise SystemExit(err or "failed to schedule alert")
    print(
        f"✓ Email alert scheduled for {row.get('due') or '?'} — "
        f"{row.get('text')} (id {row.get('id')}, category {row.get('category')})"
    )
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    rows = list_history(limit=int(args.limit or 20))
    if not rows:
        print("No email alerts sent yet.")
        return 0
    print(f"Recent email alerts ({len(rows)}):")
    for row in rows:
        when = datetime.fromtimestamp(int(row.get("created_at") or 0)).strftime("%Y-%m-%d %H:%M")
        channels = ",".join(row.get("channels") or [])
        print(f"  • {when} [{row.get('category')}] {row.get('title') or row.get('body', '')[:60]} ({channels})")
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.to:
        cfg["to"] = args.to.strip()
        save_config(cfg)
        print(f"✓ Alert email set to {cfg['to']}")
        return 0
    if args.auto is not None:
        enabled = str(args.auto).strip().lower() not in {"0", "false", "no", "off"}
        set_auto_alert(enabled)
        state = "ON" if enabled else "OFF"
        print(f"✓ Auto-alerts {state}")
        return 0
    if args.set_category:
        name, _, val = args.set_category.partition("=")
        name = name.strip().lower()
        if name not in CATEGORIES:
            raise SystemExit(f"Unknown category {name!r}; choose from: {', '.join(CATEGORIES)}")
        cats = cfg.setdefault("categories", {})
        cats[name] = val.strip().lower() not in {"0", "false", "no", "off"}
        save_config(cfg)
        state = "enabled" if cats[name] else "disabled"
        print(f"✓ Category {name} {state}")
        return 0
    print(json.dumps(status_payload(), indent=2))
    return 0


def _cmd_test(_args: argparse.Namespace) -> int:
    row = send_alert(
        "Test alert",
        "Arka email alerts are working. You will receive cross-platform notifications "
        "for selections, credits, hackathons, and study deadlines.",
        category="general",
    )
    if row.get("email_error"):
        print(f"OS notification sent; email failed: {row['email_error']}", file=sys.stderr)
        return 1
    print(f"✓ Test alert sent — id {row.get('id')}")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    payload = status_payload()
    print(json.dumps(payload, indent=2))
    auto_state = "ON" if payload.get("auto") else "OFF"
    active = payload.get("active_categories") or []
    print(f"\nAuto-alerts: {auto_state}")
    if active:
        print(f"Active categories: {', '.join(active)}")
    if not payload.get("enabled"):
        print("\nSet ALERT_EMAIL_TO in ~/.config/arka/.env and configure a provider.", file=sys.stderr)
    elif not payload.get("providers"):
        print("\nConfigure RESEND_API_KEY, SENDGRID_API_KEY, or SMTP_HOST.", file=sys.stderr)
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def _cmd_route(args: argparse.Namespace) -> int:
    route = route_command(" ".join(args.text))
    if not route:
        return 1
    print(route)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] not in _KNOWN_CMDS and argv[0] not in ("-h", "--help"):
        return _cmd_send(argparse.Namespace(message=argv, title="", body="", category="", source=None))

    parser = argparse.ArgumentParser(
        description="Email alerts for selections, credits, hackathons, and study deadlines.",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_send = sub.add_parser("send", help="Send an immediate email alert")
    p_send.add_argument("message", nargs="+", help="Alert message")
    p_send.add_argument("--title", help="Email subject title")
    p_send.add_argument("--body", help="Email body (defaults to message)")
    p_send.add_argument("--category", choices=CATEGORIES, help="Alert category")
    p_send.add_argument("--source", help="Optional source URL or citation")
    p_send.set_defaults(func=_cmd_send)

    p_sched = sub.add_parser("schedule", help="Schedule a deadline alert (email at due time)")
    p_sched.add_argument("message", nargs="+", help="What to remind you about")
    p_sched.add_argument("--at", dest="at", help="ISO datetime or unix timestamp")
    p_sched.add_argument("--in", dest="in_spec", help="Relative delay: 30m, 2h, 1d")
    p_sched.add_argument("--category", choices=CATEGORIES, help="Alert category")
    p_sched.add_argument("--no-start", action="store_true", help="Do not start remind daemon")
    p_sched.set_defaults(func=_cmd_schedule)

    p_list = sub.add_parser("list", help="List recent sent alerts")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=_cmd_list)

    p_cfg = sub.add_parser("config", help="Show or update alert settings")
    p_cfg.add_argument("--to", help="Set alert recipient email")
    p_cfg.add_argument("--auto", choices=["on", "off"], help="Enable/disable auto-alerts")
    p_cfg.add_argument("--set-category", metavar="NAME=on|off", help="Enable/disable a category")
    p_cfg.set_defaults(func=_cmd_config, auto=None)

    sub.add_parser("test", help="Send a test alert").set_defaults(func=_cmd_test)
    sub.add_parser("status", help="Show alert configuration status").set_defaults(func=_cmd_status)

    p_parse = sub.add_parser("parse", help="Parse natural language → alert args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=_cmd_parse)

    p_route = sub.add_parser("route", help="Map NL to alert command")
    p_route.add_argument("text", nargs="+")
    p_route.set_defaults(func=_cmd_route)

    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
