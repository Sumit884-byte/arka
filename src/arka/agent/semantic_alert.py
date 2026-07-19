"""Source-grounded natural-language deadline alerts."""
from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka semantic-alert")
    p.add_argument("event", nargs="+")
    p.add_argument("--at", help="Verified ISO datetime, e.g. 2026-08-01T17:00:00")
    p.add_argument("--source", help="URL or citation containing the deadline")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    event = " ".join(args.event).strip()
    if not args.at:
        watching = any(term in event.lower() for term in ("whenever", "any new", "new program", "new hackathon"))
        message = "Provide a verified deadline with --at or a source URL with --source; Arka will not guess an event date."
        if watching:
            message = "This is a recurring program watch. Provide an official source/query and check interval; Arka will not invent programs or deadlines."
        result = {"status": "needs_watch_config" if watching else "needs_deadline", "event": event, "message": message}
        print(json.dumps(result, indent=2) if args.json else result["message"])
        return 2
    try:
        from arka.integrations.remind import _add_reminder, start_daemon
        reminder, _ = _add_reminder(f"{event} deadline", at=args.at)
        start_daemon()
    except (ImportError, OSError, SystemExit, ValueError) as exc:
        p.error(str(exc))
    result = {"status": "scheduled", "event": event, "source": args.source, "reminder": reminder}
    print(json.dumps(result, indent=2) if args.json else f"Alert scheduled for {event}: {args.at}")
    return 0
