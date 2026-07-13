"""Context7 MCP — up-to-date library documentation for Arka agents."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

CONTEXT7_MCP_SERVER_KEY = "context7"
CONTEXT7_MCP_PKG = "@upstash/context7-mcp"
CONTEXT7_CLI_PKG = "ctx7"
CONTEXT7_ENV_VAR = "CONTEXT7_API_KEY"
CONTEXT7_TOOLS = frozenset({"resolve-library-id", "query-docs"})
_CONTEXT7_LIBS: list[str] = []
SETUP_HINT = (
    "Context7 fetches current library docs via MCP.\n"
    "  npx ctx7 setup --mcp --stdio -y   # OAuth login + credentials\n"
    f"  Or set {CONTEXT7_ENV_VAR} in ~/.config/arka/.env"
)


def npx_available() -> bool:
    return bool(shutil.which("npx"))


def credentials_path() -> Path:
    return Path.home() / ".config" / "context7" / "credentials.json"


def load_credentials_api_key() -> str:
    path = credentials_path()
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    token = str(data.get("access_token") or data.get("api_key") or "").strip()
    return token


def context7_api_key() -> str:
    from arka.paths import load_env_file

    load_env_file()
    env_key = os.environ.get(CONTEXT7_ENV_VAR, "").strip()
    if env_key:
        return env_key
    return load_credentials_api_key()


def context7_configured() -> bool:
    return bool(context7_api_key())


def show_context7_enabled() -> bool:
    """True unless SHOW_CONTEXT7 is explicitly disabled (default on, like SHOW_MODEL)."""
    raw = os.environ.get("SHOW_CONTEXT7", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def _context7_library_label(tool_name: str, arguments: dict[str, Any] | None) -> str:
    args = arguments or {}
    tool = tool_name.strip().lower()
    if tool == "resolve-library-id":
        return str(args.get("libraryName") or args.get("library_name") or "").strip()
    if tool == "query-docs":
        lib_id = str(args.get("libraryId") or args.get("library_id") or "").strip()
        return lib_id.lstrip("/")
    return ""


def reset_context7_usage() -> None:
    global _CONTEXT7_LIBS
    _CONTEXT7_LIBS = []


def record_context7_usage(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    """Track Context7 tool use and return the library label for this call."""
    global _CONTEXT7_LIBS
    label = _context7_library_label(tool_name, arguments)
    if label and label not in _CONTEXT7_LIBS:
        _CONTEXT7_LIBS.append(label)
    return label


def context7_usage_label() -> str | None:
    """Footer label for answer blocks, e.g. context7/vercel/next.js."""
    if not _CONTEXT7_LIBS:
        return None
    return "context7/" + ", context7/".join(_CONTEXT7_LIBS)


def format_context7_stderr(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    tool = tool_name.strip().lower()
    label = _context7_library_label(tool_name, arguments)
    if tool == "resolve-library-id":
        target = label or "library"
        return f"Context7: resolving library {target}"
    if tool == "query-docs":
        target = f"/{label}" if label and not label.startswith("/") else (label or "docs")
        return f"Context7: querying docs for {target}"
    return "Context7: docs lookup"


def notify_context7_tool_call(
    server: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> None:
    """Emit user-visible Context7 usage when configured MCP tools are invoked."""
    if server.strip() != CONTEXT7_MCP_SERVER_KEY:
        return
    if tool_name.strip().lower() not in CONTEXT7_TOOLS:
        return
    if not show_context7_enabled():
        return
    record_context7_usage(tool_name, arguments)
    print(format_context7_stderr(tool_name, arguments), file=sys.stderr)


def context7_mcp_launch_spec() -> dict[str, Any]:
    return {
        "command": "npx",
        "args": ["-y", CONTEXT7_MCP_PKG],
        "env": {CONTEXT7_ENV_VAR: f"${{env:{CONTEXT7_ENV_VAR}}}"},
    }


def ensure_context7_in_config() -> bool:
    """Add Context7 MCP entry to ~/.config/arka/mcp.json if missing."""
    from arka.integrations.mcp_manager import load_mcp_config, save_mcp_config

    data = load_mcp_config()
    servers = data.setdefault("mcpServers", {})
    if CONTEXT7_MCP_SERVER_KEY in servers:
        return False
    servers[CONTEXT7_MCP_SERVER_KEY] = context7_mcp_launch_spec()
    save_mcp_config(data)
    return True


def _env_has_context7_key(env_path: Path) -> bool:
    if not env_path.is_file():
        return False
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == CONTEXT7_ENV_VAR and value.strip():
            return True
    return False


def sync_context7_env_key(*, quiet: bool = False) -> bool:
    """Copy Context7 credentials into ~/.config/arka/.env when missing."""
    from arka.paths import env_file

    key = load_credentials_api_key()
    if not key:
        return False
    path = env_file()
    if _env_has_context7_key(path):
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        with path.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(f"\n# Context7 MCP — library documentation ({CONTEXT7_MCP_PKG})\n")
            handle.write(f"{CONTEXT7_ENV_VAR}={key}\n")
    except OSError as exc:
        if not quiet:
            print(f"  ⚠ Could not write {CONTEXT7_ENV_VAR} to {path}: {exc}", file=sys.stderr)
        return False
    if not quiet:
        print(f"  ✓ {CONTEXT7_ENV_VAR} added to {path}")
    return True


def run_ctx7_setup(*, auto_yes: bool = True, timeout: float = 180.0) -> dict[str, Any]:
    """Run `npx ctx7 setup` to obtain OAuth credentials when interactive."""
    if not npx_available():
        return {"ok": False, "skipped": True, "reason": "npx not found"}
    if context7_configured():
        return {"ok": True, "skipped": True, "reason": "already configured"}
    if not sys.stdin.isatty():
        return {
            "ok": False,
            "skipped": True,
            "reason": f"non-interactive; set {CONTEXT7_ENV_VAR} or run: npx ctx7 setup",
        }
    cmd = ["npx", "-y", CONTEXT7_CLI_PKG, "setup", "--mcp", "--stdio"]
    if auto_yes:
        cmd.append("-y")
    try:
        proc = subprocess.run(cmd, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "skipped": False, "reason": "ctx7 setup timed out"}
    except OSError as exc:
        return {"ok": False, "skipped": False, "reason": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "skipped": False, "reason": f"ctx7 setup exited {proc.returncode}"}
    return {"ok": True, "skipped": False, "reason": "ctx7 setup complete"}


def setup_context7(*, skip_cli: bool = False, quiet: bool = False) -> dict[str, Any]:
    """Default Context7 setup for `arka setup`."""
    result: dict[str, Any] = {"mcp_added": False, "env_synced": False, "cli": None}
    result["mcp_added"] = ensure_context7_in_config()
    if skip_cli:
        result["cli"] = {"ok": True, "skipped": True, "reason": "--no-context7"}
        if not quiet and not npx_available():
            print("  ⚠ Context7 MCP configured; npx not found — install Node.js 18+ for live docs")
        elif not quiet and not context7_configured():
            print(f"  → Context7: run `npx ctx7 setup` or set {CONTEXT7_ENV_VAR} in .env")
        return result

    if not npx_available():
        result["cli"] = {"ok": False, "skipped": True, "reason": "npx not found"}
        if not quiet:
            print("  ⚠ Context7 MCP entry added; npx not found — install Node.js 18+ for live docs")
        return result

    cli_result = run_ctx7_setup()
    result["cli"] = cli_result
    if cli_result.get("ok") and not cli_result.get("skipped"):
        result["env_synced"] = sync_context7_env_key(quiet=quiet)
    elif context7_configured():
        result["env_synced"] = sync_context7_env_key(quiet=quiet)

    if not quiet:
        if result["mcp_added"]:
            print("  ✓ Context7 MCP added to ~/.config/arka/mcp.json")
        if cli_result.get("skipped") and cli_result.get("reason") == "already configured":
            if result["env_synced"]:
                pass
            elif context7_configured():
                print("  ✓ Context7 credentials ready")
            else:
                print(f"  → Context7: run `npx ctx7 setup` or set {CONTEXT7_ENV_VAR} in .env")
        elif cli_result.get("skipped") and cli_result.get("reason") == "npx not found":
            print("  ⚠ Context7 MCP entry added; npx not found — install Node.js 18+ for live docs")
        elif cli_result.get("skipped") and "non-interactive" in str(cli_result.get("reason", "")):
            print(f"  → Context7: run `npx ctx7 setup` or set {CONTEXT7_ENV_VAR} in .env")
        elif cli_result.get("ok") and not cli_result.get("skipped"):
            print("  ✓ Context7 setup complete (library docs MCP)")
        elif not cli_result.get("ok") and not cli_result.get("skipped"):
            print(f"  ⚠ Context7 setup failed: {cli_result.get('reason')}", file=sys.stderr)
            print(f"    Retry: npx ctx7 setup  |  or set {CONTEXT7_ENV_VAR} in .env", file=sys.stderr)
    return result


def doctor_checks() -> list[dict[str, Any]]:
    """Lightweight Context7 checks for `arka doctor`."""
    from arka.integrations.mcp_manager import load_mcp_config, mcp_config_path

    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "name": "context7_npx",
            "ok": npx_available(),
            "detail": "npx available" if npx_available() else "install Node.js 18+ (npx)",
        }
    )

    data = load_mcp_config()
    servers = data.get("mcpServers") or {}
    in_config = CONTEXT7_MCP_SERVER_KEY in servers
    checks.append(
        {
            "name": "context7_mcp_config",
            "ok": in_config,
            "detail": str(mcp_config_path()) if in_config else "run: arka setup",
        }
    )

    configured = context7_configured()
    checks.append(
        {
            "name": "context7_api_key",
            "ok": configured,
            "detail": (
                f"{CONTEXT7_ENV_VAR} set"
                if os.environ.get(CONTEXT7_ENV_VAR, "").strip()
                else (
                    "credentials.json"
                    if load_credentials_api_key()
                    else f"run: npx ctx7 setup  |  set {CONTEXT7_ENV_VAR}"
                )
            ),
        }
    )
    return checks


def format_doctor_lines() -> list[str]:
    lines: list[str] = []
    for check in doctor_checks():
        status = "ok" if check["ok"] else "missing"
        lines.append(f"  context7 {check['name'].removeprefix('context7_')}: {status} ({check['detail']})")
    return lines


__all__ = [
    "CONTEXT7_ENV_VAR",
    "CONTEXT7_MCP_SERVER_KEY",
    "CONTEXT7_MCP_PKG",
    "CONTEXT7_TOOLS",
    "SETUP_HINT",
    "context7_api_key",
    "context7_configured",
    "context7_mcp_launch_spec",
    "context7_usage_label",
    "doctor_checks",
    "ensure_context7_in_config",
    "format_context7_stderr",
    "format_doctor_lines",
    "notify_context7_tool_call",
    "npx_available",
    "record_context7_usage",
    "reset_context7_usage",
    "run_ctx7_setup",
    "setup_context7",
    "show_context7_enabled",
    "sync_context7_env_key",
]
