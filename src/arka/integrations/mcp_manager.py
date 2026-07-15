"""Generic MCP server config, connection, and tool calls for Arka."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from arka.integrations.mcp_client import (
    MCP_PROTOCOL_VERSION,
    McpHttpClient,
    McpTool,
    _parse_tools,
    _tool_result_text,
)

MCP_CONFIG_FILE = "mcp.json"
MCP_SDK_INSTALL_HINT = (
    "Optional MCP Python SDK not installed.\n"
    "  pip install mcp\n"
    "Arka uses built-in JSON-RPC over stdio/HTTP without it."
)


@dataclass
class McpServerConfig:
    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)

    @property
    def transport(self) -> str:
        return "http" if self.url else "stdio"

    def to_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {}
        if self.url:
            entry["url"] = self.url
            if self.headers:
                entry["headers"] = dict(self.headers)
        else:
            entry["command"] = self.command
            if self.args:
                entry["args"] = list(self.args)
        if self.env:
            entry["env"] = dict(self.env)
        return entry

    @classmethod
    def from_entry(cls, name: str, entry: dict[str, Any]) -> McpServerConfig:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid MCP server entry for {name!r}")
        url = str(entry.get("url", "")).strip()
        command = str(entry.get("command", "")).strip()
        if not url and not command:
            raise ValueError(f"MCP server {name!r} needs command or url")
        args = entry.get("args") or []
        if not isinstance(args, list):
            raise ValueError(f"MCP server {name!r} args must be a list")
        headers = entry.get("headers") or {}
        if not isinstance(headers, dict):
            raise ValueError(f"MCP server {name!r} headers must be an object")
        env = entry.get("env") or {}
        if not isinstance(env, dict):
            raise ValueError(f"MCP server {name!r} env must be an object")
        return cls(
            name=name,
            command=command,
            args=[str(a) for a in args],
            url=url,
            headers={str(k): str(v) for k, v in headers.items()},
            env={str(k): str(v) for k, v in env.items()},
        )


class McpClient(Protocol):
    server: str

    def connect(self) -> dict[str, Any]: ...

    def list_tools(self) -> list[McpTool]: ...

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...

    def close(self) -> None: ...


def mcp_config_path() -> Path:
    from arka.paths import config_dir

    return config_dir() / MCP_CONFIG_FILE


def mcp_sdk_available() -> bool:
    try:
        import mcp  # noqa: F401

        return True
    except ImportError:
        return False


def _empty_config() -> dict[str, Any]:
    return {"mcpServers": {}}


def load_mcp_config() -> dict[str, Any]:
    path = mcp_config_path()
    if not path.is_file():
        return _empty_config()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid MCP config in {path}")
    servers = data.get("mcpServers")
    if servers is None:
        data["mcpServers"] = {}
    elif not isinstance(servers, dict):
        raise ValueError(f"Invalid mcpServers in {path}")
    return data


def save_mcp_config(data: dict[str, Any]) -> Path:
    path = mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mcpServers": dict(data.get("mcpServers") or {})}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def list_server_names() -> list[str]:
    data = load_mcp_config()
    return sorted((data.get("mcpServers") or {}).keys())


def get_server_config(name: str) -> McpServerConfig:
    key = name.strip()
    if not key:
        raise ValueError("MCP server name is required")
    data = load_mcp_config()
    servers = data.get("mcpServers") or {}
    if key not in servers:
        raise KeyError(f"MCP server not configured: {key}")
    return McpServerConfig.from_entry(key, servers[key])


def add_server(
    name: str,
    *,
    command: str = "",
    args: list[str] | None = None,
    url: str = "",
    headers: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
) -> McpServerConfig:
    key = name.strip()
    if not key:
        raise ValueError("MCP server name is required")
    if url and command:
        raise ValueError("Use either command (stdio) or --url (HTTP), not both")
    if not url and not command:
        raise ValueError("Provide command for stdio or --url for HTTP transport")

    config = McpServerConfig(
        name=key,
        command=command.strip(),
        args=list(args or []),
        url=url.strip(),
        headers=dict(headers or {}),
        env=dict(env or {}),
    )
    data = load_mcp_config()
    servers = data.setdefault("mcpServers", {})
    servers[key] = config.to_entry()
    save_mcp_config(data)
    return config


def remove_server(name: str) -> bool:
    key = name.strip()
    data = load_mcp_config()
    servers = data.get("mcpServers") or {}
    if key not in servers:
        return False
    del servers[key]
    save_mcp_config(data)
    return True


def _resolve_env_values(values: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, raw in values.items():
        text = str(raw)
        m = re.fullmatch(r"\$\{env:([^}]+)\}", text.strip())
        if m:
            text = os.environ.get(m.group(1), "")
        resolved[str(key)] = text
    return resolved


class McpStdioClient:
    """Minimal MCP stdio JSON-RPC client (newline-delimited messages)."""

    def __init__(
        self,
        *,
        server: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.server = server
        self.command = command
        self.args = list(args)
        self.env = _resolve_env_values(env or {})
        self.timeout = timeout
        self._proc: subprocess.Popen[str] | None = None
        self._request_id = 0
        self._initialized = False
        self._lock = threading.Lock()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _ensure_proc(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        full_env = {**os.environ, **self.env}
        self._proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=full_env,
            text=True,
            bufsize=1,
        )
        return self._proc

    def _send(self, payload: dict[str, Any]) -> None:
        proc = self._ensure_proc()
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    def _recv_response(self, request_id: int) -> dict[str, Any]:
        proc = self._ensure_proc()
        assert proc.stdout is not None
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                err = ""
                if proc.stderr is not None:
                    err = proc.stderr.read() or ""
                raise RuntimeError(
                    f"MCP stdio process exited ({proc.returncode}): {err.strip()[:300]}"
                )
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.02)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                body = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(body, dict):
                continue
            if body.get("id") == request_id:
                if "error" in body:
                    err = body["error"]
                    message = str(err.get("message", err)) if isinstance(err, dict) else str(err)
                    raise RuntimeError(message)
                result = body.get("result")
                return result if isinstance(result, dict) else {"value": result}
        raise TimeoutError(f"MCP stdio timed out waiting for response id={request_id}")

    def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: int | None = None,
    ) -> Any:
        with self._lock:
            payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if request_id is not None:
                payload["id"] = request_id
            if params is not None:
                payload["params"] = params
            self._send(payload)
            if request_id is None:
                return None
            return self._recv_response(request_id)

    def connect(self) -> dict[str, Any]:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "arka", "version": "0.1.0"},
            },
            request_id=self._next_id(),
        )
        self._rpc("notifications/initialized", {})
        self._initialized = True
        return result if isinstance(result, dict) else {}

    def list_tools(self) -> list[McpTool]:
        if not self._initialized:
            self.connect()
        result = self._rpc("tools/list", {}, request_id=self._next_id())
        return _parse_tools(result)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if not self._initialized:
            self.connect()
        return self._rpc(
            "tools/call",
            {"name": name.strip(), "arguments": arguments or {}},
            request_id=self._next_id(),
        )

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except OSError:
            pass
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._initialized = False


def connect_client(name: str) -> McpClient:
    config = get_server_config(name)
    if config.transport == "http":
        return McpHttpClient(
            server=config.name,
            url=config.url,
            headers=dict(config.headers),
            api_key="",
        )
    return McpStdioClient(
        server=config.name,
        command=config.command,
        args=config.args,
        env=config.env,
    )


def list_tools(server: str) -> list[McpTool]:
    client = connect_client(server)
    try:
        return client.list_tools()
    finally:
        client.close()


def call_tool(server: str, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    try:
        from arka.integrations.context7_mcp import notify_context7_tool_call

        notify_context7_tool_call(server, tool_name, arguments)
    except ImportError:
        pass
    client = connect_client(server)
    try:
        result = client.call_tool(tool_name, arguments)
        return _tool_result_text(result)
    finally:
        client.close()


def server_status(name: str) -> dict[str, Any]:
    try:
        config = get_server_config(name)
    except KeyError as exc:
        return {"name": name, "configured": False, "healthy": False, "error": str(exc)}

    client = connect_client(name)
    try:
        info = client.connect()
        tools = client.list_tools()
        server_info = info.get("serverInfo") if isinstance(info, dict) else {}
        return {
            "name": name,
            "configured": True,
            "healthy": True,
            "transport": config.transport,
            "tool_count": len(tools),
            "server_info": server_info if isinstance(server_info, dict) else {},
            "tools": [tool.name for tool in tools[:20]],
        }
    except Exception as exc:
        return {
            "name": name,
            "configured": True,
            "healthy": False,
            "transport": config.transport,
            "error": str(exc)[:500],
        }
    finally:
        client.close()


def all_status() -> list[dict[str, Any]]:
    names = list_server_names()
    if not names:
        return []
    return [server_status(name) for name in names]


def nl_to_argv(cmd: str) -> list[str] | None:
    """Map natural language to `mcp` subcommand argv."""
    clean = cmd.strip()
    if not clean:
        return None
    lower = clean.lower()

    if re.search(r"(?i)\b(?:mcp|model\s+context\s+protocol)\b.*\b(?:status|health|connections?)\b", clean):
        return ["status"]
    if re.search(r"(?i)\b(?:connect|check)\b.*\bmcp\b", clean):
        return ["status"]
    if re.search(r"(?i)\b(?:list|show)\b.*\b(?:configured\s+)?mcp\b.*\bservers?\b", clean):
        return ["list"]
    if re.search(r"(?i)\b(?:list|show)\b.*\bmcp\b.*\btools?\b", clean):
        m = re.search(r"(?i)\b(?:from|on|for)\s+([a-zA-Z0-9._-]+)", clean)
        if m:
            return ["tools", m.group(1)]
        if re.search(r"(?i)\b(?:arka|self)\b", clean):
            return ["self-tools"]
        return ["list"]
    if re.search(r"(?i)\b(?:what|which|show|list)\b.*\btools?\b.*\b(?:available|can)\b", clean) and re.search(r"(?i)\bmcp\b", clean):
        m = re.search(r"(?i)\b(?:from|on|for)\s+([a-zA-Z0-9._-]+)", clean)
        return ["tools", m.group(1)] if m else ["self-tools"]
    if re.search(r"(?i)\b(?:list|show)\b.*\b(?:arka\s+)?(?:self\s+)?mcp\s+tools?\b", clean):
        return ["self-tools"]
    if re.search(r"(?i)\b(?:list|show)\b.*\bmcp\s+self[- ]tools?\b", clean):
        return ["self-tools"]
    if re.search(r"(?i)\barka\s+mcp\s+tools?\b", clean):
        return ["self-tools"]
    m = re.search(r"(?i)^mcp\s+tools?\s+([a-zA-Z0-9._-]+)$", clean)
    if m:
        return ["tools", m.group(1)]
    m = re.search(r"(?i)\bmcp\s+tools?\s+([a-zA-Z0-9._-]+)", clean)
    if m:
        return ["tools", m.group(1)]
    if re.search(r"(?i)\bcall\b.*\bmcp\b.*\btool\b", clean):
        server_m = re.search(r"(?i)\b(?:on|from)\s+([a-zA-Z0-9._-]+)", clean)
        tool_m = re.search(r"(?i)\btool\s+([a-zA-Z0-9._-]+)", clean)
        if server_m and tool_m:
            return ["call", server_m.group(1), tool_m.group(1)]
    m = re.search(r"(?i)\b(?:call|invoke|run|use)\s+(?:the\s+)?(?:mcp\s+)?tool\s+([a-zA-Z0-9._-]+)\s+(?:on|from)\s+([a-zA-Z0-9._-]+)", clean)
    if m:
        return ["call", m.group(2), m.group(1)]
    if lower in {"mcp", "mcp list", "list mcp", "mcp servers"}:
        return ["list"]
    return None


def format_server_list() -> str:
    names = list_server_names()
    if not names:
        return f"No MCP servers configured. Config: {mcp_config_path()}"
    lines = [f"config\t{mcp_config_path()}", f"count\t{len(names)}"]
    for name in names:
        try:
            cfg = get_server_config(name)
            if cfg.transport == "http":
                lines.append(f"{name}\thttp\t{cfg.url}")
            else:
                cmd = " ".join(shlex.quote(p) for p in [cfg.command, *cfg.args])
                lines.append(f"{name}\tstdio\t{cmd}")
        except Exception as exc:
            lines.append(f"{name}\tinvalid\t{exc}")
    if not mcp_sdk_available():
        lines.append(f"sdk\toff\t{MCP_SDK_INSTALL_HINT.splitlines()[0]}")
    else:
        lines.append("sdk\ton")
    return "\n".join(lines)


__all__ = [
    "MCP_CONFIG_FILE",
    "MCP_SDK_INSTALL_HINT",
    "McpServerConfig",
    "McpStdioClient",
    "add_server",
    "all_status",
    "call_tool",
    "connect_client",
    "format_server_list",
    "get_server_config",
    "list_server_names",
    "list_tools",
    "load_mcp_config",
    "mcp_config_path",
    "mcp_sdk_available",
    "nl_to_argv",
    "remove_server",
    "save_mcp_config",
    "server_status",
]
