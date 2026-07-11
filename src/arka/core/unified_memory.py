#!/usr/bin/env python3
"""Unified memory facade — orchestrates facts, session notes, and channel turns."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from arka.core.memory_scope import RecallScope

try:
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass

Layer = Literal["auto", "fact", "note", "channel"]

NOTE_PREFIX_RE = re.compile(r"^(?:note|journal|log|daily)\s*:\s*", re.I)
NOTE_TOPIC_RE = re.compile(
    r"\b(meeting|standup|retro|journal|diary|today i|this morning|"
    r"action items?|follow[- ]?up|brainstorm)\b",
    re.I,
)
FACT_PREFIX_RE = re.compile(
    r"^(?:remember|memorize|store|don't forget|dont forget|keep in mind)\s+(?:that\s+)?",
    re.I,
)
FACT_PREFERENCE_RE = re.compile(
    r"\b(i prefer|i like|i hate|i always|i never|my name is|i am|i live in|"
    r"my favorite|default to|always use)\b",
    re.I,
)
CHANNEL_PREFIX_RE = re.compile(r"^(?:user|assistant|system)\s*:\s*", re.I)


def _enabled() -> bool:
    return os.environ.get("UNIFIED_MEMORY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _sanitize_text(text: str) -> tuple[str, str | None]:
    text = " ".join((text or "").split()).strip()
    if not text:
        return "", "empty"
    try:
        from arka.core.security import sanitize_llm_context, verify_user_prompt

        gate = verify_user_prompt(text)
        if gate.status == "block":
            return "", gate.reason
        cleaned, _ = sanitize_llm_context(text)
        return (cleaned or text).strip(), None
    except ImportError:
        return text, None


def _infer_layer(text: str) -> Layer:
    if CHANNEL_PREFIX_RE.match(text):
        return "channel"
    if NOTE_PREFIX_RE.match(text) or NOTE_TOPIC_RE.search(text):
        return "note"
    if FACT_PREFIX_RE.match(text) or FACT_PREFERENCE_RE.search(text):
        return "fact"
    if len(text) > 140:
        return "note"
    return "fact"


def _resolve_channel(channel: str, chat_id: str) -> tuple[str, str]:
    ch = (channel or "").strip()
    cid = (chat_id or "").strip()
    if ch and cid:
        return ch, cid
    try:
        from arka.integrations.message_sessions import cli_channel, cli_chat_id

        return ch or cli_channel(), cid or cli_chat_id()
    except ImportError:
        return ch or "cli", cid or "default"


def remember(
    text: str,
    *,
    layer: Layer = "auto",
    long_term: bool = False,
    channel: str = "",
    chat_id: str = "",
) -> tuple[int, str | None]:
    """Write to the appropriate memory layer(s). Returns (exit_code, error)."""
    cleaned, err = _sanitize_text(text)
    if err:
        return 1, err
    if not cleaned:
        return 1, "empty"

    target = _infer_layer(cleaned) if layer == "auto" else layer

    if target == "channel":
        ch, cid = _resolve_channel(channel, chat_id)
        role = "user"
        body = cleaned
        m = CHANNEL_PREFIX_RE.match(cleaned)
        if m:
            head, _, rest = cleaned.partition(":")
            role = head.strip().lower()
            body = rest.strip()
            if role not in {"user", "assistant", "system"}:
                role = "user"
                body = cleaned
        try:
            from arka.integrations.message_sessions import push

            code, push_err = push(ch, cid, role, body)
            if push_err:
                return code, push_err
            print(f"Stored channel turn ({ch}:{cid}, {role}): {body[:120]}")
            return 0, None
        except ImportError:
            return 1, "message_sessions unavailable"

    if target == "note":
        note_text = NOTE_PREFIX_RE.sub("", cleaned).strip() or cleaned
        try:
            from arka.core.session_memory import append

            return append(note_text, long_term=long_term), None
        except ImportError:
            return 1, "session_memory unavailable"

    fact_text = FACT_PREFIX_RE.sub("", cleaned).strip() or cleaned
    try:
        from arka.agent.core import memory_remember

        memory_remember(fact_text)
        return 0, None
    except ImportError:
        pass
    try:
        from arka.integrations.supermemory import remember_print

        remember_print(fact_text)
        return 0, None
    except ImportError:
        return 1, "fact memory unavailable"


def _recall_facts(
    goal: str,
    *,
    limit_chars: int,
    scope: RecallScope | None = None,
) -> str:
    try:
        from arka.integrations.supermemory import context_for

        ctx = context_for(goal, limit_chars=limit_chars)
        if ctx and ctx.strip() and scope is None:
            return ctx.strip()
    except ImportError:
        pass
    except Exception:
        pass

    memory_file = cache_dir() / "memory.json"
    try:
        raw = json.loads(memory_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = []
    if not isinstance(raw, list) or not raw:
        return ""

    rows = raw
    if scope is not None:
        from arka.core.memory_scope import filter_fact_rows

        rows = filter_fact_rows(raw, scope=scope)

    q = goal.lower()
    scored: list[tuple[float, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "")
        score = sum(1 for w in q.split() if len(w) > 2 and w in text.lower())
        if score:
            scored.append((score, text))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return ""
    lines = [f"- {t}" for _, t in scored[:5]]
    out = "Relevant facts:\n" + "\n".join(lines)
    if len(out) > limit_chars:
        out = out[-limit_chars:]
    return out


def _recall_notes(goal: str, *, limit_chars: int) -> str:
    try:
        from arka.core.session_memory import context_for

        return context_for(goal, limit_chars=limit_chars)
    except ImportError:
        return ""


def _recall_channel(channel: str, chat_id: str, *, limit_chars: int) -> str:
    try:
        from arka.integrations.message_sessions import _enabled, context_for

        if not _enabled():
            return ""
        ch, cid = _resolve_channel(channel, chat_id)
        ctx = context_for(ch, cid, limit_chars=limit_chars)
        if ctx:
            return f"Channel session ({ch}:{cid}):\n{ctx}"
    except ImportError:
        pass
    return ""


def recall(
    goal: str,
    *,
    limit_chars: int = 3500,
    channel: str = "",
    chat_id: str = "",
    include_channel: bool = True,
    scope: RecallScope | None = None,
) -> str:
    """Aggregate context from all enabled memory layers."""
    goal = (goal or "").strip()
    if not goal:
        return ""

    if scope is not None:
        include_channel = scope.policy.include_channel

    per_layer = max(800, limit_chars // 4 if scope else limit_chars // 3)
    sections: list[str] = []

    facts = _recall_facts(goal, limit_chars=per_layer, scope=scope)
    if facts:
        sections.append(facts)

    notes = _recall_notes(goal, limit_chars=per_layer)
    if notes:
        sections.append(notes)

    if include_channel:
        channel_ctx = _recall_channel(channel, chat_id, limit_chars=per_layer)
        if channel_ctx:
            sections.append(channel_ctx)

    if scope is not None:
        from arka.core.memory_scope import recall_scratchpad

        scratch = recall_scratchpad(goal, scope=scope, limit_chars=per_layer)
        if scratch:
            sections.append(scratch)

    out = "\n\n".join(sections).strip()
    if len(out) > limit_chars:
        out = out[-limit_chars:]
    return out


def _facts_status() -> dict[str, object]:
    memory_file = cache_dir() / "memory.json"
    count = 0
    try:
        raw = json.loads(memory_file.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            count = len(raw)
    except (OSError, json.JSONDecodeError):
        pass
    backend = (os.environ.get("MEMORY") or "auto").strip().lower()
    has_key = bool((os.environ.get("SUPERMEMORY_API_KEY") or "").strip())
    return {"local_count": count, "backend": backend, "api_configured": has_key}


def status(*, channel: str = "", chat_id: str = "") -> dict[str, object]:
    info: dict[str, object] = {
        "unified_memory": _enabled(),
        "facts": _facts_status(),
    }
    try:
        from arka.core.memory_scope import scope_status

        info["scope"] = scope_status()
    except ImportError:
        pass
    try:
        from arka.core.session_memory import status as notes_status

        info["notes"] = notes_status()
    except ImportError:
        info["notes"] = {"enabled": False}
    try:
        from arka.integrations.message_sessions import status as channel_status

        ch, cid = _resolve_channel(channel, chat_id)
        info["channel"] = channel_status(ch, cid)
    except ImportError:
        info["channel"] = {"enabled": False}
    return info


def print_status(*, channel: str = "", chat_id: str = "") -> None:
    info = status(channel=channel, chat_id=chat_id)
    print(f"Unified memory: {'on' if info.get('unified_memory') else 'off'}")
    facts = info.get("facts")
    if isinstance(facts, dict):
        print(
            f"  Facts: {facts.get('local_count', 0)} local"
            f" (backend={facts.get('backend', 'auto')},"
            f" api={'yes' if facts.get('api_configured') else 'no'})"
        )
    notes = info.get("notes")
    if isinstance(notes, dict):
        print(
            f"  Session notes: {'on' if notes.get('enabled') else 'off'}"
            f" — {notes.get('daily_files', 0)} daily files,"
            f" {notes.get('long_term_lines', 0)} MEMORY.md lines"
        )
    channel_info = info.get("channel")
    if isinstance(channel_info, dict):
        print(
            f"  Channel sessions: {'on' if channel_info.get('enabled') else 'off'}"
            f" — {channel_info.get('sessions', 0)} stored"
        )
        sess = channel_info.get("session")
        if isinstance(sess, dict) and sess.get("key"):
            print(f"    Active: {sess.get('key')} ({sess.get('turns', 0)} turns)")
    scope_info = info.get("scope")
    if isinstance(scope_info, dict):
        print(
            f"  Scoped memory: trust_max={scope_info.get('trust_max')}"
            f", scratchpad={scope_info.get('scratchpad_count', 0)} entries"
        )


def _cmd_scratchpad_list(args: argparse.Namespace) -> int:
    from arka.core.memory_scope import list_scratchpad

    rows = list_scratchpad(team=args.team or "", workflow=args.workflow or "", limit=args.limit)
    if not rows:
        print("(no scratchpad entries)")
        return 0
    for row in rows:
        prov = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        print(
            f"{row.get('id')}\t{prov.get('team', '')}\t{prov.get('workflow', '')}\t"
            f"{prov.get('role', '')}\t{str(row.get('text', ''))[:80]}"
        )
    return 0


def _cmd_scratchpad_show(args: argparse.Namespace) -> int:
    from arka.core.memory_scope import get_scratchpad

    row = get_scratchpad(args.id)
    if not row:
        print(f"Not found: {args.id}", file=sys.stderr)
        return 1
    print(json.dumps(row, indent=2))
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    from arka.core.memory_scope import promote_to_facts

    ok, err = promote_to_facts(args.id)
    if not ok:
        print(f"Promote failed: {err}", file=sys.stderr)
        return 1
    print(f"Promoted {args.id} to global facts")
    return 0


def _cmd_scope_status(_args: argparse.Namespace) -> int:
    from arka.core.memory_scope import print_scope_status

    print_scope_status()
    return 0


def run_cli(argv: list[str]) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Unified memory facade for Arka")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("remember", help="Store text in the appropriate layer")
    p.add_argument("text")
    p.add_argument("--layer", choices=["auto", "fact", "note", "channel"], default="auto")
    p.add_argument("--long-term", action="store_true")
    p.add_argument("--channel", default="")
    p.add_argument("--chat-id", default="")

    p = sub.add_parser("recall", help="Aggregate context from all memory layers")
    p.add_argument("goal")
    p.add_argument("--limit-chars", type=int, default=3500)
    p.add_argument("--channel", default="")
    p.add_argument("--chat-id", default="")

    p = sub.add_parser("status")
    p.add_argument("--channel", default="")
    p.add_argument("--chat-id", default="")

    scope = sub.add_parser("scope", help="Scoped memory commands")
    scope_sub = scope.add_subparsers(dest="scope_cmd")
    scope_sub.add_parser("status", help="Show trust cap and scratchpad stats")

    sp = scope_sub.add_parser("scratchpad", help="Scratchpad commands")
    sp_sub = sp.add_subparsers(dest="scratchpad_cmd")
    sp_list = sp_sub.add_parser("list", help="List scratchpad entries")
    sp_list.add_argument("--team", default="")
    sp_list.add_argument("--workflow", default="")
    sp_list.add_argument("--limit", type=int, default=50)
    sp_show = sp_sub.add_parser("show", help="Show scratchpad entry")
    sp_show.add_argument("id")

    promote_p = scope_sub.add_parser("promote", help="Promote scratchpad entry to global facts")
    promote_p.add_argument("id")

    args = parser.parse_args(argv)
    if args.cmd == "remember":
        code, err = remember(
            args.text,
            layer=args.layer,
            long_term=args.long_term,
            channel=args.channel,
            chat_id=args.chat_id,
        )
        if err:
            print(f"Remember blocked: {err}", file=sys.stderr)
        return code
    if args.cmd == "recall":
        ctx = recall(
            args.goal,
            limit_chars=args.limit_chars,
            channel=args.channel,
            chat_id=args.chat_id,
        )
        print(ctx or "(no unified memory context)")
        return 0
    if args.cmd == "status":
        print_status(channel=args.channel, chat_id=args.chat_id)
        return 0
    if args.cmd == "scope":
        if args.scope_cmd == "status":
            return _cmd_scope_status(args)
        if args.scope_cmd == "promote":
            return _cmd_promote(args)
        if args.scope_cmd == "scratchpad":
            if args.scratchpad_cmd == "list":
                return _cmd_scratchpad_list(args)
            if args.scratchpad_cmd == "show":
                return _cmd_scratchpad_show(args)
        print("Usage: scope status|promote <id>|scratchpad list|show <id>", file=sys.stderr)
        return 1
    return 1


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    return run_cli(raw)


if __name__ == "__main__":
    raise SystemExit(main())
