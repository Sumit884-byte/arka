"""Connect the Arka CLI to Agent Hub shared context (memory, MCP, skills)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from arka.paths import config_dir, load_env_file

    load_env_file()
except ImportError:

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"

    def load_env_file() -> None:
        pass


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def marker_path() -> Path:
    return config_dir() / "cli-connector.json"


def is_connected() -> bool:
    flag = os.environ.get("ARKA_CLI_CONNECTOR", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    path = marker_path()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("connected"))
    except (OSError, json.JSONDecodeError):
        return False


def context_md_path() -> Path:
    raw = os.environ.get("ARKA_CONTEXT_MD", "").strip()
    if raw:
        return Path(raw).expanduser()
    try:
        from arka.integrations.agent_hub import hub_context_md_path

        return hub_context_md_path()
    except ImportError:
        return config_dir() / "hub" / "memory" / "context.md"


def launch_env_path() -> Path:
    try:
        from arka.integrations.agent_hub import hub_launch_env_path

        return hub_launch_env_path()
    except ImportError:
        return config_dir() / "hub" / "launch.env"


def _write_marker(env: dict[str, str]) -> Path:
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "connected": True,
        "connected_at": _iso_now(),
        "context_md": env.get("ARKA_CONTEXT_MD", str(context_md_path())),
        "hub_dir": env.get("ARKA_HUB_DIR", ""),
        "mcp_config": env.get("ARKA_MCP_CONFIG", ""),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def apply_launch_env(agent_key: str = "cli", *, overwrite: bool = False) -> dict[str, str]:
    """Apply Agent Hub launch env vars to the current process."""
    try:
        from arka.integrations.agent_hub import launch_env, write_launch_env_file

        write_launch_env_file(agent_key)
        env = launch_env(agent_key)
    except ImportError as exc:
        raise RuntimeError(f"agent_hub unavailable: {exc}") from exc

    for key, value in env.items():
        if overwrite or key not in os.environ:
            os.environ[key] = value
    os.environ["ARKA_CLI_CONNECTOR"] = "1"
    return env


def connect(*, sync: bool = True, unify: bool = False) -> dict[str, Any]:
    """Sync hub exports and wire this CLI session to shared context."""
    sync_result: dict[str, Any] = {}
    if sync:
        try:
            from arka.integrations.agent_hub import sync_all, write_launch_env_file

            sync_result = sync_all(unify=unify)
            write_launch_env_file("cli")
        except ImportError as exc:
            return {"ok": False, "error": f"agent_hub unavailable: {exc}"}

    try:
        env = apply_launch_env("cli", overwrite=True)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "sync": sync_result}

    marker = _write_marker(env)
    ctx = context_md_path()
    return {
        "ok": True,
        "connected": True,
        "sync": sync_result,
        "marker": str(marker),
        "context_md": str(ctx),
        "context_exists": ctx.is_file(),
        "launch_env": str(launch_env_path()),
        "env": {k: env[k] for k in sorted(env)},
    }


def disconnect() -> dict[str, Any]:
    os.environ.pop("ARKA_CLI_CONNECTOR", None)
    path = marker_path()
    if path.is_file():
        path.unlink(missing_ok=True)
    return {"ok": True, "connected": False}


def status_payload() -> dict[str, Any]:
    ctx = context_md_path()
    launch = launch_env_path()
    marker = marker_path()
    marker_data: dict[str, Any] = {}
    if marker.is_file():
        try:
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            marker_data = {}
    try:
        from arka.integrations.agent_hub import hub_dir, hub_memory_dir, hub_mcp_path

        hub = str(hub_dir())
        memory = str(hub_memory_dir())
        mcp = str(hub_mcp_path())
    except ImportError:
        hub = os.environ.get("ARKA_HUB_DIR", "")
        memory = os.environ.get("ARKA_MEMORY_DIR", "")
        mcp = os.environ.get("ARKA_MCP_CONFIG", "")

    return {
        "connected": is_connected(),
        "context_md": str(ctx),
        "context_exists": ctx.is_file(),
        "launch_env": str(launch),
        "launch_env_exists": launch.is_file(),
        "marker": str(marker),
        "marker_exists": marker.is_file(),
        "connected_at": marker_data.get("connected_at"),
        "hub_dir": hub,
        "memory_dir": memory,
        "mcp_config": mcp,
    }


def doctor_payload() -> dict[str, Any]:
    status = status_payload()
    checks: list[dict[str, Any]] = []

    checks.append(
        {
            "name": "connected",
            "ok": status["connected"],
            "detail": "run: arka connector connect",
        }
    )
    checks.append(
        {
            "name": "context_md",
            "ok": status["context_exists"],
            "detail": str(status["context_md"]),
        }
    )
    checks.append(
        {
            "name": "launch_env",
            "ok": status["launch_env_exists"],
            "detail": str(status["launch_env"]),
        }
    )
    mcp_path = Path(str(status.get("mcp_config") or ""))
    checks.append(
        {
            "name": "hub_mcp",
            "ok": mcp_path.is_file(),
            "detail": str(mcp_path),
        }
    )
    try:
        from arka.integrations.mcp_server import ensure_arka_self_in_config

        checks.append(
            {
                "name": "arka_self_mcp",
                "ok": ensure_arka_self_in_config(),
                "detail": "Arka MCP server registered in hub config",
            }
        )
    except ImportError:
        checks.append(
            {
                "name": "arka_self_mcp",
                "ok": False,
                "detail": "mcp_server unavailable",
            }
        )

    ok_count = sum(1 for row in checks if row.get("ok"))
    return {
        "ok": ok_count == len(checks),
        "checks": checks,
        "summary": f"{ok_count}/{len(checks)} checks passed",
    }


def shared_context_block(goal: str = "", *, limit_chars: int = 2500) -> str:
    """Return Agent Hub shared context for injection into CLI agent loops."""
    if not is_connected() and not os.environ.get("ARKA_CONTEXT_MD"):
        return ""

    path = context_md_path()
    if not path.is_file():
        try:
            from arka.integrations.agent_hub import sync_memory

            sync_memory()
        except ImportError:
            pass
        if not path.is_file():
            return ""

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return ""

    goal = (goal or "").strip()
    if goal:
        terms = [w.lower() for w in re.findall(r"[a-z0-9]{3,}", goal)]
        if terms:
            lines = text.splitlines()
            hits: list[str] = []
            for line in lines:
                low = line.lower()
                if line.startswith("#"):
                    continue
                if any(term in low for term in terms):
                    hits.append(line.strip())
            if hits:
                text = "\n".join(hits[:40])
            else:
                text = "\n".join(lines[:60])

    if len(text) > limit_chars:
        text = text[: limit_chars - 3].rstrip() + "..."
    return "Shared context (Agent Hub):\n" + text


def shell_init(*, shell: str = "auto") -> str:
    launch = launch_env_path()
    chosen = shell.strip().lower()
    if chosen == "auto":
        chosen = "fish" if "fish" in os.environ.get("SHELL", "").lower() else "bash"

    lines = [
        "# Arka CLI connector — source shared Agent Hub context in your shell",
        f"# Generated for: {chosen}",
        "",
    ]
    if chosen == "fish":
        lines.extend(
            [
                f"if test -f '{launch}'",
                f"    bass source '{launch}' 2>/dev/null; or begin",
                f"        for line in (grep -v '^#' '{launch}' | grep '^export ')",
                "            set -l parts (string split -m1 '=' (string sub -s 8 $line))",
                "            if test (count $parts) -eq 2",
                "                set -gx $parts[1] (string trim -c '\"' $parts[2])",
                "            end",
                "        end",
                "    end",
                "end",
                "set -gx ARKA_CLI_CONNECTOR 1",
            ]
        )
    else:
        lines.extend(
            [
                f"if [ -f '{launch}' ]; then",
                "  set -a",
                f"  . '{launch}'",
                "  set +a",
                "fi",
                "export ARKA_CLI_CONNECTOR=1",
            ]
        )
    lines.append("")
    lines.append("# Then run: arka connector connect")
    return "\n".join(lines)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def suggest_payload() -> dict[str, Any]:
    """Steps to connect the Arka CLI to Agent Hub shared context."""
    status = status_payload()
    shell = "fish" if "fish" in os.environ.get("SHELL", "").lower() else "bash"
    shell_file = "~/.config/fish/config.fish" if shell == "fish" else "~/.bashrc"
    steps = [
        {
            "step": 1,
            "command": "arka agent_hub sync",
            "purpose": "Export shared memory, MCP config, and skills to the hub",
        },
        {
            "step": 2,
            "command": "arka connector connect",
            "purpose": "Attach this terminal session to hub context (memory + MCP)",
        },
        {
            "step": 3,
            "command": "arka connector doctor",
            "purpose": "Verify context.md, launch.env, and hub MCP are wired",
        },
        {
            "step": 4,
            "command": f"arka connector shell-init --shell {shell} >> {shell_file}",
            "purpose": "Persist connector env across new shells (optional)",
        },
    ]
    if status.get("connected"):
        steps.append(
            {
                "step": 5,
                "command": "arka connector context",
                "purpose": "Preview shared context already available in this session",
            }
        )
    else:
        steps.append(
            {
                "step": 5,
                "command": "arka mcp call arka arka_connector --args '{\"action\":\"connect\"}'",
                "purpose": "Same connect flow from Cursor/Claude via Arka MCP",
            }
        )
    return {
        "connected": status.get("connected"),
        "context_exists": status.get("context_exists"),
        "recommended_first": "arka connector connect",
        "shell": shell,
        "steps": steps,
        "status": status,
    }


def cmd_suggest(args: argparse.Namespace) -> int:
    payload = suggest_payload()
    if args.json:
        _print_json(payload)
        return 0
    print("Connect the Arka CLI to Agent Hub shared context:\n")
    for row in payload["steps"]:
        print(f"  {row['step']}. {row['command']}")
        print(f"     {row['purpose']}\n")
    if payload["connected"]:
        print("Status: already connected in this session.")
    else:
        print("Status: not connected — start with `arka connector connect`.")
        if not args.no_prompt and sys.stdin.isatty():
            if input("Run connect now? [y/N]: ").strip().lower() in {"y", "yes"}:
                return cmd_connect(argparse.Namespace(no_sync=False, unify=False, json=False))
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    payload = connect(sync=not args.no_sync, unify=bool(args.unify))
    if args.json:
        _print_json(payload)
        return 0 if payload.get("ok") else 1
    if not payload.get("ok"):
        print(str(payload.get("error") or "connect failed"), file=sys.stderr)
        return 1
    print("CLI connector: connected to Agent Hub shared context")
    print(f"context\t{payload.get('context_md')}")
    print(f"launch_env\t{payload.get('launch_env')}")
    if not payload.get("context_exists"):
        print("hint\trun `arka agent_hub sync` if context.md is missing", file=sys.stderr)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    payload = status_payload()
    if args.json:
        _print_json(payload)
        return 0
    print(f"connected\t{payload['connected']}")
    print(f"context_md\t{payload['context_md']}")
    print(f"launch_env\t{payload['launch_env']}")
    print(f"hub_dir\t{payload['hub_dir']}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    goal = " ".join(args.goal or [])
    block = shared_context_block(goal, limit_chars=int(args.limit))
    if args.json:
        _print_json({"goal": goal, "context": block, "chars": len(block)})
        return 0
    if not block:
        print("No shared context available. Run: arka connector connect", file=sys.stderr)
        return 1
    print(block)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    payload = doctor_payload()
    if args.json:
        _print_json(payload)
        return 0 if payload.get("ok") else 1
    for row in payload.get("checks") or []:
        status = "ok" if row.get("ok") else "fail"
        print(f"{row.get('name')}\t{status}\t{row.get('detail', '')}")
    print(f"summary\t{payload.get('summary')}")
    return 0 if payload.get("ok") else 1


def cmd_shell_init(args: argparse.Namespace) -> int:
    print(shell_init(shell=str(args.shell or "auto")), end="")
    return 0


def cmd_disconnect(_args: argparse.Namespace) -> int:
    payload = disconnect()
    print("CLI connector: disconnected")
    if payload.get("ok"):
        return 0
    return 1


def nl_to_argv(cmd: str) -> list[str] | None:
    clean = (cmd or "").strip()
    if not clean:
        return None
    lower = clean.lower()

    if re.search(r"(?i)\b(?:agent\s+hub|arka\s+hub)\b.*\b(?:sync|refresh|update|unify|doctor|detect|status|list|launch)\b", clean):
        return None
    if re.search(r"(?i)\b(?:sync|refresh|update|unify|detect|launch)\b.*\b(?:agent\s+hub|arka\s+hub)\b", clean):
        return None

    aliases = {
        "cli connector": ["connect"],
        "connector connect": ["connect"],
        "connect cli": ["connect"],
        "connect shared context": ["connect"],
        "wire cli to hub": ["connect"],
        "attach terminal to shared context": ["connect"],
        "connector status": ["status"],
        "connector doctor": ["doctor"],
        "connector disconnect": ["disconnect"],
        "show shared context": ["context"],
        "suggest cli to connect": ["suggest"],
        "how to connect cli": ["suggest"],
    }
    if lower in aliases:
        return aliases[lower]

    if re.search(r"(?i)\b(?:suggest|show|how)\b.*\b(?:cli|terminal|shell)\b.*\b(?:connect|connector|shared\s+context|hub)\b", clean):
        return ["suggest"]

    if re.search(r"(?i)\b(?:cli|terminal|shell|command\s+line)\b.*\b(?:connector|shared\s+context|hub\s+context)\b", clean):
        if re.search(r"(?i)\b(?:status|state)\b", clean):
            return ["status"]
        if re.search(r"(?i)\b(?:doctor|health|check|verify)\b", clean):
            return ["doctor"]
        if re.search(r"(?i)\b(?:disconnect|off|disable)\b", clean):
            return ["disconnect"]
        if re.search(r"(?i)\b(?:show|preview|read|load|use|display)\b.*\b(?:context|memory)\b", clean):
            goal = re.sub(r"(?i)^.*\b(?:context|memory)\b\s+(?:for\s+)?", "", clean).strip()
            return ["context", goal] if goal else ["context"]
        if re.search(r"(?i)\b(?:shell|bash|fish|zsh)\b.*\b(?:init|setup|hook)\b", clean):
            shell = "fish" if re.search(r"(?i)\bfish\b", clean) else "bash"
            return ["shell-init", "--shell", shell]
        return ["connect"]

    if re.search(r"(?i)\b(?:connect|wire|link|attach)\b.*\b(?:shared\s+context|hub\s+context|cross[- ]agent)\b", clean):
        if re.search(r"(?i)\b(?:status|state)\b", clean):
            return ["status"]
        if re.search(r"(?i)\b(?:unify|merge)\b", clean):
            return ["connect", "--unify"]
        return ["connect"]

    if re.search(r"(?i)\b(?:shared\s+context|hub\s+memory)\b.*\b(?:cli|terminal|shell|command\s+line)\b", clean):
        return ["connect"]

    if re.search(r"(?i)\b(?:use|load|read|show|preview|display)\b.*\bshared\s+context\b", clean):
        goal = re.sub(r"(?i)^.*\bshared\s+context\b\s+(?:for\s+)?", "", clean).strip()
        return ["context", goal] if goal else ["context"]

    if re.search(r"(?i)\b(?:mac|macos|windows|linux|win32|unix)\b.*\b(?:shared\s+context|cli\s+connector)\b", clean):
        return ["connect"]

    return None


def route_command(text: str) -> str:
    argv = nl_to_argv(text)
    if not argv:
        return ""
    return "connector " + " ".join(shlex.quote(a) for a in argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arka connector",
        description="Connect the Arka CLI to Agent Hub shared context",
    )
    sub = parser.add_subparsers(dest="command")

    connect_p = sub.add_parser("connect", help="Sync hub and attach shared context to this CLI session")
    connect_p.add_argument("--no-sync", action="store_true", help="Skip agent_hub sync before connect")
    connect_p.add_argument("--unify", action="store_true", help="Run agent_hub sync --unify before connect")
    connect_p.add_argument("--json", action="store_true")
    connect_p.set_defaults(func=cmd_connect)

    status_p = sub.add_parser("status", help="Show connector status")
    status_p.add_argument("--json", action="store_true")
    status_p.set_defaults(func=cmd_status)

    context_p = sub.add_parser("context", help="Print shared context block for a goal")
    context_p.add_argument("goal", nargs="*", help="Optional goal to filter context")
    context_p.add_argument("--limit", type=int, default=2500)
    context_p.add_argument("--json", action="store_true")
    context_p.set_defaults(func=cmd_context)

    doctor_p = sub.add_parser("doctor", help="Verify CLI connector setup")
    doctor_p.add_argument("--json", action="store_true")
    doctor_p.set_defaults(func=cmd_doctor)

    suggest_p = sub.add_parser("suggest", help="Show steps to connect CLI to Agent Hub")
    suggest_p.add_argument("--json", action="store_true")
    suggest_p.add_argument("--no-prompt", action="store_true", help="Do not offer to run connect")
    suggest_p.set_defaults(func=cmd_suggest)

    shell_p = sub.add_parser("shell-init", help="Print shell snippet to source hub launch.env")
    shell_p.add_argument("--shell", choices=("auto", "bash", "fish"), default="auto")
    shell_p.set_defaults(func=cmd_shell_init)

    sub.add_parser("disconnect", help="Clear connector marker for this machine").set_defaults(
        func=cmd_disconnect
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
