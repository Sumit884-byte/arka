"""Arka Agent Hub — shared MCP, memory, and skills for ollama launch agents."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AGENTS: dict[str, dict[str, Any]] = {
    "claude": {
        "name": "Claude Code",
        "ollama_launch": "claude",
        "aliases": ["claude code", "claude-code"],
        "mcp_paths": [
            "~/.cursor/mcp.json",
            "~/Library/Application Support/Claude/claude_desktop_config.json",
        ],
        "memory_hint": "Read ARKA_MEMORY_DIR/summary.json for Arka facts and session notes",
    },
    "codex-app": {
        "name": "Codex App",
        "ollama_launch": "codex-app",
        "aliases": ["codex app"],
        "mcp_paths": ["~/.codex/mcp.json"],
        "memory_hint": "Set ARKA_MEMORY_DIR; read summary.json for cross-agent context",
    },
    "hermes": {
        "name": "Hermes Agent",
        "ollama_launch": "hermes",
        "aliases": [],
        "mcp_paths": ["~/.config/hermes/mcp.json"],
        "memory_hint": "Channel sessions in ARKA_MEMORY_DIR/sessions_index.json",
    },
    "openclaw": {
        "name": "OpenClaw",
        "ollama_launch": "openclaw",
        "aliases": [],
        "mcp_paths": ["~/.openclaw/mcp.json", "~/.config/openclaw/mcp.json"],
        "memory_hint": "Session notes exported to ARKA_MEMORY_DIR/summary.json",
    },
    "opencode": {
        "name": "OpenCode",
        "ollama_launch": "opencode",
        "aliases": ["open code"],
        "mcp_paths": ["~/.config/opencode/mcp.json"],
        "memory_hint": "Use ARKA_MCP_CONFIG for shared MCP servers",
    },
    "codex": {
        "name": "Codex CLI",
        "ollama_launch": "codex",
        "aliases": [],
        "mcp_paths": ["~/.codex/mcp.json"],
        "memory_hint": "Set MCP_CONFIG or ARKA_MCP_CONFIG to hub/mcp.json",
    },
    "copilot": {
        "name": "GitHub Copilot Agent",
        "ollama_launch": "copilot",
        "aliases": ["github copilot"],
        "mcp_paths": ["~/.copilot/mcp.json"],
        "memory_hint": "Read ARKA_MEMORY_DIR/skills_manifest.json for Arka plugins",
    },
    "droid": {
        "name": "Droid",
        "ollama_launch": "droid",
        "aliases": [],
        "mcp_paths": ["~/.config/droid/mcp.json"],
        "memory_hint": "Use ARKA_HUB_DIR as shared config root",
    },
    "pi": {
        "name": "Pi Agent",
        "ollama_launch": "pi",
        "aliases": [],
        "mcp_paths": ["~/.pi/mcp.json", "~/.config/pi/mcp.json"],
        "memory_hint": "Set ARKA_MEMORY_DIR for lightweight memory exports",
    },
}

ADAPTER_TARGETS: dict[str, Path] = {
    "cursor": Path("~/.cursor/mcp.json").expanduser(),
    "claude_desktop": Path(
        "~/Library/Application Support/Claude/claude_desktop_config.json"
    ).expanduser(),
}


def hub_dir() -> Path:
    if env := os.environ.get("ARKA_HUB_DIR", "").strip():
        return Path(env).expanduser().resolve()
    from arka.paths import config_dir

    return config_dir() / "hub"


def hub_mcp_path() -> Path:
    if env := os.environ.get("ARKA_MCP_CONFIG", "").strip():
        return Path(env).expanduser().resolve()
    return hub_dir() / "mcp.json"


def hub_memory_dir() -> Path:
    if env := os.environ.get("ARKA_MEMORY_DIR", "").strip():
        return Path(env).expanduser().resolve()
    return hub_dir() / "memory"


def hub_skills_dir() -> Path:
    return hub_dir() / "skills"


def hub_agents_json_path() -> Path:
    return hub_dir() / "agents.json"


def hub_adapters_dir() -> Path:
    return hub_dir() / "adapters"


def _resolve_agent(name: str) -> tuple[str, dict[str, Any]] | None:
    key = name.strip().lower()
    if not key:
        return None
    if key in AGENTS:
        return key, AGENTS[key]
    for agent_key, meta in AGENTS.items():
        if key == meta.get("ollama_launch", "").lower():
            return agent_key, meta
        for alias in meta.get("aliases") or []:
            if key == str(alias).lower():
                return agent_key, meta
        if key.replace(" ", "-") == agent_key or key.replace("-", " ") == agent_key:
            return agent_key, meta
        if key in meta.get("name", "").lower():
            return agent_key, meta
    return None


def list_agents() -> list[tuple[str, dict[str, Any]]]:
    return sorted(AGENTS.items(), key=lambda x: x[0])


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_agents_registry() -> dict[str, Any]:
    path = hub_agents_json_path()
    if not path.is_file():
        return {"version": 1, "agents": {}, "last_sync": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("version", 1)
            data.setdefault("agents", {})
            data.setdefault("last_sync", {})
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "agents": {}, "last_sync": {}}


def _save_agents_registry(data: dict[str, Any]) -> Path:
    path = hub_agents_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": data.get("version", 1),
        "agents": dict(data.get("agents") or {}),
        "last_sync": dict(data.get("last_sync") or {}),
        "updated_at": _iso_now(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def sync_mcp(*, use_symlink: bool = False) -> dict[str, Any]:
    from arka.integrations.mcp_manager import load_mcp_config, mcp_config_path

    src = mcp_config_path()
    dst = hub_mcp_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"source": str(src), "destination": str(dst), "ok": False}

    if not src.is_file():
        payload = load_mcp_config()
        dst.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        result["ok"] = True
        result["mode"] = "empty"
        return result

    if use_symlink:
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        dst.symlink_to(src.resolve())
        result["ok"] = True
        result["mode"] = "symlink"
        return result

    shutil.copy2(src, dst)
    result["ok"] = True
    result["mode"] = "copy"
    return result


def _export_memory_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {
        "exported_at": _iso_now(),
        "facts": [],
        "facts_status": {},
        "notes_status": {},
        "sessions": [],
    }

    try:
        from arka.core.unified_memory import status as memory_status

        info = memory_status()
        summary["facts_status"] = info.get("facts") or {}
        summary["notes_status"] = info.get("notes") or {}
        summary["unified_memory"] = info.get("unified_memory")
    except ImportError:
        pass

    try:
        from arka.paths import cache_dir

        memory_file = cache_dir() / "memory.json"
        if memory_file.is_file():
            raw = json.loads(memory_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for row in raw[-20:]:
                    if isinstance(row, dict):
                        text = str(row.get("text") or "").strip()
                        if text:
                            summary["facts"].append(
                                {
                                    "text": text[:500],
                                    "when": row.get("when"),
                                }
                            )
    except (OSError, json.JSONDecodeError):
        pass

    try:
        from arka.integrations.message_sessions import list_sessions

        summary["sessions"] = list_sessions(limit=10)
    except ImportError:
        pass

    try:
        from arka.core.session_memory import long_term_path

        lt = long_term_path()
        if lt.is_file():
            lines = [
                ln.strip()
                for ln in lt.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            summary["long_term_notes"] = lines[-15:]
    except ImportError:
        pass

    return summary


def sync_memory() -> dict[str, Any]:
    mem_dir = hub_memory_dir()
    mem_dir.mkdir(parents=True, exist_ok=True)
    summary = _export_memory_summary()
    summary_path = mem_dir / "summary.json"
    index_path = mem_dir / "sessions_index.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    index_path.write_text(
        json.dumps({"sessions": summary.get("sessions") or [], "exported_at": _iso_now()}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "summary": str(summary_path),
        "sessions_index": str(index_path),
        "fact_count": len(summary.get("facts") or []),
        "session_count": len(summary.get("sessions") or []),
    }


def sync_skills() -> dict[str, Any]:
    from arka.agent.skills import discover_skills

    skills_dir = hub_skills_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)
    skills = discover_skills(refresh=True)
    manifest = {
        "exported_at": _iso_now(),
        "count": len(skills),
        "skills": [
            {
                "name": sk.get("name"),
                "description": sk.get("description", ""),
                "triggers": sk.get("triggers") or [],
                "path": sk.get("path"),
                "type": sk.get("type"),
            }
            for sk in skills
        ],
    }
    manifest_path = skills_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    hub_memory_dir().mkdir(parents=True, exist_ok=True)
    (hub_memory_dir() / "skills_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return {"ok": True, "manifest": str(manifest_path), "count": len(skills)}


def write_adapter_snippets(*, force: bool = False) -> list[dict[str, Any]]:
    """Write optional MCP adapter snippets (never overwrite live configs without force)."""
    from arka.integrations.mcp_manager import load_mcp_config

    adapters_dir = hub_adapters_dir()
    adapters_dir.mkdir(parents=True, exist_ok=True)
    hub_mcp = str(hub_mcp_path())
    servers = load_mcp_config().get("mcpServers") or {}
    rows: list[dict[str, Any]] = []

    for label, target in ADAPTER_TARGETS.items():
        snippet_path = adapters_dir / f"{label}_mcp_snippet.json"
        snippet = {
            "description": f"Point {label} at Arka hub MCP config",
            "hub_mcp": hub_mcp,
            "mcpServers": servers,
            "install_hint": f"Merge mcpServers into {target} or symlink to {hub_mcp}",
        }
        snippet_path.write_text(json.dumps(snippet, indent=2) + "\n", encoding="utf-8")
        row = {
            "label": label,
            "snippet": str(snippet_path),
            "target": str(target),
            "target_exists": target.is_file(),
            "would_overwrite": target.is_file(),
        }
        if force and target.parent.exists():
            merged = {"mcpServers": servers}
            if target.is_file():
                try:
                    existing = json.loads(target.read_text(encoding="utf-8"))
                    if isinstance(existing, dict):
                        merged = {**existing, "mcpServers": servers}
                except (OSError, json.JSONDecodeError):
                    pass
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
            row["written"] = True
        else:
            row["written"] = False
        rows.append(row)
    return rows


def sync_all(*, force_adapters: bool = False, use_symlink: bool = False) -> dict[str, Any]:
    hub_dir().mkdir(parents=True, exist_ok=True)
    now = _iso_now()
    results = {
        "mcp": sync_mcp(use_symlink=use_symlink),
        "memory": sync_memory(),
        "skills": sync_skills(),
        "adapters": write_adapter_snippets(force=force_adapters),
        "synced_at": now,
    }

    registry = _load_agents_registry()
    registry["agents"] = {
        key: {
            "name": meta["name"],
            "ollama_launch": meta["ollama_launch"],
            "mcp_paths": meta.get("mcp_paths") or [],
            "memory_hint": meta.get("memory_hint", ""),
        }
        for key, meta in AGENTS.items()
    }
    last_sync = dict(registry.get("last_sync") or {})
    for component in ("mcp", "memory", "skills"):
        last_sync[component] = now
    registry["last_sync"] = last_sync
    results["registry"] = str(_save_agents_registry(registry))
    return results


def launch_env(agent_key: str) -> dict[str, str]:
    hdir = str(hub_dir())
    mcp = str(hub_mcp_path())
    mem = str(hub_memory_dir())
    env = {
        "ARKA_HUB_DIR": hdir,
        "ARKA_MCP_CONFIG": mcp,
        "ARKA_MEMORY_DIR": mem,
        "MCP_CONFIG": mcp,
    }
    meta = AGENTS.get(agent_key) or {}
    env["ARKA_AGENT_NAME"] = str(meta.get("name") or agent_key)
    env["ARKA_AGENT_LAUNCH"] = str(meta.get("ollama_launch") or agent_key)
    return env


def ollama_available() -> bool:
    try:
        proc = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def launch_agent(
    name: str,
    extra_args: list[str] | None = None,
    *,
    sync_on_launch: bool | None = None,
) -> int:
    resolved = _resolve_agent(name)
    if not resolved:
        known = ", ".join(sorted(AGENTS))
        raise ValueError(f"Unknown agent {name!r}. Known: {known}")

    agent_key, meta = resolved
    if sync_on_launch is None:
        sync_on_launch = os.environ.get("AGENT_HUB_SYNC_ON_LAUNCH", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
    if sync_on_launch:
        sync_all()

    launch_name = str(meta.get("ollama_launch") or agent_key)
    cmd = ["ollama", "launch", launch_name, *(extra_args or [])]
    env = {**os.environ, **launch_env(agent_key)}
    return subprocess.run(cmd, env=env).returncode


def doctor() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    checks.append(
        {
            "name": "ollama",
            "ok": ollama_available(),
            "detail": "ollama CLI available" if ollama_available() else "install ollama",
        }
    )

    hdir = hub_dir()
    try:
        hdir.mkdir(parents=True, exist_ok=True)
        probe = hdir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError as exc:
        writable = False
        err = str(exc)
    else:
        err = ""
    checks.append(
        {
            "name": "hub_dir_writable",
            "ok": writable,
            "detail": str(hdir) if writable else err,
        }
    )

    for label, path_fn in (
        ("mcp", hub_mcp_path),
        ("memory", hub_memory_dir),
        ("skills", hub_skills_dir),
        ("registry", hub_agents_json_path),
    ):
        p = path_fn()
        checks.append(
            {
                "name": f"hub_{label}",
                "ok": p.exists(),
                "detail": str(p),
            }
        )

    from arka.integrations.mcp_manager import mcp_config_path

    src = mcp_config_path()
    checks.append(
        {
            "name": "arka_mcp_source",
            "ok": src.is_file(),
            "detail": str(src),
        }
    )
    return checks


def format_agent_list() -> str:
    lines = [f"hub\t{hub_dir()}", f"count\t{len(AGENTS)}"]
    for key, meta in list_agents():
        launch = meta.get("ollama_launch", key)
        lines.append(f"{key}\t{meta.get('name', key)}\tollama launch {launch}")
    lines.append("")
    lines.append("Sync: agent_hub sync")
    lines.append("Launch: agent_hub launch <name>")
    return "\n".join(lines)


def format_status() -> str:
    registry = _load_agents_registry()
    last_sync = registry.get("last_sync") or {}
    lines = [
        f"hub\t{hub_dir()}",
        f"mcp\t{hub_mcp_path()}",
        f"memory\t{hub_memory_dir()}",
        f"skills\t{hub_skills_dir() / 'manifest.json'}",
        f"registry\t{hub_agents_json_path()}",
        f"agents\t{len(AGENTS)}",
    ]
    for component in ("mcp", "memory", "skills"):
        ts = last_sync.get(component)
        lines.append(f"sync_{component}\t{ts or 'never'}")
    lines.append("")
    lines.append("Configured ollama agents:")
    for key, meta in list_agents():
        lines.append(f"  {key}\t{meta.get('name')}\tollama launch {meta.get('ollama_launch')}")
    lines.append("")
    lines.append("Optional MCP adapter snippets (merge manually unless --force):")
    for label, target in ADAPTER_TARGETS.items():
        snippet = hub_adapters_dir() / f"{label}_mcp_snippet.json"
        lines.append(f"  {label}\t{target}\tsnippet={snippet}")
    return "\n".join(lines)


def format_doctor() -> tuple[str, int]:
    checks = doctor()
    lines: list[str] = []
    ok_count = 0
    for row in checks:
        status = "ok" if row.get("ok") else "fail"
        if row.get("ok"):
            ok_count += 1
        lines.append(f"{row.get('name')}\t{status}\t{row.get('detail', '')}")
    lines.append(f"summary\t{ok_count}/{len(checks)} checks passed")
    return "\n".join(lines), 0 if ok_count == len(checks) else 1


def nl_to_argv(cmd: str) -> list[str] | None:
    clean = cmd.strip()
    if not clean:
        return None
    lower = clean.lower()

    if re.search(r"(?i)\b(?:agent\s+hub|arka\s+hub)\b.*\b(?:sync|refresh|update)\b", clean):
        return ["sync"]
    if re.search(r"(?i)\b(?:sync|refresh)\b.*\b(?:agent\s+hub|shared\s+mcp|hub\s+mcp)\b", clean):
        return ["sync"]
    if re.search(r"(?i)\b(?:agent\s+hub|hub)\b.*\b(?:status|state)\b", clean):
        return ["status"]
    if re.search(r"(?i)\b(?:agent\s+hub|hub)\b.*\b(?:doctor|health|check)\b", clean):
        return ["doctor"]
    if re.search(r"(?i)\b(?:list|show)\b.*\b(?:ollama\s+)?(?:launch\s+)?agents?\b", clean):
        return ["list"]
    if re.search(r"(?i)\b(?:shared|common)\s+mcp\b.*\b(?:agents?|hub)\b", clean):
        return ["status"]
    if lower in {"agent hub", "agent hub list", "agent hub status", "agent hub sync", "agent hub doctor"}:
        return ["list"] if lower.endswith("list") else [lower.split()[-1]]

    m = re.search(
        r"(?i)\b(?:launch|start|run|open)\b.*\b("
        + "|".join(re.escape(k) for k in AGENTS)
        + r"|claude\s+code|codex\s+app|github\s+copilot)\b",
        clean,
    )
    if m:
        target = m.group(1).lower().replace(" ", "-")
        if "claude" in target:
            return ["launch", "claude"]
        if "codex" in target and "app" in lower:
            return ["launch", "codex-app"]
        if "copilot" in target:
            return ["launch", "copilot"]
        return ["launch", target.replace(" ", "-")]

    m = re.search(r"(?i)\bollama\s+launch\s+([a-z0-9_-]+)", clean)
    if m:
        return ["launch", m.group(1)]

    if re.search(r"(?i)\blaunch\s+claude\s+code\b", clean):
        return ["launch", "claude"]

    return None


__all__ = [
    "AGENTS",
    "doctor",
    "format_agent_list",
    "format_doctor",
    "format_status",
    "hub_dir",
    "hub_mcp_path",
    "hub_memory_dir",
    "launch_agent",
    "launch_env",
    "list_agents",
    "nl_to_argv",
    "ollama_available",
    "sync_all",
    "sync_mcp",
    "sync_memory",
    "sync_skills",
]
