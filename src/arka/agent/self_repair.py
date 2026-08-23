#!/usr/bin/env python3
"""Self-repair — analyze Arka logs, diagnose issues, optionally auto-fix."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ISSUE_CATEGORIES = frozenset(
    {
        "llm_exhaustion",
        "routing_misroute",
        "missing_deps",
        "config_error",
        "mcp_error",
        "skill_crash",
        "fish_python_parity",
    }
)

_LLM_EXHAUST_RE = re.compile(
    r"(?i)(?:exhaust|quota|429|rate.?limit|resource_exhausted|tokens per day|all models)"
)
_ROUTING_RE = re.compile(
    r"(?i)(?:no route|misroute|unknown skill|routing failed|could not route|fallback to chat)"
)
_IMPORT_RE = re.compile(r"(?i)(?:modulenotfounderror|importerror|no module named)")
_CONFIG_RE = re.compile(r"(?i)(?:config\.json|invalid json|missing api key|no llm provider)")
_SKILL_CRASH_RE = re.compile(r"(?i)(?:skill (?:crash|failed|error)|traceback|exception in skill)")
_PLAYWRIGHT_RE = re.compile(r"(?i)playwright")

_BLOCKED_FIX_RES = (
    re.compile(r"(?i)(?:^|/)\.env"),
    re.compile(r"(?i)(?:^|/)secrets(?:/|$)"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password)"),
)


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        return Path.home() / ".config" / "arka"


def memory_path() -> Path:
    return _config_dir() / "self-repair-memory.json"


def load_memory() -> dict[str, Any]:
    path = memory_path()
    if not path.is_file():
        return {"repairs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"repairs": []}
    if not isinstance(data, dict):
        return {"repairs": []}
    data.setdefault("repairs", [])
    return data


def save_memory(data: dict[str, Any]) -> None:
    path = memory_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def record_repair(*, actions: list["RepairAction"], apply: bool, notes: str = "") -> None:
    data = load_memory()
    repairs: list[dict[str, Any]] = list(data.get("repairs") or [])
    repairs.append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "apply": apply,
            "actions": [
                {
                    "action": a.action,
                    "category": a.category,
                    "description": a.description,
                    "applied": a.applied,
                    "result": a.result,
                }
                for a in actions
            ],
            "notes": notes,
        }
    )
    data["repairs"] = repairs[-100:]
    save_memory(data)


@dataclass
class LogIssue:
    category: str
    message: str
    source: str
    confidence: str = "medium"
    evidence: str = ""
    ts: str = ""


@dataclass
class RepairAction:
    category: str
    action: str
    description: str
    confidence: str = "medium"
    command: str = ""
    safe: bool = True
    applied: bool = False
    result: str = ""


@dataclass
class RepairPlan:
    issues: list[LogIssue] = field(default_factory=list)
    actions: list[RepairAction] = field(default_factory=list)
    analyzed_at: str = ""
    log_paths: list[str] = field(default_factory=list)


def _classify_line(text: str) -> str | None:
    low = text.lower()
    if _LLM_EXHAUST_RE.search(low):
        return "llm_exhaustion"
    if _ROUTING_RE.search(low):
        return "routing_misroute"
    if _IMPORT_RE.search(low):
        return "missing_deps"
    if _CONFIG_RE.search(low):
        return "config_error"
    if _SKILL_CRASH_RE.search(low):
        return "skill_crash"
    if "mcp" in low and ("error" in low or "failed" in low):
        return "mcp_error"
    return None


def _parse_mcp_log_rows(*, limit: int = 200) -> tuple[list[dict[str, Any]], Path | None]:
    try:
        from arka.integrations.mcp_logs import mcp_log_path
    except ImportError:
        return [], None
    path = mcp_log_path()
    if not path.is_file():
        return [], path
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit * 2 :]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows[-limit:], path


def _scan_config_logs(*, limit: int = 100) -> list[tuple[str, str]]:
    """Return (path, line) pairs from ~/.config/arka/logs/."""
    log_dir = _config_dir() / "logs"
    if not log_dir.is_dir():
        return []
    hits: list[tuple[str, str]] = []
    for path in sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[-limit:]:
            if line.strip():
                hits.append((str(path), line))
        if len(hits) >= limit:
            break
    return hits[:limit]


def _check_llm_exhaustion_state() -> list[LogIssue]:
    issues: list[LogIssue] = []
    try:
        from arka.llm.fallback import EXHAUSTION

        exhausted = EXHAUSTION.list_exhausted()
        if exhausted:
            pairs = ", ".join(f"{p}/{m}" for p, m in exhausted[:8])
            issues.append(
                LogIssue(
                    category="llm_exhaustion",
                    message=f"Session LLM exhaustion active ({len(exhausted)} model(s))",
                    source="llm.fallback",
                    confidence="high",
                    evidence=pairs,
                )
            )
    except ImportError:
        pass
    return issues


def _check_config_health() -> list[LogIssue]:
    issues: list[LogIssue] = []
    cfg_path = _config_dir() / "config.json"
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                issues.append(
                    LogIssue(
                        category="config_error",
                        message="config.json is not a JSON object",
                        source="config.json",
                        confidence="high",
                    )
                )
        except json.JSONDecodeError as exc:
            issues.append(
                LogIssue(
                    category="config_error",
                    message=f"config.json parse error: {exc}",
                    source="config.json",
                    confidence="high",
                )
            )
    try:
        from arka.llm.fallback import llm_doctor_lines, provider_available, provider_specs

        configured = any(provider_available(spec.slug) for spec in provider_specs())
        if not configured:
            issues.append(
                LogIssue(
                    category="config_error",
                    message="No LLM provider configured — add API keys to .env",
                    source="doctor",
                    confidence="high",
                    evidence="; ".join(llm_doctor_lines()[:3]),
                )
            )
    except ImportError:
        pass
    return issues


def _check_missing_deps() -> list[LogIssue]:
    issues: list[LogIssue] = []
    try:
        import importlib.util

        if importlib.util.find_spec("playwright") is None:
            issues.append(
                LogIssue(
                    category="missing_deps",
                    message="Playwright not installed (browse_web / web automation)",
                    source="doctor",
                    confidence="high",
                    evidence="python -m pip install playwright",
                )
            )
    except ImportError:
        pass
    return issues


def analyze_logs(*, limit: int = 200) -> RepairPlan:
    """Parse MCP and config logs; classify issues."""
    plan = RepairPlan(analyzed_at=datetime.now(timezone.utc).isoformat())
    seen: set[tuple[str, str]] = set()

    rows, mcp_path = _parse_mcp_log_rows(limit=limit)
    if mcp_path is not None:
        plan.log_paths.append(str(mcp_path))

    for row in rows:
        parts = [
            str(row.get(key) or "")
            for key in ("event", "tool", "status", "error", "prompt", "method")
        ]
        text = " ".join(p for p in parts if p)
        category = _classify_line(text)
        status = str(row.get("status") or "").lower()
        if not category and status == "error":
            category = "mcp_error"
        if not category:
            continue
        msg = str(row.get("error") or row.get("tool") or text)[:240]
        key = (category, msg[:80])
        if key in seen:
            continue
        seen.add(key)
        conf = "high" if category in {"llm_exhaustion", "missing_deps"} else "medium"
        plan.issues.append(
            LogIssue(
                category=category,
                message=msg or category,
                source="mcp.jsonl",
                confidence=conf,
                evidence=text[:300],
                ts=str(row.get("ts") or ""),
            )
        )

    for path, line in _scan_config_logs(limit=limit // 2):
        if path not in plan.log_paths:
            plan.log_paths.append(path)
        category = _classify_line(line)
        if not category:
            continue
        try:
            row = json.loads(line)
            msg = str(row.get("error") or row.get("message") or line)[:240]
            ts = str(row.get("ts") or "")
        except json.JSONDecodeError:
            msg = line[:240]
            ts = ""
        key = (category, msg[:80])
        if key in seen:
            continue
        seen.add(key)
        plan.issues.append(
            LogIssue(
                category=category,
                message=msg,
                source=Path(path).name,
                confidence="medium",
                evidence=line[:300],
                ts=ts,
            )
        )

    for issue in (
        *_check_llm_exhaustion_state(),
        *_check_config_health(),
        *_check_missing_deps(),
    ):
        key = (issue.category, issue.message[:80])
        if key not in seen:
            seen.add(key)
            plan.issues.append(issue)

    return plan


def build_repair_plan(plan: RepairPlan | None = None) -> RepairPlan:
    """Turn analyzed issues into a repair plan with confidence scores."""
    if plan is None:
        plan = analyze_logs()
    actions: list[RepairAction] = []
    categories = {issue.category for issue in plan.issues}

    if "llm_exhaustion" in categories:
        actions.append(
            RepairAction(
                category="llm_exhaustion",
                action="reset_llm_exhaustion",
                description="Clear session LLM provider/model exhaustion cache",
                confidence="high",
                command="arka llm reset-exhaustion",
                safe=True,
            )
        )

    if "missing_deps" in categories:
        playwright_needed = any(
            _PLAYWRIGHT_RE.search(issue.message) or _PLAYWRIGHT_RE.search(issue.evidence)
            for issue in plan.issues
            if issue.category == "missing_deps"
        ) or any(i.category == "missing_deps" and "playwright" in i.message.lower() for i in plan.issues)
        if playwright_needed:
            actions.append(
                RepairAction(
                    category="missing_deps",
                    action="install_playwright",
                    description="Install Playwright Python package",
                    confidence="high",
                    command=f"{sys.executable} -m pip install playwright",
                    safe=False,
                )
            )

    if "config_error" in categories:
        cfg_path = _config_dir() / "config.json"
        if cfg_path.is_file():
            try:
                json.loads(cfg_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                actions.append(
                    RepairAction(
                        category="config_error",
                        action="backup_broken_config",
                        description="Back up invalid config.json (manual fix required)",
                        confidence="medium",
                        command=f"mv {cfg_path} {cfg_path}.bak",
                        safe=False,
                    )
                )
        actions.append(
            RepairAction(
                category="config_error",
                action="run_doctor",
                description="Run arka doctor for configuration guidance",
                confidence="high",
                command="arka doctor",
                safe=True,
            )
        )

    if "routing_misroute" in categories or "fish_python_parity" in categories:
        actions.append(
            RepairAction(
                category="routing_misroute",
                action="route_audit",
                description="Audit symbolic / fish / test routing parity (plan-only unless high confidence)",
                confidence="medium",
                command="arka route-audit",
                safe=True,
            )
        )

    if "mcp_error" in categories or "skill_crash" in categories:
        actions.append(
            RepairAction(
                category="mcp_error",
                action="run_doctor",
                description="Verify MCP server and skill dependencies",
                confidence="medium",
                command="arka doctor",
                safe=True,
            )
        )

    if not actions and not plan.issues:
        actions.append(
            RepairAction(
                category="general",
                action="run_doctor",
                description="No log issues detected — run doctor as baseline check",
                confidence="high",
                command="arka doctor",
                safe=True,
            )
        )

    plan.actions = actions
    return plan


def _blocked_fix(text: str) -> bool:
    return any(p.search(text) for p in _BLOCKED_FIX_RES)


def _apply_reset_llm_exhaustion() -> str:
    from arka.llm.fallback import reset_llm_exhaustion

    reset_llm_exhaustion()
    return "LLM exhaustion cache cleared"


def _apply_install_playwright(*, yes: bool) -> tuple[bool, str]:
    if not yes:
        return False, "skipped — requires --yes to install packages"
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "playwright"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()[:500]
    if proc.returncode != 0:
        return False, f"pip install failed ({proc.returncode}): {out}"
    return True, out or "playwright installed"


def _apply_run_doctor() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "arka.cli", "doctor"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    lines = [ln for ln in out.splitlines() if ln.strip()][:12]
    summary = "\n".join(lines)
    return proc.returncode == 0, summary[:800]


def _apply_route_audit() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "arka.cli", "route-audit"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, out[:800]


def apply_repair_plan(
    plan: RepairPlan,
    *,
    apply: bool = False,
    yes: bool = False,
    min_confidence: str = "high",
) -> RepairPlan:
    """Apply safe fixes when --apply is set."""
    conf_rank = {"high": 3, "medium": 2, "low": 1}
    min_rank = conf_rank.get(min_confidence, 3)

    for action in plan.actions:
        if _blocked_fix(action.command) or _blocked_fix(action.description):
            action.result = "blocked — secrets or env files"
            continue
        if not apply:
            action.result = "plan-only"
            continue
        if conf_rank.get(action.confidence, 0) < min_rank:
            action.result = f"skipped — confidence {action.confidence} < {min_confidence}"
            continue
        if not action.safe and not yes:
            action.result = "skipped — requires --yes for non-safe action"
            continue

        try:
            if action.action == "reset_llm_exhaustion":
                action.result = _apply_reset_llm_exhaustion()
                action.applied = True
            elif action.action == "install_playwright":
                ok, msg = _apply_install_playwright(yes=yes)
                action.applied = ok
                action.result = msg
            elif action.action == "run_doctor":
                ok, msg = _apply_run_doctor()
                action.applied = ok
                action.result = msg
            elif action.action == "route_audit":
                ok, msg = _apply_route_audit()
                action.applied = ok
                action.result = msg
            elif action.action == "backup_broken_config":
                action.result = "skipped — manual backup only (destructive)"
            else:
                action.result = f"unknown action: {action.action}"
        except Exception as exc:
            action.result = f"error: {exc}"

    if apply:
        record_repair(actions=plan.actions, apply=True)
    return plan


def plan_to_dict(plan: RepairPlan, *, include_results: bool = False) -> dict[str, Any]:
    """Serialize a repair plan for JSON/MCP responses."""
    payload: dict[str, Any] = {
        "analyzed_at": plan.analyzed_at,
        "log_paths": plan.log_paths,
        "issues": [
            {
                "category": i.category,
                "message": i.message,
                "source": i.source,
                "confidence": i.confidence,
                "evidence": i.evidence,
                "ts": i.ts,
            }
            for i in plan.issues
        ],
        "actions": [
            {
                "category": a.category,
                "action": a.action,
                "description": a.description,
                "confidence": a.confidence,
                "command": a.command,
                "safe": a.safe,
                **(
                    {"applied": a.applied, "result": a.result}
                    if include_results
                    else {}
                ),
            }
            for a in plan.actions
        ],
    }
    return payload


def build_propose_prompt(plan: RepairPlan) -> str:
    """Human-readable approval prompt for MCP clients and CLI."""
    issue_count = len(plan.issues)
    if not plan.actions:
        if issue_count == 0:
            return "No issues detected. Run doctor as a baseline check."
        return (
            f"Found {issue_count} issue{'s' if issue_count != 1 else ''}. "
            "No automatic fixes available — review logs manually."
        )

    numbered = "; ".join(f"{idx}) {action.description}" for idx, action in enumerate(plan.actions, 1))
    return (
        f"Found {issue_count} issue{'s' if issue_count != 1 else ''}. "
        f"Recommended fixes: {numbered}. Approve with heal action."
    )


def summarize_repair_for_verify(plan: RepairPlan) -> str:
    """Compact repair summary for judge-model verification."""
    lines = [f"Issues found: {len(plan.issues)}"]
    for issue in plan.issues[:8]:
        lines.append(f"- [{issue.category}] {issue.message[:120]}")
    applied = [a for a in plan.actions if a.applied]
    skipped = [a for a in plan.actions if not a.applied and a.result]
    lines.append(f"Actions applied: {len(applied)}/{len(plan.actions)}")
    for action in applied:
        preview = (action.result or "ok").replace("\n", " ")[:160]
        lines.append(f"- applied {action.action}: {preview}")
    for action in skipped[:5]:
        lines.append(f"- skipped {action.action}: {action.result[:120]}")
    return "\n".join(lines)


def repair_success(plan: RepairPlan) -> bool:
    """Heuristic: did at least one action apply without hard errors?"""
    if not plan.actions:
        return len(plan.issues) == 0
    applied = [a for a in plan.actions if a.applied]
    if applied:
        return True
    hard_fail = [
        a
        for a in plan.actions
        if a.result.startswith(("error", "blocked"))
        or (a.result.startswith("skipped") and "requires" in a.result.lower())
    ]
    return not hard_fail and len(plan.issues) == 0


def verify_repair_result(
    plan: RepairPlan,
    *,
    force: bool = True,
    blocking: bool = True,
) -> dict[str, Any]:
    """Run judge-model quality check on a repair outcome."""
    from arka.core.output_verify import (
        maybe_verify_output,
        timing_to_dict,
        verdict_to_dict,
        ResponseTimer,
    )

    timer = ResponseTimer()
    question = (
        "Did the Arka self-repair operation succeed? "
        "Evaluate whether the applied fixes address the detected issues "
        "and whether the repair output is clear and actionable."
    )
    answer = summarize_repair_for_verify(plan)
    context = format_plan_output(plan, apply=True)
    verdict = maybe_verify_output(
        question,
        answer,
        context=context,
        blocking=blocking,
        force=force,
    )
    timing = timer.finish()
    success = repair_success(plan)
    if verdict is not None:
        success = success and verdict.passed
    return {
        "success": success,
        "applied_count": sum(1 for a in plan.actions if a.applied),
        "issue_count": len(plan.issues),
        "verdict": verdict_to_dict(verdict),
        "timing": timing_to_dict(timing),
        "verify_ran": verdict is not None,
    }


def run_mcp_self_repair(
    action: str,
    *,
    apply: bool = False,
    yes: bool = False,
    min_confidence: str = "high",
    verify: bool | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """MCP-first live healing entry point."""
    act = (action or "analyze").strip().lower()

    if act == "status":
        data = load_memory()
        repairs = data.get("repairs") or []
        return {
            "action": "status",
            "count": len(repairs),
            "last": repairs[-1] if repairs else None,
            "memory_path": str(memory_path()),
        }

    plan = build_repair_plan(analyze_logs(limit=limit))

    if act in ("analyze", "plan"):
        return {
            "action": "analyze",
            **plan_to_dict(plan),
            "propose_prompt": build_propose_prompt(plan),
            "next": "Call action=propose for approval text, or action=heal with apply=true.",
        }

    if act == "propose":
        return {
            "action": "propose",
            **plan_to_dict(plan),
            "prompt": build_propose_prompt(plan),
            "next": "Approve with action=heal and apply=true (yes=true for package installs).",
        }

    if act in ("heal", "fix", "apply", "run"):
        apply_flag = apply or act in ("heal", "fix", "apply", "run")
        if apply_flag:
            plan = apply_repair_plan(
                plan,
                apply=True,
                yes=yes,
                min_confidence=min_confidence,
            )
        should_verify = verify if verify is not None else apply_flag
        payload: dict[str, Any] = {
            "action": "heal" if act == "heal" else act,
            "apply": apply_flag,
            **plan_to_dict(plan, include_results=True),
            "propose_prompt": build_propose_prompt(plan),
        }
        if should_verify:
            payload["verification"] = verify_repair_result(plan, force=True, blocking=True)
            payload["exit_code"] = 0 if payload["verification"]["success"] else 1
        else:
            applied = sum(1 for a in plan.actions if a.applied)
            payload["exit_code"] = 0 if applied or not apply_flag else 1
        return payload

    if act == "verify":
        return {
            "action": "verify",
            **plan_to_dict(plan, include_results=True),
            "verification": verify_repair_result(plan, force=True, blocking=True),
        }

    raise ValueError("action must be analyze, propose, heal, fix, verify, or status")


def run_live_self_repair(
    *,
    yes: bool = False,
    min_confidence: str = "high",
    json_output: bool = False,
) -> int:
    """Full live workflow: analyze → propose → heal → verify."""
    plan = build_repair_plan(analyze_logs())
    prompt = build_propose_prompt(plan)
    plan = apply_repair_plan(plan, apply=True, yes=yes, min_confidence=min_confidence)
    verification = verify_repair_result(plan, force=True, blocking=True)

    if json_output:
        print(
            json.dumps(
                {
                    "workflow": "live",
                    "propose_prompt": prompt,
                    **plan_to_dict(plan, include_results=True),
                    "verification": verification,
                },
                indent=2,
            )
        )
    else:
        print(format_plan_output(plan, apply=True))
        print("")
        print(f"Proposed: {prompt}")
        print("")
        v = verification.get("verdict") or {}
        if verification.get("verify_ran") and v:
            print(
                f"Verify: quality {v.get('overall', '?')}/5 "
                f"({'pass' if v.get('passed') else 'fail'}) — {v.get('summary', '')}"
            )
            timing = verification.get("timing") or {}
            if timing.get("total_ms") is not None:
                print(f"Timing: total {timing['total_ms']:.0f}ms")
        else:
            print("Verify: skipped (judge model unavailable)")

    return 0 if verification.get("success") else 1


def format_plan_output(plan: RepairPlan, *, apply: bool) -> str:
    lines = ["━━━ Arka Self-Repair ━━━"]
    if plan.log_paths:
        lines.append(f"Logs: {', '.join(Path(p).name for p in plan.log_paths[:3])}")
    lines.append(f"Issues: {len(plan.issues)}")
    lines.append("")

    if plan.issues:
        by_cat: dict[str, int] = {}
        for issue in plan.issues:
            by_cat[issue.category] = by_cat.get(issue.category, 0) + 1
        for cat, count in sorted(by_cat.items()):
            lines.append(f"  • {cat}: {count}")
        lines.append("")
        for issue in plan.issues[:8]:
            mark = {"high": "✗", "medium": "○", "low": "·"}.get(issue.confidence, "○")
            lines.append(f"{mark} [{issue.category}] {issue.message[:100]}")
        if len(plan.issues) > 8:
            lines.append(f"  … and {len(plan.issues) - 8} more")
        lines.append("")

    lines.append(f"Repair actions: {len(plan.actions)}")
    for action in plan.actions:
        mark = "✓" if action.applied else ("→" if apply else "○")
        conf = action.confidence
        lines.append(f"{mark} [{conf}] {action.description}")
        if action.command:
            lines.append(f"    cmd: {action.command}")
        if action.result:
            preview = action.result.replace("\n", " ")[:120]
            lines.append(f"    result: {preview}")

    lines.append("")
    if apply:
        applied = sum(1 for a in plan.actions if a.applied)
        lines.append(f"Applied {applied}/{len(plan.actions)} action(s)")
    else:
        lines.append("Next: arka self repair --apply")
        lines.append("      arka self repair --apply --yes   # include package installs")
    return "\n".join(lines)


def run_self_repair(
    *,
    apply: bool = False,
    yes: bool = False,
    json_output: bool = False,
    min_confidence: str = "high",
) -> int:
    plan = build_repair_plan(analyze_logs())
    plan = apply_repair_plan(plan, apply=apply, yes=yes, min_confidence=min_confidence)

    if json_output:
        payload = {
            "analyzed_at": plan.analyzed_at,
            "log_paths": plan.log_paths,
            "issues": [
                {
                    "category": i.category,
                    "message": i.message,
                    "source": i.source,
                    "confidence": i.confidence,
                    "ts": i.ts,
                }
                for i in plan.issues
            ],
            "actions": [
                {
                    "category": a.category,
                    "action": a.action,
                    "description": a.description,
                    "confidence": a.confidence,
                    "command": a.command,
                    "applied": a.applied,
                    "result": a.result,
                }
                for a in plan.actions
            ],
            "apply": apply,
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(format_plan_output(plan, apply=apply))
    if not apply:
        record_repair(actions=plan.actions, apply=False, notes="analyze")
    if apply:
        failed = [a for a in plan.actions if not a.applied and a.result.startswith(("error", "skipped"))]
        return 1 if failed and not any(a.applied for a in plan.actions) else 0
    return 0


def route_command(text: str) -> str:
    """NL → self_repair skill line."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""

    if re.match(r"(?i)^(?:arka\s+)?self\s+repair\s+(?:status|memory)\s*$", raw):
        sub = re.search(r"(status|memory)\s*$", raw, re.I)
        return f"self_repair {sub.group(1).lower()}" if sub else "self_repair status"

    if re.match(r"(?i)^(?:arka\s+)?self_repair\s+(?:analyze|fix|status|memory|propose|heal|verify|live)\s*$", raw):
        sub = re.search(r"(analyze|fix|status|memory|propose|heal|verify|live)\s*$", raw, re.I)
        return f"self_repair {sub.group(1).lower()}" if sub else "self_repair analyze"

    if re.match(r"(?i)^(?:arka\s+)?self\s+repair\s+(?:propose|heal|verify|live)\s*$", raw):
        sub = re.search(r"(propose|heal|verify|live)\s*$", raw, re.I)
        return f"self_repair {sub.group(1).lower()}" if sub else "self_repair analyze"

    triggers = (
        r"(?i)\b(?:self\s+repair|self_repair|auto\s+fix\s+arka|fix\s+arka\s+(?:logs|errors)|"
        r"repair\s+arka|auto\s+repair\s+arka|analyze\s+arka\s+logs|fix\s+arka\s+logs)\b"
    )
    if not re.search(triggers, raw):
        return ""

    apply = bool(re.search(r"(?i)(?:--apply\b|\bapply fixes?\b)", raw))
    yes = bool(re.search(r"(?i)\b(?:--yes|-y)\b", raw))
    line = "self_repair"
    if apply:
        line += " fix"
    else:
        line += " analyze"
    if apply:
        line += " --apply"
    if yes:
        line += " --yes"
    return line


