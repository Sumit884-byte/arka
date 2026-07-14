"""Arka Agent Hub — shared MCP, memory, and skills for ollama launch agents."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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
            "~/.config/Claude/claude_desktop_config.json",
        ],
        "mcp_merge_key": "mcpServers",
        "memory_hint": "Read ARKA_MEMORY_DIR/context.md or summary.json for Arka facts",
        "skills_path_var": "ARKA_SKILLS_DIR",
    },
    "codex-app": {
        "name": "Codex App",
        "ollama_launch": "codex-app",
        "aliases": ["codex app"],
        "mcp_paths": ["~/.codex/mcp.json"],
        "mcp_merge_key": "mcpServers",
        "memory_hint": "Set ARKA_MEMORY_DIR; read context.md for cross-agent context",
        "skills_path_var": "ARKA_SKILLS_DIR",
    },
    "hermes": {
        "name": "Hermes Agent",
        "ollama_launch": "hermes",
        "aliases": [],
        "mcp_paths": ["~/.config/hermes/mcp.json"],
        "mcp_merge_key": "mcpServers",
        "memory_hint": "Channel sessions in ARKA_MEMORY_DIR/sessions_index.json",
    },
    "openclaw": {
        "name": "OpenClaw",
        "ollama_launch": "openclaw",
        "aliases": [],
        "mcp_paths": ["~/.openclaw/mcp.json", "~/.config/openclaw/mcp.json"],
        "mcp_merge_key": "mcpServers",
        "memory_hint": "Read ARKA_CONTEXT_MD or hub/memory/context.md",
        "memory_paths": ["~/.openclaw/MEMORY.md", "~/.config/openclaw/MEMORY.md"],
        "env_vars": {"OPENCLAW_MCP_CONFIG": "ARKA_MCP_CONFIG"},
    },
    "opencode": {
        "name": "OpenCode",
        "ollama_launch": "opencode",
        "aliases": ["open code"],
        "mcp_paths": ["~/.config/opencode/mcp.json"],
        "mcp_merge_key": "mcpServers",
        "memory_hint": "Use ARKA_MCP_CONFIG for shared MCP servers",
    },
    "codex": {
        "name": "Codex CLI",
        "ollama_launch": "codex",
        "aliases": [],
        "mcp_paths": ["~/.codex/mcp.json"],
        "mcp_merge_key": "mcpServers",
        "memory_hint": "Set MCP_CONFIG or ARKA_MCP_CONFIG to hub/mcp.json",
        "skills_path_var": "ARKA_SKILLS_DIR",
    },
    "fugu": {
        "name": "Sakana Fugu",
        "ollama_launch": "codex",
        "aliases": ["sakana", "sakana fugu"],
        "mcp_paths": ["~/.codex/mcp.json"],
        "mcp_merge_key": "mcpServers",
        "memory_hint": "Orchestrator via Codex -p fugu; read ARKA_CONTEXT_MD or hub/memory/context.md",
        "skills_path_var": "ARKA_SKILLS_DIR",
        "env_vars": {"SAKANA_API_KEY": "SAKANA_API_KEY"},
    },
    "copilot": {
        "name": "GitHub Copilot Agent",
        "ollama_launch": "copilot",
        "aliases": ["github copilot"],
        "mcp_paths": ["~/.copilot/mcp.json"],
        "mcp_merge_key": "mcpServers",
        "memory_hint": "Read ARKA_SKILLS_MANIFEST for Arka plugins",
        "skills_path_var": "ARKA_SKILLS_DIR",
    },
    "droid": {
        "name": "Droid",
        "ollama_launch": "droid",
        "aliases": [],
        "mcp_paths": ["~/.config/droid/mcp.json"],
        "mcp_merge_key": "mcpServers",
        "memory_hint": "Use ARKA_HUB_DIR as shared config root",
    },
    "pi": {
        "name": "Pi Agent",
        "ollama_launch": "pi",
        "aliases": [],
        "mcp_paths": ["~/.pi/mcp.json", "~/.config/pi/mcp.json"],
        "mcp_merge_key": "mcpServers",
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


def hub_launch_env_path() -> Path:
    return hub_dir() / "launch.env"


def hub_context_md_path() -> Path:
    return hub_memory_dir() / "context.md"


def _expand_config_paths(paths: list[str] | None) -> list[Path]:
    return [Path(p).expanduser() for p in (paths or []) if str(p).strip()]


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _hub_mcp_servers() -> dict[str, Any]:
    return _load_json_file(hub_mcp_path()).get("mcpServers") or {}


def _merge_mcp_servers(
    existing: dict[str, Any],
    hub_servers: dict[str, Any],
    *,
    replace: bool,
) -> dict[str, Any]:
    if replace:
        return dict(hub_servers)
    merged = dict(existing)
    for name, cfg in hub_servers.items():
        if name not in merged:
            merged[name] = cfg
    return merged


def _mcp_merge_status(path: Path, hub_servers: dict[str, Any], merge_key: str) -> dict[str, Any]:
    existing = _load_json_file(path)
    current = existing.get(merge_key) or {}
    if not isinstance(current, dict):
        current = {}
    missing = [k for k in hub_servers if k not in current]
    extra = [k for k in current if k not in hub_servers]
    return {
        "path": str(path),
        "exists": path.is_file(),
        "hub_server_count": len(hub_servers),
        "local_server_count": len(current),
        "missing_servers": missing,
        "extra_servers": extra,
        "fully_merged": path.is_file() and not missing,
    }


def merge_mcp_into_path(
    path: Path,
    hub_servers: dict[str, Any],
    *,
    merge_key: str = "mcpServers",
    create: bool = True,
    replace: bool = False,
) -> dict[str, Any]:
    """Merge hub mcpServers into an agent config file (add-only unless replace)."""
    result: dict[str, Any] = {
        "path": str(path),
        "ok": False,
        "created": False,
        "merged_servers": [],
    }
    if not hub_servers:
        result["ok"] = True
        result["detail"] = "no hub servers"
        return result

    existing = _load_json_file(path)
    current = existing.get(merge_key) or {}
    if not isinstance(current, dict):
        current = {}

    if not path.is_file() and not create:
        result["detail"] = "missing"
        return result

    merged_servers = _merge_mcp_servers(current, hub_servers, replace=replace)
    added = [k for k in merged_servers if k not in current]
    result["merged_servers"] = added

    try:
        payload = {**existing, merge_key: merged_servers}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        result["detail"] = str(exc)
        return result
    result["ok"] = True
    result["created"] = not bool(current)
    result["detail"] = f"added {len(added)} server(s)"
    return result


def detect_agents() -> list[dict[str, Any]]:
    """Probe filesystem for which agent MCP configs exist on this machine."""
    hub_servers = _hub_mcp_servers()
    rows: list[dict[str, Any]] = []
    for agent_key, meta in list_agents():
        paths = _expand_config_paths(meta.get("mcp_paths"))
        memory_paths = _expand_config_paths(meta.get("memory_paths"))
        config_rows: list[dict[str, Any]] = []
        for path in paths:
            status = _mcp_merge_status(path, hub_servers, meta.get("mcp_merge_key", "mcpServers"))
            config_rows.append(status)
        rows.append(
            {
                "agent": agent_key,
                "name": meta.get("name", agent_key),
                "mcp_configs": config_rows,
                "mcp_config_exists": any(r["exists"] for r in config_rows),
                "memory_paths": [str(p) for p in memory_paths if p.is_file()],
            }
        )
    return rows


def unify_mcp(*, replace: bool = False) -> list[dict[str, Any]]:
    """Merge hub MCP into every known agent config path (create if missing)."""
    hub_servers = _hub_mcp_servers()
    rows: list[dict[str, Any]] = []
    for agent_key, meta in list_agents():
        merge_key = meta.get("mcp_merge_key", "mcpServers")
        for path in _expand_config_paths(meta.get("mcp_paths")):
            row = merge_mcp_into_path(
                path,
                hub_servers,
                merge_key=merge_key,
                create=True,
                replace=replace,
            )
            row["agent"] = agent_key
            rows.append(row)
    return rows


def list_adapters() -> list[dict[str, Any]]:
    """List per-agent MCP merge status (what exists and what would merge)."""
    hub_servers = _hub_mcp_servers()
    rows: list[dict[str, Any]] = []
    for agent_key, meta in list_agents():
        merge_key = meta.get("mcp_merge_key", "mcpServers")
        for path in _expand_config_paths(meta.get("mcp_paths")):
            status = _mcp_merge_status(path, hub_servers, merge_key)
            status["agent"] = agent_key
            status["agent_name"] = meta.get("name", agent_key)
            status["would_add"] = status["missing_servers"]
            rows.append(status)
    for label, target in ADAPTER_TARGETS.items():
        status = _mcp_merge_status(target, hub_servers, "mcpServers")
        status["agent"] = label
        status["agent_name"] = f"adapter:{label}"
        status["would_add"] = status["missing_servers"]
        rows.append(status)
    return rows


def _sanitize_import_text(text: str) -> tuple[str, str | None]:
    text = " ".join((text or "").split()).strip()
    if not text:
        return "", "empty"
    try:
        from arka.core.unified_memory import _sanitize_text

        return _sanitize_text(text)
    except ImportError:
        pass
    try:
        from arka.core.security import sanitize_llm_context, verify_user_prompt

        gate = verify_user_prompt(text)
        if gate.status == "block":
            return "", gate.reason
        cleaned, _ = sanitize_llm_context(text)
        return (cleaned or text).strip(), None
    except ImportError:
        return text, None


def _import_fact(text: str) -> tuple[bool, str | None]:
    cleaned, err = _sanitize_import_text(text)
    if err:
        return False, err
    if not cleaned:
        return False, "empty"
    try:
        from arka.agent.core import memory_remember_silent

        if memory_remember_silent(
            cleaned,
            source="agent_hub_import",
            trust_tier="global",
            provenance={"source": "agent_hub_import", "trust_tier": "global"},
        ):
            return True, None
    except ImportError:
        pass
    return False, "memory store unavailable"


def _import_note(text: str, *, long_term: bool = False) -> tuple[bool, str | None]:
    cleaned, err = _sanitize_import_text(text)
    if err:
        return False, err
    if not cleaned:
        return False, "empty"
    try:
        from arka.core.session_memory import append

        code = append(cleaned, long_term=long_term)
        return code == 0, None if code == 0 else "append failed"
    except ImportError:
        return False, "session_memory unavailable"


def import_memory(path: Path) -> dict[str, Any]:
    """Ingest JSON or markdown memory export back into Arka memory layers."""
    src = path.expanduser().resolve()
    result: dict[str, Any] = {
        "source": str(src),
        "ok": False,
        "facts_imported": 0,
        "notes_imported": 0,
        "errors": [],
    }
    if not src.is_file():
        result["errors"].append("file not found")
        return result

    raw = src.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        result["errors"].append("empty file")
        return result

    if src.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            result["errors"].append(str(exc))
            return result
        if isinstance(data, dict):
            for row in data.get("facts") or []:
                text = row.get("text") if isinstance(row, dict) else str(row)
                ok, err = _import_fact(str(text or ""))
                if ok:
                    result["facts_imported"] += 1
                elif err and err != "empty":
                    result["errors"].append(f"fact: {err}")
            for note in data.get("long_term_notes") or []:
                ok, err = _import_note(str(note), long_term=True)
                if ok:
                    result["notes_imported"] += 1
                elif err and err != "empty":
                    result["errors"].append(f"note: {err}")
        result["ok"] = bool(result["facts_imported"] or result["notes_imported"])
        return result

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if stripped.startswith("[") and "]" in stripped:
            stripped = stripped.split("]", 1)[-1].strip()
        if not stripped:
            continue
        ok, err = _import_note(stripped, long_term=True)
        if ok:
            result["notes_imported"] += 1
        elif err and err != "empty":
            result["errors"].append(f"line: {err}")

    result["ok"] = result["notes_imported"] > 0
    return result


def _write_context_md(summary: dict[str, Any]) -> Path:
    mem_dir = hub_memory_dir()
    mem_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Arka Agent Hub — shared context",
        "",
        f"_Exported: {summary.get('exported_at', 'unknown')}_",
        "",
    ]
    facts = summary.get("facts") or []
    if facts:
        lines.append("## Facts")
        lines.append("")
        for row in facts:
            text = row.get("text") if isinstance(row, dict) else str(row)
            when = row.get("when") if isinstance(row, dict) else None
            tier = row.get("trust_tier") if isinstance(row, dict) else "global"
            suffix = f" _({when}, {tier})_" if when else f" _({tier})_"
            lines.append(f"- {text}{suffix}")
        lines.append("")

    scratch = summary.get("scratchpad_preview") or []
    if scratch:
        lines.append("## Workflow scratchpad (scoped)")
        lines.append("")
        for row in scratch:
            if not isinstance(row, dict):
                continue
            prov = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
            label = prov.get("team") or prov.get("workflow") or "scratchpad"
            lines.append(f"- [{label}] {str(row.get('text') or '')[:200]}")
        lines.append("")

    notes = summary.get("long_term_notes") or []
    if notes:
        lines.append("## Session notes")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    sessions = summary.get("sessions") or []
    if sessions:
        lines.append("## Recent sessions")
        lines.append("")
        for sess in sessions[:5]:
            if isinstance(sess, dict):
                label = sess.get("label") or sess.get("id") or sess.get("channel") or "session"
                lines.append(f"- {label}")
            else:
                lines.append(f"- {sess}")
        lines.append("")

    lines.append("## Load instructions")
    lines.append("")
    lines.append("- JSON: `ARKA_MEMORY_DIR/summary.json`")
    lines.append("- Markdown: `ARKA_CONTEXT_MD` or `hub/memory/context.md`")
    lines.append("- Skills: `ARKA_SKILLS_MANIFEST`")
    path = mem_dir / "context.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_memory_readme() -> Path:
    mem_dir = hub_memory_dir()
    mem_dir.mkdir(parents=True, exist_ok=True)
    text = """# Arka Hub Memory

