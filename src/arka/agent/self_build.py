#!/usr/bin/env python3
"""Self-build loop — Arka uses its own MCP tools to analyze and improve itself."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from arka.env import env_int
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass

    def env_int(name: str, default: int) -> int:
        return int(os.environ.get(name) or str(default))


DEFAULT_MAX_ROUNDS = env_int("SELF_BUILD_MAX_ROUNDS", 2)
DEFAULT_MAX_STEPS = env_int("SELF_BUILD_MAX_STEPS", 15)
RESULT_LIMIT = 6000
OBSERVABILITY_TARGETS = frozenset(
    {"observability", "dashboard", "dashboards", "signoz", "signoz-dashboard", "signoz-dashboards"}
)


def self_build_root() -> Path:
    if raw := os.environ.get("SELF_BUILD_DIR", "").strip():
        return Path(raw).expanduser()
    return cache_dir() / "self_build"


def _session_path(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return self_build_root() / f"{safe}.json"


def _load(session_id: str) -> dict[str, Any] | None:
    path = _session_path(session_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save(data: dict[str, Any]) -> None:
    root = self_build_root()
    root.mkdir(parents=True, exist_ok=True)
    session_id = str(data.get("id") or uuid.uuid4().hex[:10])
    data["id"] = session_id
    data["updated"] = time.time()
    _session_path(session_id).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def list_sessions(*, limit: int = 20) -> list[dict[str, Any]]:
    root = self_build_root()
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rows.append(data)
        except (OSError, json.JSONDecodeError):
            continue
        if len(rows) >= limit:
            break
    return rows


def session_status(session_id: str) -> dict[str, Any] | None:
    return _load(session_id)


def status_summary() -> dict[str, Any]:
    rows = list_sessions(limit=100)
    by_status: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    return {"count": len(rows), "by_status": by_status, "dir": str(self_build_root())}


def _mcp_tool(name: str, arguments: dict[str, Any]) -> str:
    from arka.integrations.mcp_server import call_mcp_tool

    return call_mcp_tool(name, arguments)


def _parse_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class McpAudit:
    scan: dict[str, Any] = field(default_factory=dict)
    run: dict[str, Any] = field(default_factory=dict)
    repo_map: str = ""
    route_hint: str = ""


def mcp_audit(root: Path, *, target: str = "") -> McpAudit:
    """Repo health + map via in-process MCP handlers."""
    path = str(root)
    audit = McpAudit()
    audit.scan = _parse_json(_mcp_tool("arka_repo_health", {"action": "scan", "path": path}))
    audit.run = _parse_json(_mcp_tool("arka_repo_health", {"action": "run", "path": path}))
    try:
        audit.repo_map = _mcp_tool(
            "arka_repo_map",
            {"path": path, "depth": 2, "symbols": False},
        )[:4000]
    except Exception as exc:
        audit.repo_map = f"(repo_map unavailable: {exc})"
    if target:
        try:
            audit.route_hint = _mcp_tool("arka_route", {"prompt": f"improve arka {target}"})[:500]
        except Exception:
            audit.route_hint = ""
    return audit


def _is_observability_target(target: str) -> bool:
    t = " ".join((target or "").split()).strip().lower()
    if not t:
        return False
    if t in OBSERVABILITY_TARGETS:
        return True
    return any(token in t for token in ("observability", "dashboard", "signoz"))


def format_observability_plan(*, apply: bool) -> str:
    lines = [
        "━━━ Observability plan ━━━",
        "",
        "Bundled SigNoz dashboard: signoz/dashboards/arka-agent-observability.json",
        "Panels: service overview, skill dispatch latency/errors, routing decisions,",
        "        LLM failover + token usage, correlated logs, error breakdown.",
        "",
        "Install:",
        "  arka signoz dashboard install",
        "  arka signoz dashboard install --alerts",
        "",
    ]
    if apply:
        lines.append("Apply mode: installing dashboard via SigNoz API (+ bundled alerts).")
    else:
        lines.append("Plan-only: re-run with --apply to install into local SigNoz.")
    return "\n".join(lines)


def apply_observability_improvements(
    *,
    apply: bool,
    replace: bool = False,
    use_mcp: bool = False,
    with_alerts: bool = True,
) -> tuple[int, dict[str, Any]]:
    """Install bundled SigNoz dashboard (and optional alerts)."""
    from arka.core.output import user_msg
    from arka.telemetry.signoz_dashboards import install_observability_bundle, list_dashboard_templates

    templates = list_dashboard_templates()
    if "arka-agent-observability" not in templates:
        user_msg("✗ Bundled dashboard template missing (signoz/dashboards/)")
        return 1, {"error": "missing dashboard template"}

    if not apply:
        return 0, {"planned": True, "templates": templates}

    try:
        bundle = install_observability_bundle(
            dry_run=False,
            replace=replace,
            alerts=with_alerts,
            use_mcp=use_mcp,
        )
    except Exception as exc:
        user_msg(f"✗ Observability install failed: {exc}")
        return 1, {"error": str(exc)}

    dashboard = bundle.get("dashboard") or {}
    if dashboard.get("skipped"):
        user_msg(f"Dashboard skipped: {dashboard.get('message', 'already exists')}")
    elif dashboard.get("created"):
        user_msg(f"✓ Dashboard installed: {dashboard.get('title', 'Arka Agent Observability')}")
    alerts = bundle.get("alerts") or []
    created_alerts = sum(1 for row in alerts if row.get("created"))
    if with_alerts and created_alerts:
        user_msg(f"✓ Alerts created: {created_alerts}")
    return 0, bundle


def format_audit_summary(audit: McpAudit) -> str:
    lines = ["━━━ Arka Self-Build (MCP) ━━━", ""]
    scan_count = audit.scan.get("count", 0)
    lines.append(f"MCP scan: {scan_count} check(s) detected")
    run = audit.run
    if run:
        lines.append(
            f"MCP run: passed={run.get('passed', 0)} failed={run.get('failed', 0)} "
            f"skipped={run.get('skipped', 0)} ok={run.get('ok')}"
        )
        for row in run.get("results") or []:
            if row.get("status") == "failed":
                preview = str(row.get("preview") or "").splitlines()[0][:120]
                lines.append(f"  ✗ {row.get('name')}: {preview}")
    if audit.route_hint:
        lines.append(f"Route hint: {audit.route_hint[:200]}")
    return "\n".join(lines)


def _check_mode(*, apply: bool) -> tuple[bool, str]:
    if not apply:
        return True, ""
    try:
        from arka.core.mode import get_mode

        mode = get_mode()
        if mode != "agent":
            return False, f"self build --apply requires agent mode (current: {mode}). Run: arka mode agent"
    except ImportError:
        pass
    return True, ""


def _apply_via_goal(
    target: str,
    *,
    root: Path,
    plan: Any,
    max_rounds: int,
    max_steps: int,
    yes: bool,
) -> int:
    from arka.agent import self_improve

    return self_improve.run_self_improve(
        target,
        max_rounds=max_rounds,
        max_steps=max_steps,
        auto_init=False,
        yes=yes,
        apply=True,
        fast=False,
    )


def _apply_via_jules(goal: str, *, max_steps: int) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = _parse_json(
            _mcp_tool(
                "arka_jules",
                {
                    "action": "assign",
                    "task": goal,
                    "sync": True,
                    "max_steps": max_steps,
                },
            )
        )
        if payload.get("id"):
            return payload, ""
        return None, "jules assign returned no session id"
    except Exception as exc:
        return None, str(exc)


def run_self_build(
    target: str = "",
    *,
    apply: bool = False,
    yes: bool = False,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    max_steps: int = DEFAULT_MAX_STEPS,
    auto_init: bool = True,
    use_jules: bool = False,
    session_id: str = "",
) -> int:
    """Audit via MCP → plan → optional apply → verify."""
    from arka.agent import self_improve
    from arka.core.output import debug_msg, user_msg

    try:
        root = self_improve.ensure_arka_project(auto_init=auto_init)
    except Exception as exc:
        user_msg(str(exc))
        return 1

    target = self_improve._normalize_target(target)
    observability = _is_observability_target(target)

    if apply and not observability:
        ok, reason = _check_mode(apply=apply)
        if not ok:
            user_msg(reason)
            return 1

    session: dict[str, Any] = {
        "id": session_id or uuid.uuid4().hex[:10],
        "status": "running",
        "target": target,
        "apply": apply,
        "use_jules": use_jules,
        "root": str(root),
        "started": time.time(),
        "phases": {},
    }
    _save(session)

    debug_msg(f"Arka self-build — {root}")
    audit = mcp_audit(root, target=target)
    session["phases"]["audit"] = {
        "scan_count": audit.scan.get("count", 0),
        "run_ok": audit.run.get("ok"),
        "failed_checks": [
            row.get("name")
            for row in audit.run.get("results") or []
            if row.get("status") == "failed"
        ],
    }
    print(format_audit_summary(audit))

    if _is_observability_target(target):
        print(format_observability_plan(apply=apply))
        exit_code, obs_result = apply_observability_improvements(
            apply=apply,
            use_mcp=False,
            with_alerts=True,
        )
        session["phases"]["observability"] = obs_result
        session["status"] = "done" if exit_code == 0 else "failed"
        session["exit_code"] = exit_code
        session["finished"] = time.time()
        _save(session)
        if exit_code == 0 and apply:
            user_msg("✓ Observability self-build complete")
        elif exit_code == 0:
            user_msg("Plan ready — run: self build observability --apply")
        return exit_code

    context = self_improve._read_repo_context(root)
    if audit.repo_map and not audit.repo_map.startswith("("):
        context = f"{context[:6000]}\n\n=== repo map (MCP) ===\n{audit.repo_map[:3000]}"
    diag = self_improve.run_diagnostics(root)
    routing_notes = self_improve._routing_analysis(root, target)
    docs = self_improve._docs_check(root)
    plan = self_improve.generate_plan(
        target,
        context=context,
        diag=diag,
        routing_notes=routing_notes,
        root=root,
    )
    session["phases"]["plan"] = {
        "focus": plan.focus,
        "proposal": plan.proposal,
        "files": plan.files,
        "tests": plan.tests,
    }
    print(
        self_improve.format_plan_output(
            plan,
            apply=apply,
            diag=diag,
            routing_notes=routing_notes,
            target=target,
            docs=docs,
        )
    )

    if not apply:
        session["status"] = "planned"
        session["finished"] = time.time()
        _save(session)
        self_improve.record_attempt(plan, outcome="planned", notes="self_build mcp", root=root)
        return 0

    user_msg("Applying via MCP orchestration…")
    if use_jules:
        goal = self_improve.build_goal(target, context=context, diag=diag, root=root, plan=plan)
        jules_data, err = _apply_via_jules(goal, max_steps=max_steps)
        session["phases"]["apply"] = {"engine": "jules", "error": err, "session": jules_data}
        if err:
            session["status"] = "failed"
            session["finished"] = time.time()
            _save(session)
            user_msg(f"✗ Jules apply failed: {err}")
            self_improve.record_attempt(plan, outcome="failed", notes=err, root=root)
            return 1
        exit_code = int((jules_data or {}).get("exit_code") or 0)
    else:
        exit_code = _apply_via_goal(
            target,
            root=root,
            plan=plan,
            max_rounds=max_rounds,
            max_steps=max_steps,
            yes=yes,
        )
        session["phases"]["apply"] = {"engine": "goal", "exit_code": exit_code}

    verify = mcp_audit(root, target=target)
    session["phases"]["verify"] = {
        "run_ok": verify.run.get("ok"),
        "failed_checks": [
            row.get("name")
            for row in verify.run.get("results") or []
            if row.get("status") == "failed"
        ],
    }
    diag_after = self_improve.run_diagnostics(root)
    session["phases"]["verify"]["diag_passed"] = diag_after.passed

    ok = exit_code == 0 and diag_after.passed and bool(verify.run.get("ok", True))
    session["status"] = "done" if ok else "failed"
    session["exit_code"] = exit_code
    session["finished"] = time.time()
    _save(session)

    if ok:
        user_msg("✓ Self-build complete")
        self_improve.record_attempt(plan, outcome="passed", notes="self_build mcp", root=root)
        return 0

    user_msg("✗ Self-build finished with issues")
    self_improve.record_attempt(plan, outcome="failed", notes=f"exit {exit_code}", root=root)
    return exit_code if exit_code != 0 else 1


def parse_self_build_argv(argv: list[str]) -> tuple[str, bool, dict[str, Any]]:
    """Parse target and flags from argv."""
    apply = False
    yes = False
    use_jules = False
    extras: dict[str, Any] = {}
    tokens: list[str] = []
    flat: list[str] = []
    for raw in argv:
        flat.extend(raw.split())

    it = iter(flat)
    for tok in it:
        if tok == "--apply":
            apply = True
        elif tok in ("-y", "--yes"):
            yes = True
        elif tok == "--jules":
            use_jules = True
        elif tok in ("-n", "--max-rounds") and (nxt := next(it, None)) is not None:
            extras["max_rounds"] = int(nxt)
        elif tok in ("-s", "--max-steps") and (nxt := next(it, None)) is not None:
            extras["max_steps"] = int(nxt)
        elif tok in ("--target", "--dashboard") and (nxt := next(it, None)) is not None:
            tokens.append(nxt)
        elif tok == "--no-auto-init":
            extras["auto_init"] = False
        elif tok in ("build", "self_build", "self-build", "improve_self", "improve-self"):
            continue
        else:
            tokens.append(tok)

    from arka.agent.self_improve import _normalize_target, _split_improve_flags_from_text

    target, embedded_apply = _split_improve_flags_from_text(_normalize_target(" ".join(tokens)))
    return target, apply or embedded_apply, {**extras, "yes": yes, "use_jules": use_jules}


def route_command(text: str) -> str:
    """NL → self_build skill line."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""

    if re.match(r"(?i)^(?:arka\s+)?self\s+build\s+(?:memory|status|list)\s*$", raw):
        sub = re.search(r"(memory|status|list)\s*$", raw, re.I)
        return f"self_build {sub.group(1).lower()}" if sub else "self_build status"

    mcp_phrases = (
        r"(?i)\b(?:self\s+build|improve\s+self|build\s+arka(?:\s+with\s+mcp)?|"
        r"use\s+mcp\s+to\s+(?:fix|improve)\s+arka|improve\s+arka\s+using\s+mcp|"
        r"mcp\s+self\s+improve|self\s+improve\s+(?:with|via|using)\s+mcp|"
        r"use\s+arka\s+mcp\s+to\s+improve\s+arka)\b"
    )
    if not re.search(mcp_phrases, raw):
        return ""

    target = raw
    for pattern in (
        r"(?i)^(?:arka\s+)?self\s+build\s*",
        r"(?i)^(?:arka\s+)?improve\s+self\s*",
        r"(?i)^(?:arka\s+)?build\s+arka(?:\s+with\s+mcp)?\s*",
        r"(?i)^(?:arka\s+)?use\s+mcp\s+to\s+(?:fix|improve)\s+arka\s*",
        r"(?i)^(?:arka\s+)?improve\s+arka\s+using\s+mcp\s*",
        r"(?i)^(?:arka\s+)?use\s+arka\s+mcp\s+to\s+improve\s+arka\s*",
        r"(?i)^(?:arka\s+)?mcp\s+self\s+improve\s*",
        r"(?i)^(?:arka\s+)?self\s+improve\s+(?:with|via|using)\s+mcp\s*",
    ):
        stripped = re.sub(pattern, "", target).strip()
        if stripped != target:
            target = stripped
            break

    from arka.agent.self_improve import _normalize_target, _split_improve_flags_from_text

    target, apply = _split_improve_flags_from_text(_normalize_target(target))
    line = "self_build"
    if target:
        line += f" {target}"
    if apply:
        line += " --apply"
    return line