def main(argv: list[str] | None = None) -> int:
    from arka.paths import load_env_file

    load_env_file()

    parser = argparse.ArgumentParser(description="Arka self-repair — analyze logs and auto-fix")
    sub = parser.add_subparsers(dest="cmd")

    for name, help_text in (
        ("analyze", "Analyze logs and produce repair plan (default)"),
        ("propose", "Show human-readable fix approval prompt"),
        ("fix", "Analyze and apply safe fixes (--apply implied)"),
        ("heal", "Apply fixes and verify outcome quality"),
        ("verify", "Verify current repair plan / last outcome quality"),
        ("live", "Full live workflow: analyze, heal, verify"),
        ("status", "Show recent repair history"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--apply", action="store_true", help="Apply safe fixes")
        p.add_argument("--yes", "-y", action="store_true", help="Confirm package installs")
        p.add_argument("--json", action="store_true", help="JSON output")
        p.add_argument(
            "--min-confidence",
            choices=["high", "medium", "low"],
            default="high",
            help="Minimum confidence for auto-fix",
        )
        if name in ("heal", "live", "verify"):
            p.add_argument(
                "--no-verify",
                action="store_true",
                help="Skip post-fix quality verification",
            )

    p_route = sub.add_parser("route", help="NL routing helper")
    p_route.add_argument("text", nargs="+")

    p_mem = sub.add_parser("memory", help="Show repair history")
    p_mem.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    cmd = args.cmd

    if cmd == "route":
        line = route_command(" ".join(args.text))
        if line:
            print(line)
            return 0
        return 1

    if cmd == "memory":
        data = load_memory()
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        repairs = list(reversed(data.get("repairs") or []))[:15]
        if not repairs:
            print("No self-repair history yet.")
            return 0
        print("Recent self-repair runs:\n")
        for entry in repairs:
            at = entry.get("at", "")
            apply_flag = "apply" if entry.get("apply") else "analyze"
            actions = entry.get("actions") or []
            applied = sum(1 for a in actions if a.get("applied"))
            print(f"  [{apply_flag}] {at} — {applied}/{len(actions)} applied")
        return 0

    if cmd == "status":
        data = load_memory()
        repairs = data.get("repairs") or []
        print(f"memory: {memory_path()}")
        print(f"repairs recorded: {len(repairs)}")
        if repairs:
            last = repairs[-1]
            print(f"last run: {last.get('at', '?')} ({'apply' if last.get('apply') else 'analyze'})")
        return 0

    apply = bool(getattr(args, "apply", False) or cmd in ("fix", "heal", "live"))
    if cmd == "propose":
        plan = build_repair_plan(analyze_logs())
        prompt = build_propose_prompt(plan)
        if args.json:
            print(json.dumps({"prompt": prompt, **plan_to_dict(plan)}, indent=2))
        else:
            print(prompt)
            print("")
            print(format_plan_output(plan, apply=False))
        record_repair(actions=plan.actions, apply=False, notes="propose")
        return 0

    if cmd == "verify":
        plan = build_repair_plan(analyze_logs())
        verification = verify_repair_result(plan, force=True, blocking=True)
        if args.json:
            print(
                json.dumps(
                    {**plan_to_dict(plan), "verification": verification},
                    indent=2,
                )
            )
        else:
            print(format_plan_output(plan, apply=False))
            v = verification.get("verdict") or {}
            if verification.get("verify_ran") and v:
                print(f"\nVerify: {v.get('summary', '')} (overall {v.get('overall', '?')}/5)")
            else:
                print("\nVerify: judge model unavailable")
        return 0 if verification.get("success") else 1

    if cmd == "heal":
        plan = build_repair_plan(analyze_logs())
        plan = apply_repair_plan(
            plan,
            apply=True,
            yes=bool(args.yes),
            min_confidence=str(args.min_confidence),
        )
        payload: dict[str, Any] = plan_to_dict(plan, include_results=True)
        if not getattr(args, "no_verify", False):
            payload["verification"] = verify_repair_result(plan, force=True, blocking=True)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(format_plan_output(plan, apply=True))
            if payload.get("verification"):
                v = payload["verification"].get("verdict") or {}
                print(f"\nVerify: {v.get('summary', '')}")
        success = payload.get("verification", {}).get("success", repair_success(plan))
        return 0 if success else 1

    if cmd == "live":
        return run_live_self_repair(
            yes=bool(args.yes),
            min_confidence=str(args.min_confidence),
            json_output=bool(args.json),
        )

    return run_self_repair(
        apply=apply,
        yes=bool(getattr(args, "yes", False)),
        json_output=bool(getattr(args, "json", False)),
        min_confidence=str(getattr(args, "min_confidence", "high")),
    )


if __name__ == "__main__":
    raise SystemExit(main())