Exports from Arka unified memory for cross-agent context.

## Files

| File | Format | Use |
| ---- | ------ | --- |
| `summary.json` | JSON | Facts, session index, memory status |
| `context.md` | Markdown | Human-readable bundle for agents that read files |
| `sessions_index.json` | JSON | Recent channel sessions |
| `skills_manifest.json` | JSON | Copy of skills manifest for memory-aware agents |

## Per-agent loading

| Agent | Recommended |
| ----- | ----------- |
| Claude Code / Cursor | `ARKA_CONTEXT_MD` or read `context.md` at session start |
| OpenClaw | Sync `MEMORY.md` tail via `agent_hub sync --unify`; read `context.md` |
| Hermes | `sessions_index.json` for channel continuity |
| Codex / Copilot | `summary.json` facts + `ARKA_SKILLS_MANIFEST` |

## Import back into Arka

```bash
arka agent_hub import-memory path/to/export.json
arka agent_hub import-memory path/to/notes.md
```

Imported text passes through Arka security gates before writing to unified memory.

## Scoped export (edge / ClawBox)

Set on Jetson or always-on devices to limit what the hub exports:

```env
ARKA_MEMORY_TRUST_MAX=team
ARKA_HUB_MEMORY_SCOPE=team:clawbox
```

Use `agent_hub sync` (export-only) on edge — avoid `sync --unify` unless you intend to merge MCP into agent configs.
"""
    path = mem_dir / "README.md"
    path.write_text(text, encoding="utf-8")
    return path


def _sync_openclaw_memory_tail() -> dict[str, Any] | None:
    meta = AGENTS.get("openclaw") or {}
    for src in _expand_config_paths(meta.get("memory_paths")):
        if not src.is_file():
            continue
        lines = [ln.strip() for ln in src.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        tail = lines[-20:]
        if not tail:
            continue
        dst = hub_memory_dir() / "openclaw_memory_tail.md"
        hub_memory_dir().mkdir(parents=True, exist_ok=True)
        dst.write_text("\n".join(f"- {ln.lstrip('- ').strip()}" for ln in tail) + "\n", encoding="utf-8")
        return {"source": str(src), "destination": str(dst), "lines": len(tail)}
    return None


def _write_skills_install(manifest: dict[str, Any]) -> Path:
    skills_dir = hub_skills_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)
    skills = manifest.get("skills") or []
    lines = [
        "# Arka Hub Skills",
        "",
        "Installed Arka skills exported for cross-agent use.",
        "",
        "## Manifest",
        "",
        f"Path: `{skills_dir / 'manifest.json'}`",
        f"Count: {manifest.get('count', len(skills))}",
        "",
        "## Environment",
        "",
        "Agents that support plugin directories should read:",
        "",
        "```bash",
        f"export ARKA_SKILLS_MANIFEST={skills_dir / 'manifest.json'}",
        f"export ARKA_SKILLS_DIR={skills_dir}",
        "```",
        "",
        "## Skills",
        "",
    ]
    for sk in skills:
        name = sk.get("name", "unknown")
        desc = sk.get("description", "")
        sk_path = sk.get("path", "")
        sk_type = sk.get("type", "")
        lines.append(f"### {name}")
        if desc:
            lines.append(desc)
        if sk_path:
            lines.append(f"- Path: `{sk_path}`")
        if sk_type:
            lines.append(f"- Type: {sk_type}")
        triggers = sk.get("triggers") or []
        if triggers:
            lines.append(f"- Triggers: {', '.join(triggers)}")
        lines.append("")
    path = skills_dir / "INSTALL.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_launch_env_file(agent_key: str = "") -> Path:
    """Write hub/launch.env — sourceable env contract for any agent."""
    env = launch_env(agent_key) if agent_key else launch_env("claude")
    skills_manifest = str(hub_skills_dir() / "manifest.json")
    skills_dir = str(hub_skills_dir())
    context_md = str(hub_context_md_path())
    env.update(
        {
            "ARKA_SKILLS_MANIFEST": skills_manifest,
            "ARKA_SKILLS_DIR": skills_dir,
            "ARKA_CONTEXT_MD": context_md,
        }
    )
    if agent_key:
        meta = AGENTS.get(agent_key) or {}
        for src_var, dst_var in (meta.get("env_vars") or {}).items():
            if dst_var in env:
                env[src_var] = env[dst_var]
        skills_var = meta.get("skills_path_var")
        if skills_var:
            env[skills_var] = skills_dir

    lines = ["# Arka Agent Hub launch environment", "# source this file: . hub/launch.env", ""]
    for key in sorted(env):
        val = env[key].replace('"', '\\"')
        lines.append(f'export {key}="{val}"')
    path = hub_launch_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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
    from arka.integrations.context7_mcp import (
        CONTEXT7_MCP_SERVER_KEY,
        context7_mcp_launch_spec,
        ensure_context7_in_config,
    )
    from arka.integrations.mcp_manager import load_mcp_config, mcp_config_path
    from arka.integrations.mcp_server import ARKA_MCP_SERVER_KEY, ensure_arka_self_in_config, mcp_server_launch_spec

    src = mcp_config_path()
    dst = hub_mcp_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"source": str(src), "destination": str(dst), "ok": False}

    if ensure_context7_in_config():
        result["context7_mcp"] = "added_to_source"
    if ensure_arka_self_in_config():
        result["arka_self_mcp"] = "added_to_source"

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
    hub_data = _load_json_file(dst)
    hub_servers = hub_data.setdefault("mcpServers", {})
    changed = False
    if CONTEXT7_MCP_SERVER_KEY not in hub_servers:
        hub_servers[CONTEXT7_MCP_SERVER_KEY] = context7_mcp_launch_spec()
        changed = True
        result["context7_mcp"] = result.get("context7_mcp", "merged_into_hub")
    if ARKA_MCP_SERVER_KEY not in hub_servers:
        hub_servers[ARKA_MCP_SERVER_KEY] = mcp_server_launch_spec()
        changed = True
        result["arka_self_mcp"] = result.get("arka_self_mcp", "merged_into_hub")
    if changed:
        dst.write_text(json.dumps(hub_data, indent=2) + "\n", encoding="utf-8")
    result["ok"] = True
    result["mode"] = "copy"
    return result


def _hub_fact_allowed(row: dict[str, Any]) -> bool:
    try:
        from arka.core.memory_scope import (
            TIER_ORDER,
            fact_provenance,
            fact_trust_tier,
            hub_memory_scope,
            trust_max_tier,
        )

        tier = fact_trust_tier(row)
        cap = trust_max_tier()
        if TIER_ORDER.get(tier, 99) > TIER_ORDER.get(cap, 0):
            return False
        hub = hub_memory_scope()
        if hub and hub[0] == "team":
            prov = fact_provenance(row)
            if tier != "global" and prov.team and prov.team != hub[1]:
                return False
        return True
    except ImportError:
        return True


def _export_memory_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {
        "exported_at": _iso_now(),
        "facts": [],
        "facts_status": {},
        "notes_status": {},
        "sessions": [],
        "scratchpad_preview": [],
    }

    try:
        from arka.core.memory_scope import list_scratchpad, scope_status

        summary["scope"] = scope_status()
        hub = scope_status().get("hub_scope")
        team_filter = ""
        if hub and isinstance(hub, str) and hub.startswith("team:"):
            team_filter = hub.split(":", 1)[-1]
        scratch_rows = list_scratchpad(team=team_filter, limit=10) if team_filter else list_scratchpad(limit=10)
        for row in scratch_rows:
            prov = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
            summary["scratchpad_preview"].append(
                {
                    "id": row.get("id"),
                    "text": str(row.get("text") or "")[:500],
                    "trust_tier": row.get("trust_tier"),
                    "provenance": prov,
                    "expires_at": row.get("expires_at"),
                }
            )
    except ImportError:
        pass

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
                for row in raw[-40:]:
                    if isinstance(row, dict):
                        if not _hub_fact_allowed(row):
                            continue
                        text = str(row.get("text") or "").strip()
                        if text:
                            fact_row: dict[str, Any] = {
                                "text": text[:500],
                                "when": row.get("when"),
                                "trust_tier": row.get("trust_tier", "global"),
                            }
                            if row.get("provenance"):
                                fact_row["provenance"] = row.get("provenance")
                            if row.get("source"):
                                fact_row["source"] = row.get("source")
                            summary["facts"].append(fact_row)
                summary["facts"] = summary["facts"][-20:]
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
    context_path = _write_context_md(summary)
    readme_path = _write_memory_readme()
    return {
        "ok": True,
        "summary": str(summary_path),
        "context_md": str(context_path),
        "readme": str(readme_path),
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
    install_path = _write_skills_install(manifest)
    return {
        "ok": True,
        "manifest": str(manifest_path),
        "install_md": str(install_path),
        "count": len(skills),
    }


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


def sync_all(
    *,
    force_adapters: bool = False,
    use_symlink: bool = False,
    unify: bool = False,
    replace: bool = False,
) -> dict[str, Any]:
    hub_dir().mkdir(parents=True, exist_ok=True)
    now = _iso_now()
    results: dict[str, Any] = {
        "mcp": sync_mcp(use_symlink=use_symlink),
        "memory": sync_memory(),
        "skills": sync_skills(),
        "adapters": write_adapter_snippets(force=force_adapters or (unify and replace)),
        "launch_env": str(write_launch_env_file()),
        "synced_at": now,
        "unified": unify,
    }

    if unify:
        results["unify_mcp"] = unify_mcp(replace=replace)
        openclaw_tail = _sync_openclaw_memory_tail()
        if openclaw_tail:
            results["openclaw_memory"] = openclaw_tail

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
    if unify:
        last_sync["unify"] = now
    registry["last_sync"] = last_sync
    registry["version"] = 2
    results["registry"] = str(_save_agents_registry(registry))
    return results


def launch_env(agent_key: str) -> dict[str, str]:
    hdir = str(hub_dir())
    mcp = str(hub_mcp_path())
    mem = str(hub_memory_dir())
    skills_manifest = str(hub_skills_dir() / "manifest.json")
    skills_dir = str(hub_skills_dir())
    context_md = str(hub_context_md_path())
    env = {
        "ARKA_HUB_DIR": hdir,
        "ARKA_MCP_CONFIG": mcp,
        "ARKA_MEMORY_DIR": mem,
        "MCP_CONFIG": mcp,
        "ARKA_SKILLS_MANIFEST": skills_manifest,
        "ARKA_SKILLS_DIR": skills_dir,
        "ARKA_CONTEXT_MD": context_md,
    }
    meta = AGENTS.get(agent_key) or {}
    env["ARKA_AGENT_NAME"] = str(meta.get("name") or agent_key)
    env["ARKA_AGENT_LAUNCH"] = str(meta.get("ollama_launch") or agent_key)
    for src_var, dst_var in (meta.get("env_vars") or {}).items():
        if dst_var in env:
            env[src_var] = env[dst_var]
    skills_var = meta.get("skills_path_var")
    if skills_var:
        env[skills_var] = skills_dir
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

    launch_env_path = hub_launch_env_path()
    checks.append(
        {
            "name": "hub_launch_env",
            "ok": launch_env_path.is_file(),
            "detail": str(launch_env_path),
        }
    )

    context_md = hub_context_md_path()
    checks.append(
        {
            "name": "hub_context_md",
            "ok": context_md.is_file(),
            "detail": str(context_md),
        }
    )

    registry = _load_agents_registry()
    last_unify = (registry.get("last_sync") or {}).get("unify")
    hub_servers = _hub_mcp_servers()
    for agent_key, meta in list_agents():
        paths = _expand_config_paths(meta.get("mcp_paths"))
        existing = [p for p in paths if p.is_file()]
        merge_key = meta.get("mcp_merge_key", "mcpServers")
        merged_count = 0
        for path in existing:
            status = _mcp_merge_status(path, hub_servers, merge_key)
            if status.get("fully_merged"):
                merged_count += 1
        detail = f"configs={len(existing)}/{len(paths)} merged={merged_count}"
        if last_unify:
            detail += f" last_unify={last_unify}"
        checks.append(
            {
                "name": f"unify_{agent_key}",
                "ok": bool(existing) and merged_count == len(existing) if existing else True,
                "detail": detail,
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


def status_payload() -> dict[str, Any]:
    """Structured Agent Hub status for MCP / automation clients."""
    registry = _load_agents_registry()
    last_sync = registry.get("last_sync") or {}
    return {
        "hub": str(hub_dir()),
        "mcp": str(hub_mcp_path()),
        "memory": str(hub_memory_dir()),
        "skills": str(hub_skills_dir() / "manifest.json"),
        "registry": str(hub_agents_json_path()),
        "launch_env": str(hub_launch_env_path()),
        "context_md": str(hub_context_md_path()),
        "agent_count": len(AGENTS),
        "last_sync": last_sync,
        "ollama_available": ollama_available(),
        "agents": [
            {
                "key": key,
                "name": meta.get("name", key),
                "ollama_launch": meta.get("ollama_launch", key),
            }
            for key, meta in list_agents()
        ],
    }


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
    unify_ts = last_sync.get("unify")
    lines.append(f"sync_unify\t{unify_ts or 'never'}")
    lines.append(f"launch_env\t{hub_launch_env_path()}")
    lines.append(f"context_md\t{hub_context_md_path()}")
    lines.append("")
    lines.append("Configured ollama agents:")
    for key, meta in list_agents():
        lines.append(f"  {key}\t{meta.get('name')}\tollama launch {meta.get('ollama_launch')}")
    lines.append("")
    lines.append("MCP adapter targets (use sync --unify to merge):")
    for row in list_adapters()[:12]:
        status = "merged" if row.get("fully_merged") else "pending"
        missing = len(row.get("missing_servers") or [])
        lines.append(
            f"  {row.get('agent')}\t{row.get('path')}\t{status}\tmissing={missing}"
        )
    return "\n".join(lines)


def format_adapters() -> str:
    lines = [f"hub\t{hub_dir()}", f"hub_servers\t{len(_hub_mcp_servers())}", ""]
    for row in list_adapters():
        status = "merged" if row.get("fully_merged") else "pending"
        would_add = ",".join(row.get("would_add") or []) or "-"
        lines.append(
            f"{row.get('agent')}\t{status}\t{row.get('path')}\twould_add={would_add}"
        )
    return "\n".join(lines)


def format_detect() -> str:
    lines = [f"hub\t{hub_dir()}", ""]
    for row in detect_agents():
        configs = row.get("mcp_configs") or []
        existing = sum(1 for c in configs if c.get("exists"))
        lines.append(f"{row.get('agent')}\tconfigs={existing}/{len(configs)}")
        for cfg in configs:
            if cfg.get("exists"):
                missing = len(cfg.get("missing_servers") or [])
                lines.append(f"  {cfg.get('path')}\tmissing={missing}")
        for mem in row.get("memory_paths") or []:
            lines.append(f"  memory\t{mem}")
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

    if re.search(r"(?i)\b(?:detect|probe|scan)\b.*\b(?:agent\s+hub|arka\s+hub|hub)\b", clean):
        return ["detect"]
    if re.search(r"(?i)\b(?:agent\s+hub|arka\s+hub)\b.*\b(?:detect|probe|scan)\b", clean):
        return ["detect"]
    if re.search(r"(?i)\b(?:agent\s+hub|hub)\b.*\b(?:adapters?|merge)\b", clean):
        return ["adapters"]
    if re.search(r"(?i)\b(?:import|ingest)\b.*\b(?:hub\s+)?memory\b", clean):
        return None
    if re.search(r"(?i)\b(?:agent\s+hub|arka\s+hub)\b.*\b(?:sync|refresh|update)\b", clean):
        return ["sync"]
    if re.search(r"(?i)\b(?:sync|refresh)\b.*\b(?:agent\s+hub|shared\s+mcp|hub\s+mcp)\b", clean):
        return ["sync"]
    if re.search(r"(?i)\b(?:agent\s+hub|hub)\b.*\b(?:status|state)\b", clean):
        return ["status"]
    if re.search(r"(?i)\b(?:agent\s+hub|hub)\b.*\b(?:doctor|health|check)\b", clean):
        return ["doctor"]
    if re.search(r"(?i)\b(?:list|show)\b.*\b(?:ollama\s+)?(?:launch\s+)?agents?\b", clean):
        if re.search(r"(?i)\bheartbeat\b", clean):
            return None
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
    "detect_agents",
    "doctor",
    "format_adapters",
    "format_agent_list",
    "format_detect",
    "format_doctor",
    "format_status",
    "hub_dir",
    "hub_mcp_path",
    "hub_memory_dir",
    "import_memory",
    "launch_agent",
    "launch_env",
    "list_adapters",
    "list_agents",
    "merge_mcp_into_path",
    "nl_to_argv",
    "ollama_available",
    "sync_all",
    "sync_mcp",
    "sync_memory",
    "sync_skills",
    "unify_mcp",
    "write_launch_env_file",
]
