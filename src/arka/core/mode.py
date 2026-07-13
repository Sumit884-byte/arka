"""Arka operation modes — ask, plan, agent, debug, multitask."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from arka.paths import config_dir

if TYPE_CHECKING:
    from arka.router import Route

VALID_MODES = frozenset({"ask", "plan", "agent", "debug", "multitask"})
DEFAULT_MODE = "agent"

MODE_DESCRIPTIONS: dict[str, str] = {
    "ask": "Read-only Q&A — risky actions blocked; falls back to web answers",
    "plan": "Planning only — shows steps without executing skills",
    "agent": "Full agent — default behavior with skill execution",
    "debug": "Verbose routing and LLM attempt logging",
    "multitask": "Delegates work to background sub-agents when possible",
}

# Skills safe in ask mode (read-only / informational).
READONLY_SKILL_HEADS = frozenset(
    {
        "web_answer",
        "deep_web_answer",
        "calc",
        "hyperlocal_weather",
        "weather",
        "platform_howto",
        "help",
        "price_check",
        "select_model",
        "model_select",
        "best_model",
        "model_advisor",
        "flow",
        "fact_check",
        "ascii_art",
        "data_ask",
        "view_data",
        "competitions",
        "daily_brief",
        "platform_howto",
        "error_helper",
        "predictions",
        "sports_score",
        "route",
        "mode",
    }
)


def mode_file() -> os.PathLike[str]:
    return config_dir() / "mode"


def _normalize_mode(raw: str) -> str | None:
    mode = (raw or "").strip().lower()
    if mode in VALID_MODES:
        return mode
    return None


def is_debug_mode() -> bool:
    """True when verbose routing and LLM traces should be shown."""
    return get_mode() == "debug"


def get_mode() -> str:
    """Current operation mode (env ARKA_MODE overrides persisted file)."""
    env_mode = _normalize_mode(os.environ.get("ARKA_MODE", ""))
    if env_mode:
        return env_mode
    path = mode_file()
    try:
        if path.is_file():
            file_mode = _normalize_mode(path.read_text(encoding="utf-8"))
            if file_mode:
                return file_mode
    except OSError:
        pass
    return DEFAULT_MODE


def set_mode(mode: str) -> str:
    """Persist mode and apply side effects. Returns normalized mode."""
    normalized = _normalize_mode(mode)
    if not normalized:
        raise ValueError(f"Unknown mode: {mode!r} (choose: {', '.join(sorted(VALID_MODES))})")
    config_dir().mkdir(parents=True, exist_ok=True)
    path = mode_file()
    path.write_text(normalized + "\n", encoding="utf-8")
    os.environ["ARKA_MODE"] = normalized
    apply_mode_env(normalized)
    return normalized


def load_mode() -> str:
    """Load persisted mode into the environment (CLI startup)."""
    mode = get_mode()
    os.environ.setdefault("ARKA_MODE", mode)
    apply_mode_env(mode)
    return mode


def apply_mode_env(mode: str) -> None:
    if mode == "debug":
        os.environ.setdefault("LLM_VERBOSE", "1")
    if mode == "multitask":
        os.environ.setdefault("SUBAGENT_ENABLED", "1")


def describe_mode(mode: str | None = None) -> str:
    mode = mode or get_mode()
    return MODE_DESCRIPTIONS.get(mode, MODE_DESCRIPTIONS[DEFAULT_MODE])


def _skill_head(skill_line: str) -> str:
    return (skill_line or "").strip().split(maxsplit=1)[0] if skill_line.strip() else ""


def is_readonly_skill(skill_line: str) -> bool:
    return _skill_head(skill_line) in READONLY_SKILL_HEADS


def is_risky_skill(skill_line: str) -> bool:
    try:
        from arka.core.security import check_action

        result = check_action(skill_line)
        return result.status in ("block", "confirm")
    except ImportError:
        return False


def ask_mode_skill(skill_line: str, original_text: str) -> str:
    """Resolve which skill to run in ask mode (may redirect to web_answer)."""
    head = _skill_head(skill_line)
    if head == "help":
        return skill_line
    if is_readonly_skill(skill_line):
        return skill_line
    if head in ("web_answer", "deep_web_answer"):
        return skill_line
    topic = original_text.strip() or skill_line
    return f"web_answer {topic}"


def mode_allows_execution(skill_line: str, *, kind: str = "skill") -> tuple[bool, str]:
    """Whether the current mode permits executing this routed action."""
    mode = get_mode()
    if mode in ("agent", "debug"):
        return True, ""
    if mode == "plan":
        return False, "plan mode — execution disabled (use 'arka mode agent')"
    if mode == "ask":
        if kind == "shell":
            return False, "ask mode blocks shell commands"
        if is_risky_skill(skill_line):
            return False, "ask mode blocks risky actions"
        if not is_readonly_skill(skill_line):
            return False, "ask mode allows read-only skills only"
        return True, ""
    if mode == "multitask":
        return True, ""
    return True, ""


@dataclass(frozen=True)
class PlanStep:
    index: int
    action: str
    note: str = ""


def build_plan(text: str, route: Route | None) -> list[PlanStep]:
    steps: list[PlanStep] = []
    steps.append(PlanStep(1, f"Understand request: {text.strip()}"))
    if route:
        steps.append(
            PlanStep(
                2,
                f"Route via {route.source} → {route.skill}",
                note=f"kind={route.kind}",
            )
        )
        if route.kind == "shell":
            steps.append(PlanStep(3, f"Execute shell: {route.skill}", note="requires agent mode"))
        else:
            head = _skill_head(route.skill)
            steps.append(PlanStep(3, f"Run skill: {head}", note=route.skill))
            steps.append(PlanStep(4, "Verify output and report result"))
    else:
        steps.append(PlanStep(2, "No skill match — use web_answer / LLM chat"))
        steps.append(PlanStep(3, "Synthesize answer from search results"))
    return steps


def print_plan(text: str, route: Route | None) -> None:
    print(f"Plan mode — steps for: {text.strip()}\n")
    for step in build_plan(text, route):
        line = f"{step.index}. {step.action}"
        if step.note:
            line += f"  ({step.note})"
        print(line)
    print("\nSet 'arka mode agent' to execute.")


def print_debug_route(text: str, route: Route | None) -> None:
    print(f"[debug] mode={get_mode()} route_mode={os.environ.get('ROUTE_MODE', 'symbolic')}")
    print(f"[debug] request={text[:200]!r}")
    if route:
        print(f"[debug] skill={route.skill!r} source={route.source} kind={route.kind}")
    else:
        print("[debug] skill=(none — LLM chat fallback)")
    try:
        from arka.llm.cli import cmd_active_model

        class _Args:
            pass

        cmd_active_model(_Args())
    except Exception:
        pass


def try_multitask_delegate(text: str, route: Route | None = None) -> int | None:
    """Spawn a background sub-agent for non-trivial requests. Returns exit code or None."""
    if get_mode() != "multitask":
        return None
    if route is not None:
        head = _skill_head(route.skill)
        if head in READONLY_SKILL_HEADS or head == "help":
            return None
    try:
        from arka.integrations.subagent import spawn
    except ImportError:
        print("Multitask mode: subagent module unavailable.", file=sys.stderr)
        return 1
    data, err = spawn(text.strip(), background=True)
    if err:
        print(f"Multitask blocked: {err}", file=sys.stderr)
        return 1
    assert data is not None
    agent_id = data.get("id", "?")
    status = data.get("status", "pending")
    print(f"→ subagent {agent_id} [{status}]")
    print(f"  Task: {text.strip()[:120]}")
    print(f"  Check: arka subagent status {agent_id}")
    return 0


def route_mode_nl(cmd: str) -> str | None:
    """Symbolic NL → 'mode' or 'mode <name>'."""
    clean = cmd.strip()
    lower = clean.lower()
    if lower in ("mode", "show mode", "current mode", "what mode"):
        return "mode"
    if re.match(r"(?i)^(?:what|show|get)\s+(?:is\s+)?(?:the\s+)?(?:current\s+)?(?:operation\s+)?mode\b", lower):
        return "mode"
    m = re.match(r"(?i)^(?:set|switch|change)\s+(?:the\s+)?(?:operation\s+)?mode\s+(?:to\s+)?(\w+)\b", lower)
    if m:
        mode = m.group(1).lower()
        if mode in VALID_MODES:
            return f"mode {mode}"
    for mode in VALID_MODES:
        if re.match(rf"(?i)^(?:set\s+)?{re.escape(mode)}\s+mode$", lower):
            return f"mode {mode}"
        if re.match(rf"(?i)^(?:switch|change)\s+to\s+{re.escape(mode)}\s+mode$", lower):
            return f"mode {mode}"
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if args and args[0] == "mode":
        args = args[1:]

    if not args:
        return cmd_show()
    if args[0] in ("-h", "--help", "help"):
        print(
            "Usage: arka mode [ask|plan|agent|debug|multitask|list]\n"
            "\n"
            "Operation modes (persisted in ~/.config/arka/mode, overridable via ARKA_MODE):\n"
            "  ask       Read-only — block risky skills, prefer web answers\n"
            "  plan      Show step-by-step plan without executing\n"
            "  agent     Full agent behavior (default)\n"
            "  debug     Verbose routing and LLM logging\n"
            "  multitask Delegate to background sub-agents\n"
            "\n"
            "Examples:\n"
            "  arka mode\n"
            "  arka mode debug\n"
            "  arka mode list"
        )
        return 0

    if args[0] == "list":
        current = get_mode()
        for name in sorted(VALID_MODES):
            mark = " *" if name == current else ""
            print(f"{name:10}{mark}  {MODE_DESCRIPTIONS[name]}")
        return 0

    try:
        mode = set_mode(args[0])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Mode: {mode} — {describe_mode(mode)}")
    print(f"Saved: {mode_file()}")
    return 0


def cmd_show() -> int:
    mode = get_mode()
    print(f"Mode: {mode}")
    print(describe_mode(mode))
    print(f"File: {mode_file()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
