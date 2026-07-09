"""Cursor + SigNoz Agent Skills setup helper."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _cursor_dir() -> Path:
    return _repo_root() / ".cursor"


def _mcp_example() -> Path:
    return _cursor_dir() / "mcp.json.example"


def _mcp_target() -> Path:
    return _cursor_dir() / "mcp.json"


def cursor_setup_lines(*, write: bool = False) -> list[str]:
    from arka.telemetry.mcp_obs import mcp_api_key, mcp_server_url
    from arka.telemetry.signoz_setup import signoz_mcp_status

    mcp_base = os.environ.get("SIGNOZ_MCP_URL", "http://localhost:8000").strip().rstrip("/")
    livez = signoz_mcp_status(mcp_base)
    key = mcp_api_key()
    mcp_url = mcp_server_url("signoz")

    lines = [
        "cursor_plugin\tSigNoz/agent-skills (Team Marketplace — recommended)",
        "cursor_marketplace\thttps://github.com/SigNoz/agent-skills",
        "cursor_plugin_name\tsignoz",
        "cursor_setup_cmd\t/signoz-mcp-setup http://localhost:8000/mcp",
        f"signoz_mcp_livez\t{livez}",
        f"signoz_mcp_url\t{mcp_url}",
        f"signoz_api_key\t{'set' if key else 'not_set'}",
        f"mcp_json\t{_mcp_target()}",
        "docs\thackathon/signoz/CURSOR_AGENT_SKILLS.md",
        "official\thttps://signoz.io/docs/ai/agent-skills/?agent-client=cursor",
    ]

    if write:
        _cursor_dir().mkdir(parents=True, exist_ok=True)
        example = _mcp_example()
        if example.is_file():
            payload = json.loads(example.read_text(encoding="utf-8"))
        else:
            payload = {
                "mcpServers": {
                    "signoz": {
                        "url": mcp_url,
                        "headers": {"SIGNOZ-API-KEY": "<your-signoz-api-key>"},
                    }
                }
            }
        headers = payload.setdefault("mcpServers", {}).setdefault("signoz", {}).setdefault("headers", {})
        if key:
            headers["SIGNOZ-API-KEY"] = key
        payload["mcpServers"]["signoz"]["url"] = mcp_url
        _mcp_target().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        lines.append(f"written\t{_mcp_target()}")

    return lines


def cmd_cursor_setup(args) -> int:
    from arka.telemetry.mcp_obs import mcp_api_key

    write = bool(getattr(args, "write", False))
    if write and not mcp_api_key():
        print("hint\tSet SIGNOZ_API_KEY in .env before --write", file=sys.stderr)

    for line in cursor_setup_lines(write=write):
        print(line)

    print("", file=sys.stderr)
    print("Cursor Agent Skills (recommended):", file=sys.stderr)
    print("  1. Settings → Plugins → add Team Marketplace: https://github.com/SigNoz/agent-skills", file=sys.stderr)
    print("  2. Install plugin: signoz", file=sys.stderr)
    print("  3. In Agent chat: /signoz-mcp-setup http://localhost:8000/mcp", file=sys.stderr)
    print("  4. Reload Cursor → Settings → MCP → authenticate signoz", file=sys.stderr)
    print("", file=sys.stderr)
    print("Fallback: arka signoz cursor-setup --write  (manual .cursor/mcp.json)", file=sys.stderr)
    print("Docs: hackathon/signoz/CURSOR_AGENT_SKILLS.md", file=sys.stderr)
    return 0
