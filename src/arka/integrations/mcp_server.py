"""Arka as a local stdio MCP server — expose skills and memory to other agents."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from arka import __version__
from arka.integrations.mcp_client import MCP_PROTOCOL_VERSION

SERVER_NAME = "arka"
ARKA_MCP_SERVER_KEY = "arka"

ToolHandler = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ArkaMcpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
    }
    if is_error:
        payload["isError"] = True
    return payload


def _handle_arka_ask(arguments: dict[str, Any]) -> str:
    prompt = str(arguments.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    deep = bool(arguments.get("deep", False))
    try:
        from arka.agent.chat import answer_question

        provenance, answer = answer_question(
            prompt,
            deep=deep,
            use_session=True,
            cleanup=True,
        )
        return f"[{provenance}]\n{answer}".strip()
    except ImportError as exc:
        raise RuntimeError(f"chat module unavailable: {exc}") from exc


def _handle_arka_remember(arguments: dict[str, Any]) -> str:
    text = str(arguments.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    layer = str(arguments.get("layer") or "auto").strip().lower()
    if layer not in {"auto", "fact", "note", "channel"}:
        raise ValueError("layer must be auto, fact, note, or channel")
    try:
        from arka.core.unified_memory import remember

        with contextlib.redirect_stdout(io.StringIO()):
            code, err = remember(
                text,
                layer=layer,  # type: ignore[arg-type]
                long_term=bool(arguments.get("long_term", False)),
            )
        if code != 0:
            raise RuntimeError(err or "remember failed")
        return f"Remembered ({layer}): {text[:200]}"
    except ImportError as exc:
        raise RuntimeError(f"unified_memory unavailable: {exc}") from exc


def _handle_arka_recall(arguments: dict[str, Any]) -> str:
    goal = str(arguments.get("goal") or arguments.get("query") or "").strip()
    if not goal:
        raise ValueError("goal is required")
    limit_chars = int(arguments.get("limit_chars") or 3500)
    try:
        from arka.core.unified_memory import recall

        text = recall(goal, limit_chars=max(200, limit_chars))
        return text or "(no matching memory)"
    except ImportError as exc:
        raise RuntimeError(f"unified_memory unavailable: {exc}") from exc


def _handle_arka_skill(arguments: dict[str, Any]) -> str:
    skill = str(arguments.get("skill") or arguments.get("name") or "").strip()
    if not skill:
        raise ValueError("skill is required")
    args = arguments.get("args") or []
    if isinstance(args, str):
        extra = args.split()
    elif isinstance(args, list):
        extra = [str(a) for a in args]
    else:
        raise ValueError("args must be a string or list")
    skill_line = " ".join([skill, *extra]).strip()
    try:
        from arka.dispatch import run_skill

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = run_skill(skill_line)
        output = buf.getvalue().strip()
        if code != 0 and not output:
            raise RuntimeError(f"skill exited {code}")
        if output:
            return output
        return f"Skill {skill!r} completed (exit {code})"
    except ImportError as exc:
        raise RuntimeError(f"dispatch unavailable: {exc}") from exc


def _handle_arka_repo_map(arguments: dict[str, Any]) -> str:
    depth = int(arguments.get("depth") or 2)
    include_symbols = bool(arguments.get("symbols", True))
    path_arg = str(arguments.get("path") or "").strip()
    try:
        from arka.agent.pr_check import git_root
        from arka.agent.repo_map import map_text

        root = Path(path_arg).expanduser().resolve() if path_arg else git_root()
        if root is None or not root.is_dir():
            root = Path.cwd()
        return map_text(
            root,
            depth=max(1, min(depth, 5)),
            include_symbols=include_symbols,
        )
    except ImportError as exc:
        raise RuntimeError(f"repo_map unavailable: {exc}") from exc


def _handle_arka_heartbeat(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    activity = str(arguments.get("activity") or "mcp.ping").strip()
    try:
        from arka.integrations.heartbeat import history, ping, status

        if action == "ping":
            ping(activity, source="mcp")
            return f"Heartbeat ping: {activity}"
        if action == "history":
            limit = int(arguments.get("limit") or 20)
            return json.dumps(history(limit=max(1, min(limit, 100))), indent=2)
        if action == "status":
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                status(json_out=bool(arguments.get("json")))
            return buf.getvalue().strip() or "Heartbeat status unavailable"
        raise ValueError("action must be ping, status, or history")
    except ImportError as exc:
        raise RuntimeError(f"heartbeat unavailable: {exc}") from exc


def _handle_arka_sessions(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    channel = str(arguments.get("channel") or "").strip() or None
    chat_id = str(arguments.get("chat_id") or "").strip() or None
    try:
        from arka.integrations.message_sessions import (
            context_for,
            list_sessions,
            push,
            reset,
            resume_payload,
            silence_check,
            status,
        )

        if action == "list":
            limit = int(arguments.get("limit") or 20)
            return json.dumps(list_sessions(limit=max(1, min(limit, 200))), indent=2)
        if action == "status":
            return json.dumps(status(channel, chat_id), indent=2)
        if action == "context":
            if not channel:
                raise ValueError("channel is required for context")
            limit_chars = int(arguments.get("limit_chars") or 3000)
            text = context_for(
                channel,
                chat_id or "default",
                limit_chars=max(200, limit_chars),
            )
            return text or "(no session context)"
        if action == "resume":
            if not channel:
                raise ValueError("channel is required for resume")
            limit = int(arguments.get("limit") or 12)
            return json.dumps(
                resume_payload(channel, chat_id or "default", limit=limit),
                indent=2,
            )
        if action == "silence_check":
            text = str(arguments.get("text") or "").strip()
            if not text:
                raise ValueError("text is required for silence_check")
            return json.dumps(silence_check(text), indent=2)
        if action == "push":
            if not channel:
                raise ValueError("channel is required for push")
            role = str(arguments.get("role") or "user").strip().lower()
            text = str(arguments.get("text") or "").strip()
            if not text:
                raise ValueError("text is required for push")
            title = str(arguments.get("title") or "").strip()
            code, err = push(
                channel,
                chat_id or "default",
                role,
                text,
                title=title,
            )
            if code != 0:
                raise RuntimeError(err or "session push failed")
            return f"Session turn stored: {text[:200]}"
        if action == "reset":
            if not channel:
                raise ValueError("channel is required for reset")
            code = reset(channel, chat_id or "default")
            if code != 0:
                raise RuntimeError("session reset failed")
            return f"Session reset: {channel}:{chat_id or 'default'}"
        raise ValueError(
            "action must be list, status, context, resume, silence_check, push, or reset"
        )
    except ImportError as exc:
        raise RuntimeError(f"message_sessions unavailable: {exc}") from exc


def _handle_arka_routines(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.integrations.routines import (
            _security_gate_action,
            list_routines,
            normalize_action,
            routine_add,
            routine_remove,
            routine_set_enabled,
        )

        if action == "list":
            enabled_only = bool(arguments.get("enabled_only", False))
            rows = list_routines(enabled_only=enabled_only)
            return json.dumps(rows, indent=2)
        if action == "add":
            schedule = str(arguments.get("schedule") or "").strip()
            task = str(
                arguments.get("task")
                or arguments.get("routine_action")
                or ""
            ).strip()
            if not schedule:
                raise ValueError("schedule is required for add")
            if not task:
                raise ValueError("task is required for add")
            name = str(arguments.get("name") or arguments.get("id") or "").strip()
            normalized = normalize_action(task) or task
            if not _security_gate_action(normalized):
                raise RuntimeError("routine blocked by security gate")
            with contextlib.redirect_stdout(io.StringIO()):
                rid = routine_add(schedule, normalized, name=name, auto_install=False)
            return json.dumps(
                {"id": rid, "schedule": schedule, "action": normalized, "enabled": True},
                indent=2,
            )
        if action == "remove":
            rid = str(arguments.get("id") or arguments.get("name") or "").strip()
            if not rid:
                raise ValueError("id is required for remove")
            before = {r["id"] for r in list_routines()}
            if rid not in before:
                raise ValueError(f"No routine {rid}")
            with contextlib.redirect_stdout(io.StringIO()):
                routine_remove(rid)
            return f"Removed routine {rid}"
        if action in {"enable", "disable"}:
            rid = str(arguments.get("id") or arguments.get("name") or "").strip()
            if not rid:
                raise ValueError(f"id is required for {action}")
            row = routine_set_enabled(rid, action == "enable")
            if not row:
                raise ValueError(f"No routine {rid}")
            return json.dumps(row, indent=2)
        raise ValueError("action must be list, add, remove, enable, or disable")
    except ImportError as exc:
        raise RuntimeError(f"routines unavailable: {exc}") from exc


def _handle_arka_session_memory(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.core.session_memory import append, clear, context_for, search, status

        if action == "append":
            text = str(arguments.get("text") or "").strip()
            if not text:
                raise ValueError("text is required for append")
            long_term = bool(arguments.get("long_term", False))
            with contextlib.redirect_stdout(io.StringIO()):
                code = append(text, long_term=long_term)
            if code != 0:
                raise RuntimeError("session memory append failed")
            return f"Session memory stored: {text[:200]}"
        if action == "search":
            query = str(arguments.get("query") or arguments.get("goal") or "").strip()
            limit = int(arguments.get("limit") or 8)
            rows = search(query, limit=max(1, min(limit, 50)))
            payload = [{"file": rel, "text": body} for rel, body in rows]
            return json.dumps(payload, indent=2)
        if action == "context":
            goal = str(arguments.get("goal") or arguments.get("query") or "").strip()
            if not goal:
                raise ValueError("goal is required for context")
            limit_chars = int(arguments.get("limit_chars") or 2500)
            text = context_for(goal, limit_chars=max(200, limit_chars))
            return text or "(no session memory context)"
        if action == "status":
            return json.dumps(status(), indent=2)
        if action == "clear":
            scope = str(arguments.get("scope") or "daily").strip()
            return json.dumps(clear(scope=scope), indent=2)
        raise ValueError("action must be append, search, context, status, or clear")
    except ImportError as exc:
        raise RuntimeError(f"session_memory unavailable: {exc}") from exc


def _handle_arka_subagent(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.integrations.subagent import (
            agent_status,
            list_agents,
            resume_payload,
            spawn,
            status_summary,
        )

        if action == "spawn":
            task = str(arguments.get("task") or "").strip()
            if not task:
                raise ValueError("task is required for spawn")
            sync = bool(arguments.get("sync", False))
            session_channel = str(arguments.get("session_channel") or "").strip()
            session_chat_id = str(arguments.get("session_chat_id") or "").strip()
            data, err = spawn(
                task,
                session_channel=session_channel,
                session_chat_id=session_chat_id,
                background=not sync,
            )
            if err:
                raise RuntimeError(err)
            assert data is not None
            return json.dumps(data, indent=2)
        if action == "list":
            limit = int(arguments.get("limit") or 20)
            return json.dumps(list_agents(limit=max(1, min(limit, 100))), indent=2)
        if action == "resume":
            agent_id = str(arguments.get("agent_id") or arguments.get("id") or "").strip()
            if not agent_id:
                raise ValueError("agent_id is required for resume")
            data = resume_payload(agent_id)
            if not data:
                raise ValueError(f"unknown sub-agent: {agent_id}")
            return json.dumps(data, indent=2)
        if action == "status":
            agent_id = str(arguments.get("agent_id") or arguments.get("id") or "").strip()
            if agent_id:
                data = agent_status(agent_id)
                if not data:
                    raise ValueError(f"unknown sub-agent: {agent_id}")
                return json.dumps(data, indent=2)
            return json.dumps(status_summary(), indent=2)
        raise ValueError("action must be spawn, list, status, or resume")
    except ImportError as exc:
        raise RuntimeError(f"subagent unavailable: {exc}") from exc


def _handle_arka_webhook(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.integrations.webhook import health_payload, status_info

        if action == "status":
            return json.dumps(status_info(), indent=2)
        if action == "health":
            return json.dumps(health_payload(), indent=2)
        raise ValueError("action must be status or health")
    except ImportError as exc:
        raise RuntimeError(f"webhook unavailable: {exc}") from exc


def _handle_arka_project_rules(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "context").strip().lower()
    root_raw = str(arguments.get("root") or "").strip()
    root = Path(root_raw).expanduser() if root_raw else None
    try:
        from arka.core.project_rules import context_for, list_rules, status

        if action == "list":
            return json.dumps(list_rules(root=root), indent=2)
        if action == "status":
            return json.dumps(status(root=root), indent=2)
        if action == "context":
            goal = str(arguments.get("goal") or arguments.get("query") or "").strip()
            limit_chars = int(arguments.get("limit_chars") or 4000)
            text = context_for(goal, root=root, limit_chars=max(200, limit_chars))
            return text or "(no project rules found)"
        raise ValueError("action must be list, status, or context")
    except ImportError as exc:
        raise RuntimeError(f"project_rules unavailable: {exc}") from exc


def _handle_arka_view_data(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "preview").strip().lower()
    try:
        from arka.agent.view_data import preview_file

        if action == "preview":
            path = str(arguments.get("path") or arguments.get("file") or "").strip()
            if not path:
                raise ValueError("path is required for preview")
            max_rows = int(arguments.get("max_rows") or arguments.get("limit") or 50)
            delimiter = str(arguments.get("delimiter") or "").strip() or None
            plain = bool(arguments.get("plain", True))
            return json.dumps(
                preview_file(path, max_rows=max_rows, plain=plain, delimiter=delimiter),
                indent=2,
            )
        raise ValueError("action must be preview")
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"view_data unavailable: {exc}") from exc


def _handle_arka_clipboard(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.integrations.clipboard_history import (
            clear_entries,
            get_entry,
            list_entries,
            save_entry,
        )

        if action == "list":
            limit = int(arguments.get("limit") or 20)
            return json.dumps(list_entries(limit=limit), indent=2)
        if action == "save":
            text = arguments.get("text")
            text_arg = None if text is None else str(text)
            row, err = save_entry(text=text_arg)
            if err or row is None:
                raise RuntimeError(err or "clipboard save failed")
            return json.dumps(row, indent=2)
        if action == "get":
            index = arguments.get("index") or arguments.get("id") or 1
            row, err = get_entry(int(index))
            if err or row is None:
                raise ValueError(err or "entry not found")
            return json.dumps(row, indent=2)
        if action == "clear":
            clear_entries()
            return "Clipboard history cleared"
        raise ValueError("action must be list, save, get, or clear")
    except ImportError as exc:
        raise RuntimeError(f"clipboard_history unavailable: {exc}") from exc


def _handle_arka_remind(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.integrations.remind import add_reminder, cancel_reminder, list_reminders

        if action == "list":
            include_done = bool(arguments.get("include_done", False))
            limit = int(arguments.get("limit") or 50)
            return json.dumps(
                list_reminders(include_done=include_done, limit=max(1, min(limit, 200))),
                indent=2,
            )
        if action == "add":
            text = str(arguments.get("text") or arguments.get("message") or "").strip()
            at = str(arguments.get("at") or "").strip() or None
            in_spec = str(arguments.get("in") or arguments.get("in_spec") or "").strip() or None
            start = bool(arguments.get("start", False))
            row, err = add_reminder(text, at=at, in_spec=in_spec, start=start)
            if err or row is None:
                raise RuntimeError(err or "failed to add reminder")
            return json.dumps(row, indent=2)
        if action == "cancel":
            rid = str(arguments.get("id") or arguments.get("reminder_id") or "").strip()
            cancelled, err = cancel_reminder(rid)
            if err:
                raise ValueError(err)
            return json.dumps({"cancelled": cancelled}, indent=2)
        raise ValueError("action must be list, add, or cancel")
    except ImportError as exc:
        raise RuntimeError(f"remind unavailable: {exc}") from exc


def _handle_arka_bookmarks(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.agent import bookmarks as bm

        if action == "list":
            tag = str(arguments.get("tag") or "").strip() or None
            limit = int(arguments.get("limit") or 50)
            return json.dumps(bm.list_bookmarks(tag=tag, limit=limit), indent=2)
        if action == "save":
            url = str(arguments.get("url") or arguments.get("link") or "").strip()
            if not url:
                raise ValueError("url is required for save")
            title = str(arguments.get("title") or "").strip() or None
            tags = arguments.get("tags")
            note = str(arguments.get("note") or "").strip() or None
            return json.dumps(
                bm.save_bookmark(url, title=title, tags=tags, note=note),
                indent=2,
            )
        if action == "search":
            query = str(arguments.get("query") or arguments.get("q") or "").strip()
            limit = int(arguments.get("limit") or 50)
            return json.dumps(bm.search_bookmarks(query, limit=limit), indent=2)
        if action == "get":
            index = int(arguments.get("index") or arguments.get("id") or 0)
            return json.dumps(bm.get_bookmark(index), indent=2)
        if action == "delete":
            index = int(arguments.get("index") or arguments.get("id") or 0)
            return json.dumps(bm.delete_bookmark(index), indent=2)
        raise ValueError("action must be list, save, search, get, or delete")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"bookmarks unavailable: {exc}") from exc


def _handle_arka_docker(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "health").strip().lower()
    try:
        from arka.integrations import docker_status as ds

        if action == "health":
            return json.dumps(ds.health_payload(), indent=2)
        if action in ("ps", "containers"):
            return json.dumps(ds.list_containers(), indent=2)
        if action == "images":
            limit = int(arguments.get("limit") or 50)
            return json.dumps(ds.list_images(limit=limit), indent=2)
        if action == "logs":
            name = str(
                arguments.get("container")
                or arguments.get("name")
                or arguments.get("id")
                or ""
            ).strip()
            tail = int(arguments.get("tail") or arguments.get("limit") or 50)
            return json.dumps(ds.container_logs(name, tail=tail), indent=2)
        raise ValueError("action must be health, ps, images, or logs")
    except ValueError:
        raise
    except RuntimeError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"docker_status unavailable: {exc}") from exc


def _handle_arka_sports(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "scores").strip().lower()
    try:
        from arka.integrations import sports as sports_mod

        if action in ("scores", "live"):
            query = str(arguments.get("query") or arguments.get("league") or "").strip()
            limit = int(arguments.get("limit") or arguments.get("limit_per_league") or 3)
            return json.dumps(
                sports_mod.scores_payload(query, limit_per_league=max(1, min(limit, 20))),
                indent=2,
            )
        if action in ("leagues", "list"):
            return json.dumps(sports_mod.leagues_payload(), indent=2)
        raise ValueError("action must be scores or leagues")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"sports unavailable: {exc}") from exc


def _handle_arka_qr(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "ascii").strip().lower()
    try:
        from arka.integrations import qr_code as qr_mod

        text = str(
            arguments.get("text")
            or arguments.get("url")
            or arguments.get("data")
            or ""
        ).strip()
        if action in ("ascii", "generate", "encode"):
            return json.dumps(qr_mod.ascii_payload(text), indent=2)
        raise ValueError("action must be ascii")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"qr_code unavailable: {exc}") from exc


def _handle_arka_currency(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "convert").strip().lower()
    try:
        from arka.integrations import currency as currency_mod

        if action == "convert":
            amount = arguments.get("amount")
            if amount is None:
                raise ValueError("amount is required")
            from_ccy = str(
                arguments.get("from")
                or arguments.get("from_ccy")
                or arguments.get("source")
                or ""
            ).strip()
            to_ccy = str(
                arguments.get("to")
                or arguments.get("to_ccy")
                or arguments.get("target")
                or ""
            ).strip()
            if not from_ccy or not to_ccy:
                raise ValueError("from and to currencies are required")
            return json.dumps(
                currency_mod.convert_payload(amount, from_ccy, to_ccy),
                indent=2,
            )
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or "").strip()
            if not text:
                raise ValueError("text is required for parse")
            parsed = currency_mod.parse_convert(text)
            if parsed is None:
                raise ValueError(f"could not parse currency query: {text!r}")
            amount, from_ccy, to_ccy = parsed
            return json.dumps(
                currency_mod.convert_payload(amount, from_ccy, to_ccy),
                indent=2,
            )
        raise ValueError("action must be convert or parse")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"currency unavailable: {exc}") from exc


def _handle_arka_disk(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "usage").strip().lower()
    try:
        from arka.core import disk as disk_mod

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        if action == "usage":
            return json.dumps(disk_mod.usage_payload(path), indent=2)
        if action in ("breakdown", "categories"):
            return json.dumps(disk_mod.breakdown_payload(path), indent=2)
        raise ValueError("action must be usage or breakdown")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"disk unavailable: {exc}") from exc


def _handle_arka_repo_health(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "scan").strip().lower()
    try:
        from arka.agent import repo_health as rh

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        if action == "scan":
            return json.dumps(rh.scan_payload(path), indent=2)
        if action == "run":
            cats: set[str] | None = None
            if bool(arguments.get("test")) and not bool(arguments.get("lint")):
                cats = {"test"}
            elif bool(arguments.get("lint")) and not bool(arguments.get("test")):
                cats = {"lint"}
            category = str(arguments.get("category") or "").strip().lower()
            if category in ("test", "lint"):
                cats = {category}
            return json.dumps(rh.run_payload(path, categories=cats), indent=2)
        raise ValueError("action must be scan or run")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"repo_health unavailable: {exc}") from exc


def _handle_arka_agent_hub(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.integrations import agent_hub

        if action == "status":
            return json.dumps(agent_hub.status_payload(), indent=2)
        if action == "adapters":
            return json.dumps(agent_hub.list_adapters(), indent=2)
        if action == "detect":
            return json.dumps(agent_hub.detect_agents(), indent=2)
        if action == "doctor":
            return json.dumps(agent_hub.doctor(), indent=2)
        if action in ("list", "agents"):
            return json.dumps(
                [
                    {
                        "key": key,
                        "name": meta.get("name", key),
                        "ollama_launch": meta.get("ollama_launch", key),
                    }
                    for key, meta in agent_hub.list_agents()
                ],
                indent=2,
            )
        raise ValueError("action must be status, adapters, detect, doctor, or list")
    except ImportError as exc:
        raise RuntimeError(f"agent_hub unavailable: {exc}") from exc


def _handle_arka_team_run(arguments: dict[str, Any]) -> str:
    team = str(arguments.get("team") or arguments.get("name") or "").strip()
    task = str(arguments.get("task") or "").strip()
    if not team:
        raise ValueError("team is required")
    if not task:
        raise ValueError("task is required")
    workflow = str(arguments.get("workflow") or "").strip() or None
    try:
        from arka.teams.executor import format_run_result, run_team

        result = run_team(
            team,
            task,
            workflow_name=workflow,
            promote_final=bool(arguments.get("promote_final", False)),
        )
        if arguments.get("json"):
            return json.dumps(result, indent=2)
        return format_run_result(result)
    except ImportError as exc:
        raise RuntimeError(f"teams unavailable: {exc}") from exc


def _build_tools() -> list[ArkaMcpTool]:
    return [
        ArkaMcpTool(
            name="arka_ask",
            description="Ask Arka a question — web search, memory, calc, weather, or chat.",
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Question or request"},
                    "deep": {
                        "type": "boolean",
                        "description": "Use deep web search when applicable",
                        "default": False,
                    },
                },
                "required": ["prompt"],
            },
            handler=_handle_arka_ask,
        ),
        ArkaMcpTool(
            name="arka_remember",
            description="Store a fact, note, or channel turn in Arka unified memory.",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Content to remember"},
                    "layer": {
                        "type": "string",
                        "enum": ["auto", "fact", "note", "channel"],
                        "default": "auto",
                    },
                    "long_term": {
                        "type": "boolean",
                        "description": "Persist note to long-term session memory",
                        "default": False,
                    },
                },
                "required": ["text"],
            },
            handler=_handle_arka_remember,
        ),
        ArkaMcpTool(
            name="arka_recall",
            description="Recall facts, notes, and channel context from Arka unified memory.",
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "What to recall or search for"},
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters in response",
                        "default": 3500,
                    },
                },
                "required": ["goal"],
            },
            handler=_handle_arka_recall,
        ),
        ArkaMcpTool(
            name="arka_skill",
            description="Invoke an Arka skill or routed command by name.",
            input_schema={
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "Skill name or command head"},
                    "args": {
                        "description": "Skill arguments (string or list)",
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                    },
                },
                "required": ["skill"],
            },
            handler=_handle_arka_skill,
        ),
        ArkaMcpTool(
            name="arka_repo_map",
            description="Summarize repository layout and optional Python symbols.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repo path (default: git root or cwd)"},
                    "depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5},
                    "symbols": {"type": "boolean", "default": True},
                },
            },
            handler=_handle_arka_repo_map,
        ),
        ArkaMcpTool(
            name="arka_heartbeat",
            description="OpenClaw-style agent heartbeat — ping, status, or recent activity history.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "ping", "history"],
                        "default": "status",
                        "description": "status snapshot, ping activity, or recent history",
                    },
                    "activity": {
                        "type": "string",
                        "description": "Activity label when action=ping",
                        "default": "mcp.ping",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max events when action=history",
                        "default": 20,
                    },
                    "json": {
                        "type": "boolean",
                        "description": "Return JSON when action=status",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_heartbeat,
        ),
        ArkaMcpTool(
            name="arka_sessions",
            description="Hermes-style channel sessions — list, context, resume, silence_check, push, or reset.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "status",
                            "context",
                            "resume",
                            "silence_check",
                            "push",
                            "reset",
                        ],
                        "default": "list",
                        "description": "list, status, context, resume, silence_check, push, or reset",
                    },
                    "channel": {
                        "type": "string",
                        "description": "Channel name (required for context, resume, push, reset)",
                    },
                    "chat_id": {
                        "type": "string",
                        "description": "Chat id within the channel (default: default)",
                    },
                    "role": {
                        "type": "string",
                        "enum": ["user", "assistant", "system"],
                        "description": "Turn role when action=push",
                        "default": "user",
                    },
                    "text": {
                        "type": "string",
                        "description": "Turn text when action=push, or reply text when action=silence_check",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional session title when action=push",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max sessions (list) or turns (resume)",
                        "default": 20,
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters when action=context",
                        "default": 3000,
                    },
                },
            },
            handler=_handle_arka_sessions,
        ),
        ArkaMcpTool(
            name="arka_routines",
            description="OpenClaw-style scheduled routines — list, add, remove, enable, or disable.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "remove", "enable", "disable"],
                        "default": "list",
                        "description": "list, add, remove, enable, or disable a routine",
                    },
                    "schedule": {
                        "type": "string",
                        "description": "When to run (daily, hourly, or HH:MM) for action=add",
                    },
                    "task": {
                        "type": "string",
                        "description": "Task/command to schedule for action=add",
                    },
                    "id": {
                        "type": "string",
                        "description": "Routine id (required for remove/enable/disable; optional name for add)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional routine id when action=add",
                    },
                    "enabled_only": {
                        "type": "boolean",
                        "description": "Only include enabled routines when action=list",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_routines,
        ),
        ArkaMcpTool(
            name="arka_session_memory",
            description="OpenClaw-style markdown session memory — append, search, context, status, or clear.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["append", "search", "context", "status", "clear"],
                        "default": "status",
                        "description": "append, search, context, status, or clear notes",
                    },
                    "text": {
                        "type": "string",
                        "description": "Note text when action=append",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Recall goal when action=context (alias: query)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query when action=search",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["daily", "long_term", "all"],
                        "description": "What to clear when action=clear",
                        "default": "daily",
                    },
                    "long_term": {
                        "type": "boolean",
                        "description": "Also append to MEMORY.md when action=append",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max hits when action=search",
                        "default": 8,
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters when action=context",
                        "default": 2500,
                    },
                },
            },
            handler=_handle_arka_session_memory,
        ),
        ArkaMcpTool(
            name="arka_subagent",
            description="Hermes-style sub-agent delegation — spawn, list, status, or resume results.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["spawn", "list", "status", "resume"],
                        "default": "list",
                        "description": "spawn, list, status, or resume a sub-agent result",
                    },
                    "task": {
                        "type": "string",
                        "description": "Task prompt when action=spawn",
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Sub-agent id when action=status or resume",
                    },
                    "sync": {
                        "type": "boolean",
                        "description": "Wait for completion when action=spawn (default: background)",
                        "default": False,
                    },
                    "session_channel": {
                        "type": "string",
                        "description": "Optional channel for session context + result push",
                    },
                    "session_chat_id": {
                        "type": "string",
                        "description": "Chat id within session_channel",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max agents when action=list",
                        "default": 20,
                    },
                },
            },
            handler=_handle_arka_subagent,
        ),
        ArkaMcpTool(
            name="arka_project_rules",
            description="Cursor-style project rules — list or read AGENTS.md, CLAUDE.md, .cursor/rules.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "status", "context"],
                        "default": "context",
                        "description": "list files, status, or truncated context block",
                    },
                    "root": {
                        "type": "string",
                        "description": "Project root (default: walk up from cwd)",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Optional goal to rank relevant rule files",
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters when action=context",
                        "default": 4000,
                    },
                },
            },
            handler=_handle_arka_project_rules,
        ),
        ArkaMcpTool(
            name="arka_webhook",
            description="OpenClaw/Hermes-style webhook gateway — status or health (no serve via MCP).",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "health"],
                        "default": "status",
                        "description": "status: listener config; health: /v1/health payload",
                    },
                },
            },
            handler=_handle_arka_webhook,
        ),
        ArkaMcpTool(
            name="arka_view_data",
            description="Preview CSV/TSV tables as plain text (csvlook-style) for agents.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["preview"],
                        "default": "preview",
                        "description": "preview: return table text and column metadata",
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to a .csv or .tsv file",
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": "Max data rows to include",
                        "default": 50,
                    },
                    "delimiter": {
                        "type": "string",
                        "description": "Optional delimiter override (default: auto)",
                    },
                    "plain": {
                        "type": "boolean",
                        "description": "Disable ANSI colors (default: true for MCP)",
                        "default": True,
                    },
                },
                "required": ["path"],
            },
            handler=_handle_arka_view_data,
        ),
        ArkaMcpTool(
            name="arka_clipboard",
            description="Clipboard history — list, save, get, or clear saved clips (Cursor-style pasteboard memory).",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "save", "get", "clear"],
                        "default": "list",
                        "description": "list previews, save text/clipboard, get full entry, or clear",
                    },
                    "text": {
                        "type": "string",
                        "description": "Optional text to save (otherwise reads system clipboard)",
                    },
                    "index": {
                        "type": "integer",
                        "description": "1-based entry index when action=get",
                        "default": 1,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows when action=list",
                        "default": 20,
                    },
                },
            },
            handler=_handle_arka_clipboard,
        ),
        ArkaMcpTool(
            name="arka_remind",
            description="OpenClaw-style reminders — list, add, or cancel scheduled nudges.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "cancel"],
                        "default": "list",
                        "description": "list, add, or cancel a reminder",
                    },
                    "text": {
                        "type": "string",
                        "description": "Reminder message (may include 'in 30m' / 'at 5pm')",
                    },
                    "at": {
                        "type": "string",
                        "description": "Optional absolute time for action=add",
                    },
                    "in": {
                        "type": "string",
                        "description": "Optional relative delay (30m, 2h) for action=add",
                    },
                    "id": {
                        "type": "string",
                        "description": "Reminder id prefix when action=cancel",
                    },
                    "include_done": {
                        "type": "boolean",
                        "description": "Include cancelled/done when action=list",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows when action=list",
                        "default": 50,
                    },
                    "start": {
                        "type": "boolean",
                        "description": "Start reminder daemon after add (default: false for MCP)",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_remind,
        ),
        ArkaMcpTool(
            name="arka_bookmarks",
            description="Cursor-style bookmarks — list, save, search, get, or delete saved links.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "save", "search", "get", "delete"],
                        "default": "list",
                        "description": "list, save, search, get, or delete bookmarks",
                    },
                    "url": {
                        "type": "string",
                        "description": "URL when action=save",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional title when action=save",
                    },
                    "tags": {
                        "description": "Optional tags (comma string or array) when action=save",
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional note when action=save",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search keywords when action=search",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Filter tag when action=list",
                    },
                    "index": {
                        "type": "integer",
                        "description": "1-based index when action=get or delete",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows for list/search",
                        "default": 50,
                    },
                },
            },
            handler=_handle_arka_bookmarks,
        ),
        ArkaMcpTool(
            name="arka_docker",
            description=(
                "Docker status — health, running containers, images, or container logs "
                "(OpenClaw-style local infra awareness)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["health", "ps", "images", "logs"],
                        "default": "health",
                        "description": "health, ps (containers), images, or logs",
                    },
                    "container": {
                        "type": "string",
                        "description": "Container name when action=logs",
                    },
                    "tail": {
                        "type": "integer",
                        "description": "Log lines when action=logs",
                        "default": 50,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max images when action=images",
                        "default": 50,
                    },
                },
            },
            handler=_handle_arka_docker,
        ),
        ArkaMcpTool(
            name="arka_sports",
            description=(
                "Live sports scores (ESPN) — fetch scores by league query "
                "or list supported leagues (IPL, NFL, EPL, NBA, …)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["scores", "leagues"],
                        "default": "scores",
                        "description": "scores: live scoreboard; leagues: supported aliases",
                    },
                    "query": {
                        "type": "string",
                        "description": "League/sport query e.g. ipl, nfl, epl, all",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max events per league",
                        "default": 3,
                    },
                },
            },
            handler=_handle_arka_sports,
        ),
        ArkaMcpTool(
            name="arka_qr",
            description=(
                "Generate a QR code as ASCII art from text or a URL "
                "(useful for sharing links offline in the terminal)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["ascii"],
                        "default": "ascii",
                        "description": "ascii: return QR as terminal ASCII art",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text or URL to encode",
                    },
                    "url": {
                        "type": "string",
                        "description": "Alias for text when encoding a URL",
                    },
                },
                            },
            handler=_handle_arka_qr,
        ),
        ArkaMcpTool(
            name="arka_currency",
            description=(
                "Currency conversion — convert amounts between ISO currencies "
                "or parse a natural-language query like '100 USD to INR'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["convert", "parse"],
                        "default": "convert",
                        "description": "convert: explicit amount/from/to; parse: natural language",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount when action=convert",
                    },
                    "from": {
                        "type": "string",
                        "description": "Source currency (ISO code or name)",
                    },
                    "to": {
                        "type": "string",
                        "description": "Target currency (ISO code or name)",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural-language query when action=parse",
                    },
                },
            },
            handler=_handle_arka_currency,
        ),
        ArkaMcpTool(
            name="arka_disk",
            description=(
                "Disk space — quick usage summary or home-folder breakdown by category "
                "(videos, downloads, cache, etc.)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["usage", "breakdown"],
                        "default": "usage",
                        "description": "usage: df summary; breakdown: category scan",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional path to measure (default: home directory)",
                    },
                },
            },
            handler=_handle_arka_disk,
        ),
        ArkaMcpTool(
            name="arka_repo_health",
            description=(
                "Cursor-style repo health — scan for lint/test commands or run them "
                "in the current project."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["scan", "run"],
                        "default": "scan",
                        "description": "scan: detect checks; run: execute checks",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional project root (default: git root / cwd)",
                    },
                    "test": {
                        "type": "boolean",
                        "description": "When action=run, only run test checks",
                        "default": False,
                    },
                    "lint": {
                        "type": "boolean",
                        "description": "When action=run, only run lint checks",
                        "default": False,
                    },
                    "category": {
                        "type": "string",
                        "enum": ["test", "lint"],
                        "description": "Optional category filter when action=run",
                    },
                },
            },
            handler=_handle_arka_repo_health,
        ),
        ArkaMcpTool(
            name="arka_agent_hub",
            description=(
                "Agent Hub inspection — status, adapters, detect installed agents, "
                "or doctor checks (Hermes/OpenClaw multi-agent unification)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "adapters", "detect", "doctor", "list"],
                        "default": "status",
                        "description": (
                            "status: hub paths and sync timestamps; "
                            "adapters: MCP merge status per agent; "
                            "detect: which agent configs exist; "
                            "doctor: health checks; "
                            "list: registered launch agents"
                        ),
                    },
                },
            },
            handler=_handle_arka_agent_hub,
        ),
        ArkaMcpTool(
            name="arka_team_run",
            description="Run an Arka agent team workflow on a task.",
            input_schema={
                "type": "object",
                "properties": {
                    "team": {"type": "string", "description": "Team name"},
                    "task": {"type": "string", "description": "Task description"},
                    "workflow": {"type": "string", "description": "Optional workflow override"},
                    "promote_final": {"type": "boolean", "default": False},
                    "json": {"type": "boolean", "default": False},
                },
                "required": ["team", "task"],
            },
            handler=_handle_arka_team_run,
        ),
    ]


def list_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in _build_tools()
    ]


def list_tool_names() -> list[str]:
    return [tool.name for tool in _build_tools()]


def mcp_server_launch_spec() -> dict[str, Any]:
    """Cursor-compatible stdio launch spec for this MCP server."""
    arka_cmd = shutil.which("arka")
    if arka_cmd:
        return {"command": arka_cmd, "args": ["mcp", "serve"]}
    from arka.paths import python_executable

    return {"command": python_executable(), "args": ["-m", "arka", "mcp", "serve"]}


def install_config_snippet(*, agent: str = "cursor") -> str:
    """Return JSON config snippet for Cursor, Claude Desktop, or generic clients."""
    entry = mcp_server_launch_spec()
    payload: dict[str, Any] = {"mcpServers": {ARKA_MCP_SERVER_KEY: entry}}
    if agent.strip().lower() in {"claude", "claude_desktop", "claude-desktop"}:
        payload = {
            "mcpServers": {
                ARKA_MCP_SERVER_KEY: {
                    **entry,
                    "env": {},
                }
            }
        }
    return json.dumps(payload, indent=2) + "\n"


def ensure_arka_self_in_config() -> bool:
    """Add arka self-MCP entry to ~/.config/arka/mcp.json if missing."""
    from arka.integrations.mcp_manager import load_mcp_config, save_mcp_config

    data = load_mcp_config()
    servers = data.setdefault("mcpServers", {})
    if ARKA_MCP_SERVER_KEY in servers:
        return False
    servers[ARKA_MCP_SERVER_KEY] = mcp_server_launch_spec()
    save_mcp_config(data)
    return True


class ArkaMcpServer:
    """Minimal newline-delimited JSON-RPC MCP server over stdio."""

    def __init__(
        self,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self._tools = {tool.name: tool for tool in _build_tools()}
        self._lock = threading.Lock()
        self._initialized = False

    def _send(self, payload: dict[str, Any]) -> None:
        self.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.stdout.flush()

    def _error_response(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def handle_message(self, body: dict[str, Any]) -> dict[str, Any] | None:
        method = str(body.get("method", "")).strip()
        request_id = body.get("id")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if method == "notifications/initialized":
            return None

        if method == "initialize":
            self._initialized = True
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": list_tool_definitions()},
            }

        if method == "tools/call":
            name = str(params.get("name") or "").strip()
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool = self._tools.get(name)
            if not tool:
                return self._error_response(request_id, -32602, f"Unknown tool: {name}")
            try:
                text = tool.handler(arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _text_result(text),
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _text_result(str(exc)[:2000], is_error=True),
                }

        if request_id is None:
            return None
        return self._error_response(request_id, -32601, f"Method not found: {method}")

    def process_line(self, line: str) -> dict[str, Any] | None:
        line = line.strip()
        if not line:
            return None
        try:
            body = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(body, dict):
            return None
        with self._lock:
            return self.handle_message(body)

    def run(self) -> None:
        for line in self.stdin:
            response = self.process_line(line)
            if response is not None:
                self._send(response)


def serve_stdio() -> int:
    """Run the MCP server on stdio until stdin closes."""
    ArkaMcpServer().run()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry for bundled arka_mcp_server.py — defaults to serve."""
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] in ("-h", "--help", "help"):
        print("Usage: arka mcp serve  |  python -m arka.integrations.mcp_server")
        return 0
    return serve_stdio()


