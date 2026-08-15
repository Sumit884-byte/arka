#!/usr/bin/env python3
"""Generic login autostart for any service — register commands or scripts, install via launchd/systemd."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from arka.paths import cache_dir
except ImportError:
    cache_dir = lambda: Path.home() / ".cache" / "fish-agent"  # noqa: E731

_KNOWN_CMDS = frozenset(
    {"add", "list", "install", "uninstall", "remove", "status", "run", "help", "parse"}
)
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,48}$")


def _registry_file() -> Path:
    return cache_dir() / "service_autostart.json"


def _load_json(path: Path, default: object) -> object:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return default


def _save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_registry() -> list[dict[str, Any]]:
    raw = _load_json(_registry_file(), [])
    return raw if isinstance(raw, list) else []


def _save_registry(rows: list[dict[str, Any]]) -> None:
    _save_json(_registry_file(), rows)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug or not _ID_RE.match(slug):
        slug = "svc-" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return slug[:49]


def _validate_id(service_id: str) -> str:
    sid = service_id.strip().lower()
    if not _ID_RE.match(sid):
        raise ValueError(f"Invalid service id {service_id!r} — use lowercase letters, digits, - or _")
    return sid


def _parse_llm_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start : end + 1])
        else:
            raise ValueError("LLM did not return valid JSON for service definition")
    return data if isinstance(data, dict) else {}


def infer_service_from_description(
    description: str,
    *,
    service_id: str = "",
    name: str = "",
) -> dict[str, str]:
    """Infer command/workdir/env from a natural-language service description."""
    desc = description.strip()
    if not desc:
        raise ValueError("description is required")
    system = (
        "You infer login autostart service definitions from user descriptions. "
        "Return ONLY valid JSON with keys: command (required shell command string), "
        "workdir (optional absolute path or empty string), env (optional object of env vars). "
        "The command must be one safe shell command suitable for bash — no markdown or commentary."
    )
    user = (
        f"Service id: {service_id or 'unknown'}\n"
        f"Display name: {name or service_id or 'service'}\n"
        f"Description: {desc}"
    )
    try:
        from arka.llm.cli import llm_complete

        raw = llm_complete(system, user, temperature=0.1, task="route", skill="service_autostart")
    except ImportError as exc:
        raise RuntimeError(f"LLM unavailable for service inference: {exc}") from exc
    data = _parse_llm_json(raw)
    command = str(data.get("command") or "").strip()
    if not command:
        raise ValueError("Could not infer a start command from the description")
    workdir = str(data.get("workdir") or "").strip()
    env_raw = data.get("env")
    env: dict[str, str] = {}
    if isinstance(env_raw, dict):
        env = {str(k): str(v) for k, v in env_raw.items()}
    return {"command": command, "workdir": workdir, "env": env}


def ensure_wrapper_script(service_id: str) -> Path:
    """Write or refresh the autostart wrapper script for a registered service."""
    svc = get_service(service_id)
    if not svc:
        raise ValueError(f"Unknown service {service_id!r}")
    sid = str(svc["id"])
    paths = _service_paths(sid)
    wrapper = paths["script"]
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(generate_start_script(svc), encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def _security_gate_action(action: str) -> bool:
    if os.environ.get("SERVICE_AUTOSTART_SECURITY", "1").strip().lower() in ("0", "false", "no", "off"):
        return True
    try:
        from arka.core.security import check_action
    except ImportError:
        return True
    result = check_action(action.strip())
    if result.status == "block":
        print(f"Service blocked: {result.reason}", file=sys.stderr)
        return False
    if result.status == "confirm":
        print(f"Service skipped (needs confirm): {result.reason}", file=sys.stderr)
        return False
    return True


def list_services() -> list[dict[str, Any]]:
    return list(_load_registry())


def get_service(service_id: str) -> dict[str, Any] | None:
    sid = _validate_id(service_id)
    for row in _load_registry():
        if row.get("id") == sid:
            return row
    return None


def service_add(
    *,
    service_id: str = "",
    name: str = "",
    command: str = "",
    script: str = "",
    workdir: str = "",
    description: str = "",
    env: dict[str, str] | None = None,
    write_wrapper: bool = True,
) -> dict[str, Any]:
    command = command.strip()
    script = script.strip()
    description = description.strip()
    if not command and not script and not description:
        raise ValueError("command, script, or description is required")
    if command and script:
        raise ValueError("provide either command or script, not both")

    inferred: dict[str, str] = {}
    if description and not command and not script:
        inferred = infer_service_from_description(description, service_id=service_id, name=name)
        command = inferred.get("command", "")
        if not workdir.strip():
            workdir = inferred.get("workdir", "")
        if not env:
            env_raw = inferred.get("env")
            if isinstance(env_raw, dict):
                env = {str(k): str(v) for k, v in env_raw.items()}

    sid = _validate_id(service_id or _slugify(name or command or script or description))
    display = (name or sid).strip()
    work = str(Path(workdir).expanduser().resolve()) if workdir.strip() else ""

    if script:
        script_path = Path(script).expanduser()
        if not script_path.is_file():
            raise ValueError(f"Script not found: {script_path}")
        if not work:
            work = str(script_path.parent.resolve())
        payload_cmd = ""
        payload_script = str(script_path.resolve())
    else:
        if not _security_gate_action(command):
            raise RuntimeError("command blocked by security gate")
        payload_cmd = command
        payload_script = ""

    rows = _load_registry()
    entry: dict[str, Any] = {
        "id": sid,
        "name": display,
        "command": payload_cmd,
        "script": payload_script,
        "workdir": work,
        "description": description,
        "env": dict(env or {}),
        "enabled": True,
        "created": time.time(),
        "updated": time.time(),
    }
    if inferred:
        entry["inferred"] = True
    replaced = False
    for idx, row in enumerate(rows):
        if row.get("id") == sid:
            entry["created"] = row.get("created", entry["created"])
            rows[idx] = entry
            replaced = True
            break
    if not replaced:
        rows.append(entry)
    _save_registry(rows)

    wrapper_path = ""
    if write_wrapper:
        wrapper = ensure_wrapper_script(sid)
        wrapper_path = str(wrapper)
        entry["wrapper_script"] = wrapper_path

    return entry


def service_remove(service_id: str) -> bool:
    sid = _validate_id(service_id)
    rows = _load_registry()
    kept = [row for row in rows if row.get("id") != sid]
    if len(kept) == len(rows):
        return False
    _save_registry(kept)
    return True


def _service_paths(service_id: str) -> dict[str, Path]:
    sid = _validate_id(service_id)
    root = cache_dir()
    return {
        "script": root / f"{sid}-autostart.sh",
        "log": root / f"{sid}-autostart.log",
        "launchd": Path.home() / "Library" / "LaunchAgents" / f"com.arka.service.{sid}.plist",
        "systemd": Path.home() / ".config" / "systemd" / "user" / f"arka-service-{sid}.service",
    }


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_start_script(service: dict[str, Any]) -> str:
    sid = str(service["id"])
    paths = _service_paths(sid)
    log = paths["log"]
    workdir = str(service.get("workdir") or "").strip()
    command = str(service.get("command") or "").strip()
    script = str(service.get("script") or "").strip()
    env_map = service.get("env") if isinstance(service.get("env"), dict) else {}

    lines = [
        "#!/usr/bin/env bash",
        f"# Generated by: arka service_autostart install {sid}",
        "set -euo pipefail",
        "",
        f'LOG={shlex.quote(str(log))}',
        'mkdir -p "$(dirname "$LOG")"',
        "exec >>\"$LOG\" 2>&1",
        "",
        'echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") service autostart starting"',
        "",
    ]

    if env_map:
        lines.append("# Service environment")
        for key, val in sorted(env_map.items()):
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                lines.append(f"export {key}={shlex.quote(str(val))}")
        lines.append("")

    if workdir:
        lines.extend(
            [
                f"WORKDIR={shlex.quote(workdir)}",
                'cd "$WORKDIR"',
                "",
            ]
        )

    if script:
        lines.extend(
            [
                f"SCRIPT={shlex.quote(script)}",
                'echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") running script $SCRIPT"',
                'bash "$SCRIPT"',
            ]
        )
    else:
        lines.extend(
            [
                f'echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") running command: {command}"',
                command,
            ]
        )

    lines.extend(
        [
            'echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") service autostart finished exit=$?"',
            "",
        ]
    )
    return "\n".join(lines)


def generate_launchd_plist(*, service_id: str, script: Path) -> str:
    log = _service_paths(service_id)["log"]
    label = f"com.arka.service.{service_id}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">',
        "<dict>",
        f"  <key>Label</key><string>{label}</string>",
        "  <key>ProgramArguments</key>",
        "  <array>",
        f"    <string>{_xml_escape(str(script))}</string>",
        "  </array>",
        "  <key>RunAtLoad</key><true/>",
        f"  <key>StandardOutPath</key><string>{_xml_escape(str(log))}</string>",
        f"  <key>StandardErrorPath</key><string>{_xml_escape(str(log))}</string>",
        "</dict>",
        "</plist>",
        "",
    ]
    return "\n".join(lines)


def generate_systemd_unit(*, service_id: str, script: Path) -> str:
    name = str(service.get("name") if (service := get_service(service_id)) else service_id)
    return "\n".join(
        [
            "[Unit]",
            f"Description=Arka autostart — {name}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart={shlex.quote(str(script))}",
            "RemainAfterExit=yes",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def supported_platform() -> bool:
    if sys.platform == "darwin":
        return bool(shutil.which("launchctl"))
    if sys.platform.startswith("linux"):
        return bool(shutil.which("systemctl"))
    return False


def platform_label() -> str:
    if sys.platform == "darwin":
        return "macOS"
    if sys.platform.startswith("linux"):
        return "Linux"
    return sys.platform


def _launchctl(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["launchctl", *args], check=False, capture_output=True)


def _systemctl(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["systemctl", *args], check=False, capture_output=True)


def autostart_status(service_id: str | None = None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    services = [get_service(service_id)] if service_id else list_services()
    for svc in services:
        if not svc:
            continue
        sid = str(svc["id"])
        paths = _service_paths(sid)
        status: dict[str, str] = {
            "id": sid,
            "name": str(svc.get("name") or sid),
            "command": str(svc.get("command") or ""),
            "script": str(svc.get("script") or ""),
            "workdir": str(svc.get("workdir") or ""),
            "platform": platform_label(),
            "supported": str(supported_platform()).lower(),
            "wrapper_script": str(paths["script"]),
            "script_present": str(paths["script"].is_file()).lower(),
            "log": str(paths["log"]),
            "installed": "false",
            "loaded": "false",
            "backend": "none",
        }
        if sys.platform == "darwin":
            plist = paths["launchd"]
            status["backend"] = "launchd"
            status["unit"] = str(plist)
            status["installed"] = str(plist.is_file()).lower()
            if plist.is_file() and shutil.which("launchctl"):
                uid = os.getuid()
                proc = _launchctl("print", f"gui/{uid}/com.arka.service.{sid}")
                status["loaded"] = str(proc.returncode == 0).lower()
        elif sys.platform.startswith("linux") and shutil.which("systemctl"):
            unit = paths["systemd"]
            unit_name = unit.name
            status["backend"] = "systemd-user"
            status["unit"] = str(unit)
            status["installed"] = str(unit.is_file()).lower()
            proc = _systemctl("--user", "is-enabled", unit_name)
            status["loaded"] = str(proc.returncode == 0).lower()
        rows.append(status)
    return rows


def install_autostart(service_id: str) -> int:
    if not supported_platform():
        print(
            f"Autostart is supported on macOS (launchd) and Linux (systemd user). "
            f"Current platform: {platform_label()}",
            file=sys.stderr,
        )
        return 1

    svc = get_service(service_id)
    if not svc:
        print(f"Unknown service {service_id!r}. Add it first: service_autostart add ...", file=sys.stderr)
        return 1

    sid = str(svc["id"])
    paths = _service_paths(sid)
    wrapper = ensure_wrapper_script(sid)

    if sys.platform == "darwin":
        plist = paths["launchd"]
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(generate_launchd_plist(service_id=sid, script=wrapper), encoding="utf-8")
        uid = os.getuid()
        _launchctl("bootout", f"gui/{uid}", str(plist))
        proc = _launchctl("bootstrap", f"gui/{uid}", str(plist))
        if proc.returncode != 0:
            _launchctl("load", str(plist))
        print(f"✓ Installed launchd agent com.arka.service.{sid}", file=sys.stderr)
        print(f"  plist: {plist}", file=sys.stderr)
    else:
        unit = paths["systemd"]
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(generate_systemd_unit(service_id=sid, script=wrapper), encoding="utf-8")
        _systemctl("--user", "daemon-reload")
        _systemctl("--user", "enable", "--now", unit.name)
        print(f"✓ Installed systemd user unit {unit.name}", file=sys.stderr)
        print(f"  unit: {unit}", file=sys.stderr)

    print(f"  wrapper: {wrapper}", file=sys.stderr)
    print(f"  log: {paths['log']}", file=sys.stderr)
    print(f"  status: arka service_autostart status {sid}", file=sys.stderr)
    print(f"  remove: arka service_autostart uninstall {sid}", file=sys.stderr)
    return 0


def uninstall_autostart(service_id: str) -> int:
    sid = _validate_id(service_id)
    paths = _service_paths(sid)
    removed = False

    if sys.platform == "darwin":
        plist = paths["launchd"]
        if plist.is_file():
            uid = os.getuid()
            _launchctl("bootout", f"gui/{uid}", str(plist))
            plist.unlink()
            removed = True
            print(f"Removed {plist}", file=sys.stderr)
    elif sys.platform.startswith("linux") and shutil.which("systemctl"):
        unit = paths["systemd"]
        if unit.is_file():
            _systemctl("--user", "disable", "--now", unit.name)
            unit.unlink(missing_ok=True)
            _systemctl("--user", "daemon-reload")
            removed = True
            print(f"Removed {unit}", file=sys.stderr)

    wrapper = paths["script"]
    if wrapper.is_file():
        wrapper.unlink()
        removed = True
        print(f"Removed {wrapper}", file=sys.stderr)

    if not removed:
        print(f"Autostart for {sid} is not installed.", file=sys.stderr)
        return 1
    return 0


def run_service(service_id: str) -> int:
    svc = get_service(service_id)
    if not svc:
        print(f"Unknown service {service_id!r}", file=sys.stderr)
        return 1
    sid = str(svc["id"])
    paths = _service_paths(sid)
    wrapper = paths["script"]
    if not wrapper.is_file():
        wrapper = ensure_wrapper_script(sid)
    proc = subprocess.run([str(wrapper)], check=False)
    return int(proc.returncode)


def nl_to_argv(text: str) -> list[str] | None:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return None

    if re.search(r"(?i)\b(?:service\s+autostart|autostart\s+service)\s+list\b", raw):
        return ["list"]
    if re.search(r"(?i)\b(?:list|show)\b.*\b(?:autostart|login)\s+services?\b", raw):
        return ["list"]
    if re.search(r"(?i)\b(?:service\s+autostart|autostart\s+service)\s+status\b", raw):
        m = re.search(r"(?i)\bstatus\s+([a-z][a-z0-9_-]+)\b", raw)
        return ["status", m.group(1)] if m else ["status"]
    if re.search(r"(?i)\b(?:autostart|login)\s+service\s+status\b", raw):
        m = re.search(r"(?i)\bstatus\s+([a-z][a-z0-9_-]+)\b", raw)
        return ["status", m.group(1)] if m else ["status"]

    m = re.search(
        r"(?i)\b(?:autostart|start)\s+(?:on\s+login|at\s+login)\s+(?:service\s+)?([a-z][a-z0-9_-]+)\b",
        raw,
    )
    if m:
        return ["install", m.group(1)]

    m = re.search(
        r"(?i)\b(?:add|register)\s+(?:autostart\s+)?service\s+([a-z][a-z0-9_-]+)\s+(?:script\s+)?(.+)$",
        raw,
    )
    if m:
        tail = m.group(2).strip()
        if tail.endswith((".sh", ".bash")) or " script " in raw.lower():
            script = re.sub(r"(?i)^script\s+", "", tail).strip()
            return ["add", m.group(1), "--script", script]
        return ["add", m.group(1), "--command", tail]

    return None


def route_command(text: str) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    if not re.search(
        r"(?i)\b(?:service\s+autostart|autostart\s+service|autostart\s+on\s+login|start\s+on\s+login)\b",
        raw,
    ):
        return ""
    argv = nl_to_argv(raw)
    if not argv:
        return "service_autostart list"
    return "service_autostart " + " ".join(shlex.quote(a) for a in argv)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Autostart any service at login — register commands or scripts, install via launchd/systemd"
    )
    sub = p.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="Register a service command or script")
    p_add.add_argument("id", help="Service id (lowercase slug)")
    p_add.add_argument("--name", default="", help="Display name")
    p_add.add_argument("--command", default="", help="Shell command to run at login")
    p_add.add_argument("--script", default="", help="Path to an existing start script")
    p_add.add_argument(
        "--description",
        default="",
        help="Natural-language service description (LLM infers command when command/script omitted)",
    )
    p_add.add_argument("--workdir", default="", help="Working directory")
    p_add.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VAL",
        help="Environment variable (repeatable)",
    )
    p_add.set_defaults(func=cmd_add)

    sub.add_parser("list", help="List registered services").set_defaults(func=cmd_list)

    p_inst = sub.add_parser("install", help="Install login autostart for a service")
    p_inst.add_argument("id")
    p_inst.set_defaults(func=cmd_install)

    p_un = sub.add_parser("uninstall", help="Remove login autostart for a service")
    p_un.add_argument("id")
    p_un.set_defaults(func=cmd_uninstall)

    p_rm = sub.add_parser("remove", help="Remove a service from the registry")
    p_rm.add_argument("id")
    p_rm.set_defaults(func=cmd_remove)

    p_status = sub.add_parser("status", help="Show autostart status")
    p_status.add_argument("id", nargs="?", default="")
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser("run", help="Run a service wrapper once (test)")
    p_run.add_argument("id")
    p_run.set_defaults(func=cmd_run)

    p_parse = sub.add_parser("parse", help="Parse natural language → argv (internal)")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    return p


def _parse_env(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid env pair {pair!r} — use KEY=VAL")
        key, val = pair.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def cmd_add(args: argparse.Namespace) -> int:
    try:
        entry = service_add(
            service_id=args.id,
            name=args.name,
            command=args.command,
            script=args.script,
            description=args.description,
            workdir=args.workdir,
            env=_parse_env(args.env),
        )
    except (ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(entry, indent=2))
    if entry.get("wrapper_script"):
        print(f"Wrapper script: {entry['wrapper_script']}", file=sys.stderr)
    print(f"Install at login: arka service_autostart install {entry['id']}", file=sys.stderr)
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    rows = list_services()
    if not rows:
        print("No services registered.")
        return 0
    print(json.dumps(rows, indent=2))
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    return install_autostart(args.id)


def cmd_uninstall(args: argparse.Namespace) -> int:
    return uninstall_autostart(args.id)


def cmd_remove(args: argparse.Namespace) -> int:
    if not service_remove(args.id):
        print(f"No service {args.id}", file=sys.stderr)
        return 1
    print(f"Removed service {args.id}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    sid = str(args.id or "").strip()
    rows = autostart_status(sid or None)
    if sid and not rows:
        print(f"No service {sid}", file=sys.stderr)
        return 1
    for row in rows:
        for key, value in row.items():
            print(f"{key}\t{value}")
        if len(rows) > 1:
            print("")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    return run_service(args.id)


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    print(json.dumps(argv or []))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in _KNOWN_CMDS:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl
        else:
            print("Could not parse service autostart request. Try:", file=sys.stderr)
            print('  service_autostart add my-api --command "npm start" --workdir ~/dev/my-api', file=sys.stderr)
            print("  service_autostart add postgres --script ~/bin/start-postgres.sh", file=sys.stderr)
            print("  service_autostart install my-api", file=sys.stderr)
            print("  service_autostart list", file=sys.stderr)
            return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if not func:
        parser.print_help()
        return 0
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