def main(argv: list[str] | None = None) -> int:
    from arka.paths import load_env_file

    load_env_file()

    parser = argparse.ArgumentParser(description="Arka self-build — MCP-orchestrated self-improvement")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Run MCP self-build loop")
    p_run.add_argument("target", nargs="*", help="Optional improvement focus")
    p_run.add_argument("--apply", action="store_true")
    p_run.add_argument("--jules", action="store_true", help="Apply via arka_jules instead of goal agent")
    p_run.add_argument("-n", "--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    p_run.add_argument("-s", "--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    p_run.add_argument("-y", "--yes", action="store_true")
    p_run.add_argument("--no-auto-init", action="store_true")

    p_route = sub.add_parser("route", help="NL routing helper")
    p_route.add_argument("text", nargs="+")

    sub.add_parser("status", help="Summary of cached self-build sessions")
    p_list = sub.add_parser("list", help="List recent sessions")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--limit", type=int, default=20)

    p_show = sub.add_parser("show", help="Show one session")
    p_show.add_argument("session_id")

    args = parser.parse_args(argv)

    if args.cmd == "run":
        target, apply, extras = parse_self_build_argv(list(args.target))
        return run_self_build(
            target,
            apply=apply or args.apply,
            yes=args.yes or extras.get("yes", False),
            max_rounds=extras.get("max_rounds", args.max_rounds),
            max_steps=extras.get("max_steps", args.max_steps),
            auto_init=extras.get("auto_init", not args.no_auto_init),
            use_jules=args.jules or extras.get("use_jules", False),
        )

    if args.cmd == "route":
        line = route_command(" ".join(args.text))
        if line:
            print(line)
            return 0
        return 1

    if args.cmd == "status":
        print(json.dumps(status_summary(), indent=2))
        return 0

    if args.cmd == "list":
        rows = list_sessions(limit=max(1, args.limit))
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("No self-build sessions yet.")
            return 0
        for row in rows:
            sid = row.get("id", "?")
            status = row.get("status", "?")
            target = row.get("target") or "general"
            print(f"  [{status}] {sid}: {target}")
        return 0

    if args.cmd == "show":
        data = session_status(args.session_id)
        if not data:
            print(f"Unknown session: {args.session_id}", file=sys.stderr)
            return 1
        print(json.dumps(data, indent=2))
        return 0

    if argv and argv[0] not in ("-h", "--help") and args.cmd is None:
        target, apply, extras = parse_self_build_argv(argv)
        return run_self_build(
            target,
            apply=apply,
            yes=extras.get("yes", False),
            max_rounds=extras.get("max_rounds", DEFAULT_MAX_ROUNDS),
            max_steps=extras.get("max_steps", DEFAULT_MAX_STEPS),
            auto_init=extras.get("auto_init", True),
            use_jules=extras.get("use_jules", False),
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