def doctor(*, timeout: float = 8.0) -> tuple[str, int]:
    """Verify the stdio MCP server initializes and lists tools."""
    from arka.integrations.mcp_manager import McpStdioClient

    spec = mcp_server_launch_spec()
    client = McpStdioClient(
        server=ARKA_MCP_SERVER_KEY,
        command=spec["command"],
        args=list(spec.get("args") or []),
        timeout=timeout,
    )
    lines: list[str] = [
        f"command\t{spec['command']}",
        f"args\t{' '.join(spec.get('args') or [])}",
        f"tools_expected\t{len(list_tool_names())}",
    ]
    try:
        info = client.connect()
        tools = client.list_tools()
        server_info = info.get("serverInfo") if isinstance(info, dict) else {}
        lines.append(f"initialize\tok\t{server_info}")
        lines.append(f"tools_list\tok\tcount={len(tools)}")
        for tool in tools:
            lines.append(f"tool\t{tool.name}")
        missing = [name for name in list_tool_names() if name not in {t.name for t in tools}]
        if missing:
            lines.append(f"missing\t{','.join(missing)}")
            return "\n".join(lines), 1
        lines.append("summary\tok")
        return "\n".join(lines), 0
    except Exception as exc:
        lines.append(f"error\t{exc}")
        return "\n".join(lines), 1
    finally:
        client.close()


__all__ = [
    "ARKA_MCP_SERVER_KEY",
    "ArkaMcpServer",
    "doctor",
    "ensure_arka_self_in_config",
    "install_config_snippet",
    "list_tool_definitions",
    "list_tool_names",
    "main",
    "mcp_server_launch_spec",
    "serve_stdio",
]
