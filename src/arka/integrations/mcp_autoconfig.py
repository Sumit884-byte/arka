"""Curated, credential-aware MCP catalog and safe auto-configuration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

CATALOG = {
    "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."], "requires": ()},
    "fetch": {"command": "uvx", "args": ["mcp-server-fetch"], "requires": ()},
    "github": {"command": "docker", "args": ["run", "--rm", "-i", "ghcr.io/github/github-mcp-server"], "requires": ("GITHUB_TOKEN",)},
    "context7": {"command": "npx", "args": ["-y", "@upstash/context7-mcp"], "requires": ()},
    "postgres": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres", "${DATABASE_URL}"], "requires": ("DATABASE_URL",)},
    "sqlite": {"command": "uvx", "args": ["mcp-server-sqlite", "--db-path", "./data.db"], "requires": ()},
    "time": {"command": "uvx", "args": ["mcp-server-time"], "requires": ()},
    "puppeteer": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-puppeteer"], "requires": ()},
    "docker": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-docker"], "requires": ()},
    "git": {"command": "uvx", "args": ["mcp-server-git", "--repository", "."], "requires": ()},
    "memory": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"], "requires": ()},
    "sequential-thinking": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"], "requires": ()},
    "everything": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"], "requires": ()},
    "brave-search": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-brave-search"], "requires": ("BRAVE_API_KEY",)},
    "slack": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-slack"], "requires": ("SLACK_BOT_TOKEN",)},
    "notion": {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"], "requires": ("NOTION_TOKEN",)},
}

def _path() -> Path:
    from arka.integrations.agent_hub import hub_mcp_path
    return hub_mcp_path()

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka mcp auto")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    add = sub.add_parser("configure")
    add.add_argument("names", nargs="*", choices=sorted(CATALOG))
    add.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "list":
        for name, spec in CATALOG.items():
            ready = all(os.environ.get(key) for key in spec["requires"])
            print(f"{name}\t{'ready' if ready else 'needs credentials'}")
        return 0
    selected = args.names or list(CATALOG)
    path = _path()
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
        except (OSError, ValueError):
            pass
    additions = {name: {key: value for key, value in CATALOG[name].items() if key != "requires"} for name in selected if name not in existing and all(os.environ.get(key) for key in CATALOG[name]["requires"])}
    for name in selected:
        status = "configured" if name in additions else "skipped (credentials or existing entry)"
        print(f"candidate\t{name}\t{status}")
    if not args.apply:
        print("preview\tpass --apply to update the Agent Hub MCP config")
        return 0
    merged = dict(existing)
    merged.update(additions)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": merged}, indent=2) + "\n", encoding="utf-8")
    print(f"applied\t{len(additions)}\t{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
