#!/usr/bin/env python3
"""Generic MCP server management for Arka — list, add, tools, call, status."""

from __future__ import annotations

import argparse
import json
import sys

from arka.integrations.mcp_manager import (
    MCP_SDK_INSTALL_HINT,
    add_server,
    all_status,
    call_tool,
    format_server_list,
    list_server_names,
    list_tools,
    mcp_config_path,
    mcp_sdk_available,
    remove_server,
    server_status,
)


def _parse_headers(values: list[str] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"Header must be KEY=VALUE, got: {raw!r}")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Header key missing in: {raw!r}")
        headers[key] = value
    return headers


def cmd_list(_args: argparse.Namespace) -> int:
    print(format_server_list())
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    name = args.name.strip()
    if not name:
        print("Server name is required", file=sys.stderr)
        return 1
    try:
        headers = _parse_headers(args.header)
        if args.url:
            add_server(name, url=args.url, headers=headers)
            print(f"added\t{name}\thttp\t{args.url}")
        else:
            if not args.command:
                print("Usage: arka mcp add <name> <command> [args...]", file=sys.stderr)
                print("   or: arka mcp add <name> --url <url>", file=sys.stderr)
                return 1
            add_server(name, command=args.command, args=list(args.args or []), headers=headers)
            cmd = " ".join([args.command, *(args.args or [])])
            print(f"added\t{name}\tstdio\t{cmd}")
        print(f"config\t{mcp_config_path()}")
        return 0
    except (ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_remove(args: argparse.Namespace) -> int:
    if not remove_server(args.name):
        print(f"not found\t{args.name}", file=sys.stderr)
        return 1
    print(f"removed\t{args.name}")
    print(f"config\t{mcp_config_path()}")
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    server = args.server.strip()
    if not server:
        print("Usage: arka mcp tools <server>", file=sys.stderr)
        return 1
    try:
        tools = list_tools(server)
    except KeyError:
        print(f"not configured\t{server}", file=sys.stderr)
        print(f"hint\tarka mcp list", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error\t{exc}", file=sys.stderr)
        return 1

    print(f"server\t{server}")
    print(f"tool_count\t{len(tools)}")
    for tool in tools:
        desc = tool.description.replace("\n", " ").strip()[:120]
        print(f"tool\t{tool.name}\t{desc}")
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    server = args.server.strip()
    tool = args.tool.strip()
    if not server or not tool:
        print("Usage: arka mcp call <server> <tool> [--args '{}']", file=sys.stderr)
        return 1
    try:
        arguments = json.loads(args.args or "{}")
    except json.JSONDecodeError as exc:
        print(f"Invalid --args JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(arguments, dict):
        print("--args must be a JSON object", file=sys.stderr)
        return 1
    try:
        text = call_tool(server, tool, arguments)
    except KeyError:
        print(f"not configured\t{server}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error\t{exc}", file=sys.stderr)
        return 1
    print(text)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    names = list_server_names()
    print(f"config\t{mcp_config_path()}")
    print(f"sdk\t{'on' if mcp_sdk_available() else 'off'}")
    if not names:
        print("servers\t0")
        print("hint\tarka mcp add <name> <command>  |  arka mcp add <name> --url <url>")
        if not mcp_sdk_available():
            print(MCP_SDK_INSTALL_HINT, file=sys.stderr)
        return 0

    healthy = 0
    for name in names:
        row = server_status(name)
        ok = row.get("healthy")
        if ok:
            healthy += 1
        status = "healthy" if ok else "unhealthy"
        transport = row.get("transport", "?")
        tool_count = row.get("tool_count", 0)
        print(f"{name}\t{status}\t{transport}\ttools={tool_count}")
        if not ok and row.get("error"):
            print(f"{name}_error\t{row['error']}")
    print(f"summary\t{healthy}/{len(names)} healthy")
    if not mcp_sdk_available():
        print(f"sdk_hint\t{MCP_SDK_INSTALL_HINT.splitlines()[0]}")
    return 0 if healthy == len(names) else 1


def cmd_parse(args: argparse.Namespace) -> int:
    from arka.integrations.mcp_manager import nl_to_argv

    argv = nl_to_argv(args.text)
    if not argv:
        return 1
    print("mcp " + " ".join(argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arka mcp",
        description="Manage and call Model Context Protocol (MCP) servers",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List configured MCP servers")

    add_p = sub.add_parser("add", help="Add stdio or HTTP MCP server")
    add_p.add_argument("name", help="Server name (e.g. filesystem, signoz)")
    add_p.add_argument("command", nargs="?", default="", help="Stdio command (e.g. npx)")
    add_p.add_argument("args", nargs="*", help="Stdio command arguments")
    add_p.add_argument("--url", help="HTTP/SSE MCP endpoint URL")
    add_p.add_argument(
        "--header",
        action="append",
        metavar="KEY=VALUE",
        help="HTTP header (repeatable)",
    )

    rm_p = sub.add_parser("remove", help="Remove a configured server")
    rm_p.add_argument("name", help="Server name")

    tools_p = sub.add_parser("tools", help="List tools from a server")
    tools_p.add_argument("server", help="Configured server name")

    call_p = sub.add_parser("call", help="Call a tool on a server")
    call_p.add_argument("server", help="Configured server name")
    call_p.add_argument("tool", help="Tool name")
    call_p.add_argument("--args", default="{}", help="JSON object of tool arguments")

    sub.add_parser("status", help="Connection health for all servers")

    parse_p = sub.add_parser("parse", help=argparse.SUPPRESS)
    parse_p.add_argument("text", help="Natural language request")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw and raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0
    if not raw:
        _print_help()
        return 0

    parser = build_parser()
    args = parser.parse_args(raw)
    if not args.command:
        _print_help()
        return 0

    handlers = {
        "list": cmd_list,
        "add": cmd_add,
        "remove": cmd_remove,
        "tools": cmd_tools,
        "call": cmd_call,
        "status": cmd_status,
        "parse": cmd_parse,
    }
    return handlers[args.command](args)


def _print_help() -> None:
    print(
        """Model Context Protocol (MCP) for Arka

Usage:
  arka mcp list                              List configured servers
  arka mcp add <name> <command> [args...]    Add stdio MCP server
  arka mcp add <name> --url <url>            Add HTTP/SSE MCP server
  arka mcp add <name> --url <url> --header KEY=VAL
  arka mcp remove <name>                     Remove a server
  arka mcp tools <server>                    List tools from a server
  arka mcp call <server> <tool> [--args '{}']
  arka mcp status                            Connection health

Config:
  ~/.config/arka/mcp.json  (Cursor-compatible mcpServers format)

Examples:
  arka mcp add filesystem npx -y @modelcontextprotocol/server-filesystem /tmp
  arka mcp add signoz --url http://localhost:8000/mcp --header SIGNOZ-API-KEY=$SIGNOZ_API_KEY
  arka mcp tools signoz
  arka mcp call signoz signoz_ask --args '{"question":"error rate last hour"}'

Fish / NL:
  mcp list
  mcp status
  agent "list mcp tools from signoz"
  agent "call mcp tool search on github"

Optional SDK:
  pip install mcp   # Arka works without it via built-in JSON-RPC
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
