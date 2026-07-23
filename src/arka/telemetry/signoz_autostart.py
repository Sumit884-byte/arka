"""Login autostart for the local SigNoz Docker stack (foundryctl cast)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from arka.telemetry.signoz_setup import (
    FOUNDRY_BIN_DIRS,
    docker_cli_path,
    foundryctl_path,
    platform_label,
    resolve_casting_yaml,
)

AUTOSTART_LABEL = "com.arka.signoz"
SYSTEMD_UNIT = "arka-signoz.service"
SIGNOZ_AUTOSTART_ENV = "SIGNOZ_AUTOSTART"
SIGNOZ_AUTOSTART_LEGACY_ENV = "ARKA_SIGNOZ_AUTOSTART"
_AUTOSTART_FALSY = frozenset({"0", "false", "no", "off"})
_AUTOSTART_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _ensure_env_loaded() -> None:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass


def _autostart_env_value() -> str:
    _ensure_env_loaded()
    for key in (SIGNOZ_AUTOSTART_ENV, SIGNOZ_AUTOSTART_LEGACY_ENV):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return ""


def signoz_autostart_enabled() -> bool:
    """Return False when SIGNOZ_AUTOSTART is explicitly off; default True when unset."""
    raw = _autostart_env_value().lower()
    if raw in _AUTOSTART_FALSY:
        return False
    if raw in _AUTOSTART_TRUTHY:
        return True
    return True


def signoz_autostart_config_status() -> dict[str, str]:
    """Report whether .env allows SigNoz login autostart."""
    raw = _autostart_env_value()
    if not raw:
        return {
            "config_enabled": "true",
            "config_detail": "default (on when unset)",
        }
    if signoz_autostart_enabled():
        return {
            "config_enabled": "true",
            "config_detail": f"{SIGNOZ_AUTOSTART_ENV}={raw}",
        }
    return {
        "config_enabled": "false",
        "config_detail": "disabled-by-config",
    }

DOCKER_DESKTOP_SETTINGS = (
    Path.home() / "Library" / "Group Containers" / "group.com.docker" / "settings-store.json"
)


def docker_desktop_installed() -> bool:
    return Path("/Applications/Docker.app").is_dir()


def read_docker_desktop_autostart() -> bool | None:
    """Return Docker Desktop AutoStart preference, or None if unknown."""
    settings = DOCKER_DESKTOP_SETTINGS
    if settings.is_file():
        try:
            import json

            data = json.loads(settings.read_text(encoding="utf-8"))
            if isinstance(data.get("AutoStart"), bool):
                return data["AutoStart"]
        except (OSError, ValueError, TypeError):
            pass
    proc = subprocess.run(
        ["defaults", "read", "com.docker.docker", "AutoStart"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip().lower()
    if value in ("1", "true", "yes"):
        return True
    if value in ("0", "false", "no"):
        return False
    return None


def _write_docker_desktop_autostart(*, enabled: bool) -> bool:
    """Persist Docker Desktop Start when you sign in (best-effort)."""
    ok = False
    settings = DOCKER_DESKTOP_SETTINGS
    if settings.is_file() or settings.parent.is_dir():
        try:
            import json

            settings.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, object] = {}
            if settings.is_file():
                loaded = json.loads(settings.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            if data.get("AutoStart") is enabled:
                ok = True
            else:
                data["AutoStart"] = enabled
                settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                ok = True
        except (OSError, ValueError, TypeError):
            pass
    proc = subprocess.run(
        [
            "defaults",
            "write",
            "com.docker.docker",
            "AutoStart",
            "-bool",
            "true" if enabled else "false",
        ],
        capture_output=True,
    )
    if proc.returncode == 0:
        ok = True
    return ok


def linux_docker_service_enabled() -> bool | None:
    if not sys.platform.startswith("linux") or not shutil.which("systemctl"):
        return None
    proc = subprocess.run(
        ["systemctl", "is-enabled", "docker"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True
    state = (proc.stdout or proc.stderr or "").strip().lower()
    if "disabled" in state or proc.returncode == 1:
        return False
    return None


def docker_autostart_status() -> dict[str, str]:
    """Report whether Docker is configured to start at login/boot (read-only)."""
    if sys.platform == "darwin":
        if not docker_desktop_installed():
            return {
                "docker_autostart": "missing",
                "docker_autostart_detail": "Docker Desktop not installed",
            }
        current = read_docker_desktop_autostart()
        if current is True:
            return {
                "docker_autostart": "enabled",
                "docker_autostart_detail": "Docker Desktop AutoStart is on",
            }
        if current is False:
            return {
                "docker_autostart": "disabled",
                "docker_autostart_detail": "Docker Desktop AutoStart is off",
            }
        return {
            "docker_autostart": "unknown",
            "docker_autostart_detail": "Could not read Docker Desktop AutoStart",
        }
    if sys.platform.startswith("linux"):
        enabled = linux_docker_service_enabled()
        if enabled is True:
            return {"docker_autostart": "enabled", "docker_autostart_detail": "docker.service enabled"}
        if enabled is False:
            return {"docker_autostart": "disabled", "docker_autostart_detail": "docker.service disabled"}
        return {"docker_autostart": "unknown", "docker_autostart_detail": "docker.service status unknown"}
    return {
        "docker_autostart": "unsupported",
        "docker_autostart_detail": f"Platform {platform_label()}",
    }


def enable_docker_autostart() -> dict[str, str]:
    """Enable Docker to start at login/boot before the SigNoz stack autostart runs."""
    current = docker_autostart_status()
    if current["docker_autostart"] == "enabled":
        return current
    if sys.platform == "darwin":
        if not docker_desktop_installed():
            return current
        if _write_docker_desktop_autostart(enabled=True):
            return {
                "docker_autostart": "enabled",
                "docker_autostart_detail": "Enabled Docker Desktop AutoStart (settings-store.json / defaults)",
            }
        return {
            "docker_autostart": "manual",
            "docker_autostart_detail": "Enable in Docker Desktop → Settings → General → Start Docker Desktop when you sign in",
        }
    if sys.platform.startswith("linux"):
        if linux_docker_service_enabled() is True:
            return current
        proc = subprocess.run(
            ["systemctl", "enable", "docker"],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return {
                "docker_autostart": "enabled",
                "docker_autostart_detail": "Enabled docker.service via systemctl",
            }
        return {
            "docker_autostart": "manual",
            "docker_autostart_detail": "Run: sudo systemctl enable --now docker",
        }
    return current


def launch_docker_desktop_if_needed() -> None:
    """Open Docker Desktop on macOS when the daemon is not running."""
    if sys.platform != "darwin" or not docker_desktop_installed():
        return
    from arka.telemetry.signoz_setup import docker_daemon_running

    if docker_daemon_running(timeout=3.0):
        return
    subprocess.run(
        ["osascript", "-e", 'tell application "Docker" to activate'],
        check=False,
        capture_output=True,
    )
    subprocess.run(["open", "-a", "Docker"], check=False)


def _cache_dir() -> Path:
    from arka.paths import cache_dir

    return cache_dir()


def autostart_script_path() -> Path:
    return _cache_dir() / "signoz-autostart.sh"


def autostart_log_path() -> Path:
    return _cache_dir() / "signoz-autostart.log"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{AUTOSTART_LABEL}.plist"


def systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _foundry_path_prefix() -> str:
    parts = [str(directory) for directory in FOUNDRY_BIN_DIRS]
    return os.pathsep.join(parts)


def generate_env_loader_bash() -> str:
    """Bash snippet that loads Arka .env files (for SIGNOZ_AUTOSTART at login)."""
    return "\n".join(
        [
            "_load_arka_env_file() {",
            "  local env_file=$1",
            "  [[ -f \"$env_file\" ]] || return 1",
            "  set -a",
            "  while IFS= read -r line || [[ -n \"$line\" ]]; do",
            "    [[ \"$line\" =~ ^[[:space:]]*# ]] && continue",
            "    [[ \"$line\" =~ ^[[:space:]]*$ ]] && continue",
            "    line=\"${line%%#*}\"",
            "    line=\"${line%\"${line##*[![:space:]]}\"}\"",
            "    [[ \"$line\" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue",
            "    local key=\"${BASH_REMATCH[1]}\" val=\"${BASH_REMATCH[2]}\"",
            "    val=\"${val#\"${val%%[![:space:]]*}\"}\"",
            "    val=\"${val%\"${val##*[![:space:]]}\"}\"",
            "    val=\"${val%$'\\r'}\"",
            "    val=\"${val#\\\"}\"; val=\"${val%\\\"}\"",
            "    export \"$key\"=\"$val\"",
            "  done < \"$env_file\"",
            "  set +a",
            "  return 0",
            "}",
            "",
            "_load_arka_env() {",
            "  local candidate",
            "  for candidate in \\",
            "    \"${ARKA_CONFIG_DIR:-$HOME/.config/arka}/.env\" \\",
            "    \"$HOME/.config/fish/.env\" \\",
            "    \"${ARKA_HOME:-$HOME/.config/arka}/.env\"; do",
            "    _load_arka_env_file \"$candidate\" && return 0",
            "  done",
            "  return 1",
            "}",
            "",
            "_load_arka_env || true",
            "",
            "_signoz_autostart_disabled() {",
            "  local raw=\"${SIGNOZ_AUTOSTART:-${ARKA_SIGNOZ_AUTOSTART:-}}\"",
            "  raw=\"$(printf '%s' \"$raw\" | tr '[:upper:]' '[:lower:]')\"",
            "  case \"$raw\" in 0|false|no|off) return 0 ;; esac",
            "  return 1",
            "}",
            "",
            "if _signoz_autostart_disabled; then",
            '  echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") signoz autostart disabled by SIGNOZ_AUTOSTART — exit"',
            "  exit 0",
            "fi",
            "",
        ]
    )


def generate_autostart_script(*, casting: Path) -> str:
    """Render the shell script that waits for Docker and runs foundryctl cast."""
    log = autostart_log_path()
    casting_resolved = casting.expanduser().resolve()
    path_prefix = _foundry_path_prefix()
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "# Generated by: arka signoz autostart install",
            "set -euo pipefail",
            "",
            f'LOG={shlex_quote(str(log))}',
            f'DEFAULT_CASTING={shlex_quote(str(casting_resolved))}',
            f'PATH="{path_prefix}:$PATH"',
            "export PATH",
            "",
            "mkdir -p \"$(dirname \"$LOG\")\"",
            "exec >>\"$LOG\" 2>&1",
            "",
            generate_env_loader_bash().rstrip(),
            "",
            'echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") signoz autostart starting"',
            "",
            'CASTING="${ARKA_SIGNOZ_CASTING:-$DEFAULT_CASTING}"',
            'CASTING_DIR="$(cd "$(dirname "$CASTING")" && pwd)"',
            'cd "$CASTING_DIR"',
            "",
            'if [[ "$(uname -s)" == "Darwin" ]] && ! docker info >/dev/null 2>&1; then',
            '  if [[ -d /Applications/Docker.app ]]; then',
            '    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") opening Docker Desktop"',
            '    osascript -e \'tell application "Docker" to activate\' >/dev/null 2>&1 || true',
            "    open -a Docker >/dev/null 2>&1 || true",
            "  fi",
            "fi",
            "",
            "deadline=$((SECONDS + 120))",
            "while ! docker info >/dev/null 2>&1; do",
            '  if (( SECONDS >= deadline )); then',
            '    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") docker not ready after 120s — abort"',
            "    exit 1",
            "  fi",
            "  sleep 3",
            "done",
            'echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") docker ready"',
            "",
            'foundryctl_bin="${FOUNDRYCTL:-}"',
            'if [[ -z "$foundryctl_bin" ]]; then',
            "  foundryctl_bin=$(command -v foundryctl || true)",
            "fi",
            'if [[ -z "$foundryctl_bin" ]]; then',
            f"  for candidate in {' '.join(shlex_quote(str(d / 'foundryctl')) for d in FOUNDRY_BIN_DIRS)}; do",
            '    if [[ -x "$candidate" ]]; then',
            '      foundryctl_bin="$candidate"',
            "      break",
            "    fi",
            "  done",
            "fi",
            'if [[ -z "$foundryctl_bin" ]]; then',
            '  echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") foundryctl not found — run: arka signoz setup -y"',
            "  exit 127",
            "fi",
            "",
            'echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") running $foundryctl_bin cast -f $CASTING --no-gauge"',
            '"$foundryctl_bin" cast -f "$CASTING" --no-gauge',
            'echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") signoz autostart finished exit=$?"',
            "",
        ]
    )


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def generate_launchd_plist(*, script: Path) -> str:
    log = autostart_log_path()
    args = [str(script)]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">',
        "<dict>",
        f"  <key>Label</key><string>{AUTOSTART_LABEL}</string>",
        "  <key>ProgramArguments</key>",
        "  <array>",
    ]
    for arg in args:
        lines.append(f"    <string>{_xml_escape(arg)}</string>")
    lines.extend(
        [
            "  </array>",
            "  <key>RunAtLoad</key><true/>",
            f"  <key>StandardOutPath</key><string>{_xml_escape(str(log))}</string>",
            f"  <key>StandardErrorPath</key><string>{_xml_escape(str(log))}</string>",
            "</dict>",
            "</plist>",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_systemd_unit(*, script: Path) -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=Arka SigNoz Docker stack (foundryctl cast on login)",
            "After=network-online.target docker.service",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart={shlex_quote(str(script))}",
            "RemainAfterExit=yes",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def _launchctl(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["launchctl", *args], check=False, capture_output=True)


def _systemctl(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["systemctl", *args], check=False, capture_output=True)


def supported_platform() -> bool:
    if sys.platform == "darwin":
        return bool(shutil.which("launchctl"))
    if sys.platform.startswith("linux"):
        return bool(shutil.which("systemctl"))
    return False


def autostart_status() -> dict[str, str]:
    script = autostart_script_path()
    log = autostart_log_path()
    casting = resolve_casting_yaml()
    status: dict[str, str] = {
        "platform": platform_label(),
        "supported": str(supported_platform()).lower(),
        "script": str(script),
        "script_present": str(script.is_file()).lower(),
        "log": str(log),
        "casting_yaml": str(casting) if casting else "missing",
        "docker_cli": "ok" if docker_cli_path() else "missing",
        "foundryctl": "ok" if foundryctl_path() else "missing",
        **signoz_autostart_config_status(),
        **docker_autostart_status(),
        "installed": "false",
        "loaded": "false",
        "backend": "none",
    }

    if sys.platform == "darwin":
        plist = launchd_plist_path()
        status["backend"] = "launchd"
        status["unit"] = str(plist)
        status["installed"] = str(plist.is_file()).lower()
        if plist.is_file() and shutil.which("launchctl"):
            uid = os.getuid()
            proc = _launchctl("print", f"gui/{uid}/{AUTOSTART_LABEL}")
            status["loaded"] = str(proc.returncode == 0).lower()
    elif sys.platform.startswith("linux") and shutil.which("systemctl"):
        unit = systemd_unit_path()
        status["backend"] = "systemd-user"
        status["unit"] = str(unit)
        status["installed"] = str(unit.is_file()).lower()
        proc = _systemctl("--user", "is-enabled", SYSTEMD_UNIT)
        status["loaded"] = str(proc.returncode == 0).lower()

    return status


def install_autostart(*, casting: Path | None = None) -> int:
    if not supported_platform():
        print(
            f"Autostart is supported on macOS (launchd) and Linux (systemd user). "
            f"Current platform: {platform_label()}",
            file=sys.stderr,
        )
        return 1

    if not signoz_autostart_enabled():
        cfg = signoz_autostart_config_status()
        existing = autostart_status()
        if existing.get("installed") == "true":
            print(
                f"  {SIGNOZ_AUTOSTART_ENV} is off ({cfg['config_detail']}) — removing existing autostart.",
                file=sys.stderr,
            )
            return uninstall_autostart()
        print(
            f"  SigNoz autostart disabled ({cfg['config_detail']}). "
            f"Set {SIGNOZ_AUTOSTART_ENV}=1 in .env to enable.",
            file=sys.stderr,
        )
        return 0

    casting_path = casting or resolve_casting_yaml()
    if not casting_path or not casting_path.is_file():
        print(
            "casting.yaml not found. Run `arka signoz setup -y` first or set ARKA_SIGNOZ_CASTING.",
            file=sys.stderr,
        )
        return 1

    if not docker_cli_path():
        print(
            "Docker CLI not found. Install Docker and enable Start at login in Docker Desktop settings.",
            file=sys.stderr,
        )
        return 1

    if not foundryctl_path():
        print("foundryctl not found. Run: arka signoz setup -y", file=sys.stderr)
        return 1

    docker_auto = enable_docker_autostart()
    print(f"  docker autostart: {docker_auto['docker_autostart']}", file=sys.stderr)
    if docker_auto.get("docker_autostart_detail"):
        print(f"    {docker_auto['docker_autostart_detail']}", file=sys.stderr)
    launch_docker_desktop_if_needed()

    script = autostart_script_path()
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(generate_autostart_script(casting=casting_path), encoding="utf-8")
    script.chmod(0o755)

    if sys.platform == "darwin":
        plist = launchd_plist_path()
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(generate_launchd_plist(script=script), encoding="utf-8")
        uid = os.getuid()
        _launchctl("bootout", f"gui/{uid}", str(plist))
        proc = _launchctl("bootstrap", f"gui/{uid}", str(plist))
        if proc.returncode != 0:
            _launchctl("load", str(plist))
        print(f"✓ Installed launchd agent {AUTOSTART_LABEL}", file=sys.stderr)
        print(f"  plist: {plist}", file=sys.stderr)
    else:
        unit = systemd_unit_path()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(generate_systemd_unit(script=script), encoding="utf-8")
        _systemctl("--user", "daemon-reload")
        _systemctl("--user", "enable", "--now", SYSTEMD_UNIT)
        print(f"✓ Installed systemd user unit {SYSTEMD_UNIT}", file=sys.stderr)
        print(f"  unit: {unit}", file=sys.stderr)

    print(f"  script: {script}", file=sys.stderr)
    print(f"  log: {autostart_log_path()}", file=sys.stderr)
    print(f"  casting: {casting_path.resolve()}", file=sys.stderr)
    print("  status: arka signoz autostart status", file=sys.stderr)
    print("  remove: arka signoz autostart uninstall", file=sys.stderr)
    return 0


def uninstall_autostart() -> int:
    removed = False
    if sys.platform == "darwin":
        plist = launchd_plist_path()
        if plist.is_file():
            uid = os.getuid()
            _launchctl("bootout", f"gui/{uid}", str(plist))
            plist.unlink()
            removed = True
            print(f"Removed {plist}", file=sys.stderr)
    elif sys.platform.startswith("linux") and shutil.which("systemctl"):
        unit = systemd_unit_path()
        if unit.is_file():
            _systemctl("--user", "disable", "--now", SYSTEMD_UNIT)
            unit.unlink(missing_ok=True)
            _systemctl("--user", "daemon-reload")
            removed = True
            print(f"Removed {unit}", file=sys.stderr)

    script = autostart_script_path()
    if script.is_file():
        script.unlink()
        removed = True
        print(f"Removed {script}", file=sys.stderr)

    if not removed:
        print("SigNoz autostart is not installed.", file=sys.stderr)
        return 1
    return 0


def cmd_autostart(args: argparse.Namespace) -> int:
    action = getattr(args, "autostart_action", "status")
    if action == "install":
        return install_autostart()
    if action == "uninstall":
        return uninstall_autostart()
    for key, value in autostart_status().items():
        print(f"{key}\t{value}")
    return 0
