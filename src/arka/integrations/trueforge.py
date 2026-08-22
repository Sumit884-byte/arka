#!/usr/bin/env python3
"""TrueForge agent harness integration — run, connect, and bridge Arka."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from typing import Any, Iterator
from urllib.parse import urljoin

DEFAULT_BASE_URL = "http://localhost:8790"
DEFAULT_PORT = 8790
ARKA_AGENT_NAME = "arka"


def base_url() -> str:
    return (
        os.environ.get("TRUEFORGE_BASE_URL")
        or os.environ.get("ARKA_TRUEFORGE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")


def auth_token() -> str:
    return (os.environ.get("TRUEFORGE_TOKEN") or os.environ.get("TRUEFORGE_ID_TOKEN") or "").strip()


def _endpoint(path: str, *, url: str | None = None) -> str:
    return urljoin((url or base_url()).rstrip("/") + "/", path.lstrip("/"))


def request_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    url: str | None = None,
    token: str | None = None,
    timeout: int = 60,
    accept: str = "application/json",
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": accept}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    tok = auth_token() if token is None else token
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(_endpoint(path, url=url), data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return resp.status, {}
            data = json.loads(raw)
            return resp.status, data if isinstance(data, dict) else {"data": data}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {"error": {"message": raw or exc.reason}}
        if isinstance(data, dict):
            return exc.code, data
        return exc.code, {"error": {"message": str(data)}}
    except urllib.error.URLError as exc:
        return 0, {"error": {"message": f"could not reach TrueForge: {exc.reason}"}}


def _error_message(data: dict[str, Any]) -> str:
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err or "request failed")


def health_payload(*, url: str | None = None) -> dict[str, Any]:
    status, caps = request_json("/api/v1/capabilities", url=url, timeout=10)
    ok = status == 200 and "data" in caps
    models: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    if ok:
        _m_status, models_resp = request_json("/api/v1/models", url=url, timeout=10)
        if _m_status == 200:
            models = list(models_resp.get("data") or [])
        _a_status, agents_resp = request_json("/api/v1/agents", url=url, timeout=10)
        if _a_status == 200:
            agents = list(agents_resp.get("data") or [])
    return {
        "ok": ok,
        "base_url": url or base_url(),
        "status_code": status,
        "capabilities": caps.get("data") or {},
        "models": [row.get("name") for row in models if isinstance(row, dict)],
        "agents": [row.get("name") for row in agents if isinstance(row, dict)],
        "token_set": bool(auth_token()),
        "error": "" if ok else _error_message(caps),
    }


def list_agents(*, url: str | None = None) -> list[dict[str, Any]]:
    status, data = request_json("/api/v1/agents", url=url, timeout=15)
    if status != 200:
        raise RuntimeError(_error_message(data))
    rows = data.get("data") or []
    return [row for row in rows if isinstance(row, dict)]


def list_models(*, url: str | None = None) -> list[str]:
    status, data = request_json("/api/v1/models", url=url, timeout=15)
    if status != 200:
        raise RuntimeError(_error_message(data))
    rows = data.get("data") or []
    return [str(row.get("name") or "") for row in rows if isinstance(row, dict) and row.get("name")]


def create_session(
    *,
    agent_name: str = "",
    model: str = "",
    instructions: str = "",
    mcp_server_names: list[str] | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    if agent_name:
        payload = {"agent": {"name": agent_name}}
    else:
        model_name = model or (list_models(url=url)[:1] or [""])[0]
        if not model_name:
            raise RuntimeError("no model configured on TrueForge — add one in Settings → Models")
        spec: dict[str, Any] = {
            "model": {"name": model_name},
            "instructions": instructions or "You are a helpful assistant.",
        }
        if mcp_server_names:
            spec["mcp_servers"] = [{"name": name} for name in mcp_server_names]
        payload = {"agent": {"spec": spec}}
    status, data = request_json("/api/v1/sessions", method="POST", payload=payload, url=url, timeout=30)
    if status not in (200, 201):
        raise RuntimeError(_error_message(data))
    session = data.get("data")
    if not isinstance(session, dict):
        raise RuntimeError("invalid session response")
    return session


def _iter_sse_json(raw_iter: Iterator[bytes]) -> Iterator[dict[str, Any]]:
    buf = ""
    for chunk in raw_iter:
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            data_lines = [line[5:].strip() for line in block.split("\n") if line.startswith("data:")]
            if not data_lines:
                continue
            payload = "\n".join(data_lines)
            if payload in ("[DONE]", ""):
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event


def stream_turn(
    session_id: str,
    message: str,
    *,
    url: str | None = None,
    timeout: int = 600,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "input": [{"type": "user.message", "content": message}],
        "stream": True,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    tok = auth_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(
        _endpoint(f"/api/v1/sessions/{session_id}/turns", url=url),
        data=body,
        method="POST",
        headers=headers,
    )
    parts: list[str] = []
    final: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for event in _iter_sse_json(iter(lambda: resp.read(4096), b"")):
                etype = event.get("type") or ""
                if etype == "model.message.delta":
                    thread_id = event.get("threadId") or event.get("thread_id") or "main"
                    if thread_id in ("main", "", None):
                        chunk = event.get("content") or ""
                        if chunk:
                            parts.append(str(chunk))
                elif etype == "turn.done":
                    final = event
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(raw or exc.reason) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach TrueForge: {exc.reason}") from exc

    text = "".join(parts)
    state = final.get("state") if isinstance(final.get("state"), dict) else {}
    output = state.get("output") if isinstance(state.get("output"), dict) else {}
    if not text and output.get("content"):
        text = str(output.get("content") or "")
    return text, final


def run_prompt(
    prompt: str,
    *,
    agent_name: str = "",
    model: str = "",
    session_id: str = "",
    instructions: str = "",
    mcp_server_names: list[str] | None = None,
    url: str | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("empty prompt")
    if not session_id:
        session = create_session(
            agent_name=agent_name,
            model=model,
            instructions=instructions,
            mcp_server_names=mcp_server_names,
            url=url,
        )
        session_id = str(session.get("id") or "")
    if not session_id:
        raise RuntimeError("could not create TrueForge session")
    output, turn = stream_turn(session_id, prompt, url=url, timeout=timeout)
    status = ""
    if isinstance(turn.get("state"), dict):
        status = str(turn["state"].get("status") or "")
    return {
        "ok": bool(output.strip()),
        "session_id": session_id,
        "output": output,
        "turn_status": status,
    }


def arka_mcp_launch_spec() -> dict[str, Any]:
    try:
        from arka.integrations.mcp_server import mcp_server_launch_spec

        return mcp_server_launch_spec()
    except ImportError:
        return {"command": "arka", "args": ["mcp", "serve"]}


def connect_payload(*, url: str | None = None, model: str = "", register_agent: bool = True) -> dict[str, Any]:
    """Prepare TrueForge ↔ Arka bridge instructions and optionally register an agent."""
    info = health_payload(url=url)
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error") or "TrueForge unreachable", **info}

    launch = arka_mcp_launch_spec()
    mcp_name = "arka"
    models = info.get("models") or []
    chosen_model = model or (models[0] if models else "")
    steps = [
        "Open TrueForge → Settings → Connectors → Add MCP Server (stdio) if supported in your version.",
        "Use the stdio launch spec below, or run `arka mcp install` for Cursor/Claude and mirror it in TrueForge.",
        "Configure a model in TrueForge Settings → Models if none are listed.",
        f"Run `arka trueforge run --agent {ARKA_AGENT_NAME} \"your task\"` once the arka agent exists.",
    ]

    agent_result: dict[str, Any] | None = None
    if register_agent and chosen_model:
        manifest: dict[str, Any] = {
            "model": {"name": chosen_model},
            "instructions": (
                "You are an Arka-powered agent. Prefer Arka MCP tools for routing, repo work, "
                "memory, CI, and skills. Explain tool use briefly."
            ),
        }
        if mcp_name in (info.get("agents") or []) or True:
            manifest["mcp_servers"] = [{"name": mcp_name, "enable_tools": ["@all"]}]
        status, data = request_json(
            "/api/v1/agents",
            method="POST",
            payload={"name": ARKA_AGENT_NAME, "manifest": manifest},
            url=url,
            timeout=30,
        )
        if status in (200, 201):
            agent_result = data.get("data") if isinstance(data.get("data"), dict) else data
        elif status == 409:
            agent_result = {"name": ARKA_AGENT_NAME, "exists": True}
        else:
            agent_result = {"error": _error_message(data)}

    return {
        "ok": True,
        "base_url": info.get("base_url"),
        "mcp_stdio_launch": launch,
        "recommended_model": chosen_model,
        "steps": steps,
        "agent": agent_result,
        "docs": "https://trueforge.dev/quickstart",
    }


def start_server(*, port: int = DEFAULT_PORT, detach: bool = True) -> dict[str, Any]:
    npx = shutil.which("npx")
    if not npx:
        return {"ok": False, "error": "npx not found — install Node.js 22+ to run TrueForge locally"}
    url = f"http://127.0.0.1:{port}"
    existing = health_payload(url=url)
    if existing.get("ok"):
        return {"ok": True, "already_running": True, "base_url": url, "ui_url": url}

    log_dir = os.environ.get("TRUEFORGE_LOG_DIR") or os.path.join(os.path.expanduser("~/.cache/arka"), "trueforge")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"trueforge-{port}.log")
    env = os.environ.copy()
    env["PORT"] = str(port)
    cmd = [npx, "@truefoundry/trueforge", "--port", str(port)]
    stdout = open(log_path, "a", encoding="utf-8") if detach else None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=stdout or subprocess.PIPE,
            stderr=subprocess.STDOUT if stdout else subprocess.PIPE,
            env=env,
            start_new_session=detach,
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    if not detach:
        proc.wait()
        return {"ok": proc.returncode == 0, "base_url": url}

    return {
        "ok": True,
        "pid": proc.pid,
        "base_url": url,
        "ui_url": url,
        "log_path": log_path,
        "command": " ".join(shlex.quote(part) for part in cmd),
    }


def setup_text() -> str:
    return f"""TrueForge + Arka quick setup

1. Start TrueForge (local harness UI + API):
   arka trueforge start
   # or: npx @truefoundry/trueforge

2. Open the UI and configure a model (Settings → Models):
   {base_url()}

3. Wire Arka tools into TrueForge:
   arka trueforge connect

4. Run a saved agent or inline model from the terminal:
   arka trueforge run --agent {ARKA_AGENT_NAME} "review my repo health"
   arka trueforge run --model <provider/model> "summarize this design"

5. Check status / list agents:
   arka trueforge status
   arka trueforge agents

Env:
  TRUEFORGE_BASE_URL={base_url()}
  TRUEFORGE_TOKEN=          # OIDC ID token when login is enabled

Docs: https://trueforge.dev/quickstart
"""


def wants_trueforge(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if re.match(
        r"(?i)^(?:arka\s+)?trueforge(?:\s+status|\s+start|\s+agents|\s+run|\s+connect|\s+setup|\s+open|\s+help|\s+--help)?$",
        clean,
    ):
        return True
    if re.match(r"(?i)^trueforge\b", clean):
        return True
    if re.search(r"(?i)\btrueforge\b.*\b(?:agent|harness|run|connect)\b", clean):
        return True
    if re.search(r"(?i)\b(?:run|use|start)\s+trueforge\b", clean):
        return True
    return False


def route_command(text: str) -> str:
    if not wants_trueforge(text):
        return ""
    clean = (text or "").strip()
    for sub in ("status", "start", "agents", "connect", "setup", "open", "models"):
        if re.match(rf"(?i)^(?:arka\s+)?trueforge\s+{sub}$", clean):
            return f"trueforge {sub}"
    m = re.match(r"(?i)^(?:arka\s+)?trueforge\s+run\s+(.+)$", clean)
    if m:
        return "trueforge run " + shlex.quote(m.group(1).strip())
    m = re.search(r"(?i)\b(?:run|use)\s+trueforge\s+(?:to\s+)?(.+)$", clean)
    if m:
        return "trueforge run " + shlex.quote(m.group(1).strip())
    return "trueforge status"


def trueforge_payload(
    *,
    action: str = "status",
    prompt: str = "",
    agent: str = "",
    model: str = "",
    session_id: str = "",
    url: str = "",
    port: int = DEFAULT_PORT,
) -> dict[str, Any]:
    action = (action or "status").strip().lower()
    base = url or base_url()
    if action == "status":
        return health_payload(url=base or None)
    if action == "setup":
        return {"ok": True, "guide": setup_text()}
    if action == "start":
        return start_server(port=port)
    if action == "connect":
        return connect_payload(url=base or None, model=model)
    if action == "agents":
        try:
            rows = list_agents(url=base or None)
            return {"ok": True, "agents": rows}
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
    if action == "models":
        try:
            return {"ok": True, "models": list_models(url=base or None)}
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
    if action == "run":
        try:
            result = run_prompt(
                prompt,
                agent_name=agent,
                model=model,
                session_id=session_id,
                url=base or None,
            )
            return {"ok": True, **result}
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": f"unknown action: {action}"}


def cmd_status(args: argparse.Namespace) -> int:
    info = health_payload(url=args.url)
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print("TrueForge integration")
        print(f"Base URL: {info.get('base_url')}")
        if info.get("ok"):
            print("Status: reachable")
            models = info.get("models") or []
            agents = info.get("agents") or []
            print(f"Models: {len(models)}" + (f" ({', '.join(models[:3])})" if models else ""))
            print(f"Agents: {len(agents)}" + (f" ({', '.join(agents[:5])})" if agents else ""))
            caps = info.get("capabilities") or {}
            sandbox = (caps.get("sandbox") or {}).get("enabled")
            print(f"Sandbox: {'enabled' if sandbox else 'not configured'}")
        else:
            print(f"Status: unreachable — {info.get('error')}")
            print("")
            print("Start locally:")
            print("  arka trueforge start")
            print("  npx @truefoundry/trueforge")
        print(f"OIDC token set: {'yes' if info.get('token_set') else 'no'}")
    return 0 if info.get("ok") else 1


def cmd_start(args: argparse.Namespace) -> int:
    result = start_server(port=args.port, detach=not args.foreground)
    if args.json:
        print(json.dumps(result, indent=2))
    elif result.get("ok"):
        if result.get("already_running"):
            print(f"TrueForge already running at {result.get('base_url')}")
        else:
            print(f"TrueForge starting (pid {result.get('pid')}) → {result.get('ui_url')}")
            print(f"Log: {result.get('log_path')}")
            print("Configure a model in the UI, then: arka trueforge connect")
    else:
        print(result.get("error") or "start failed", file=sys.stderr)
    return 0 if result.get("ok") else 1


def cmd_agents(args: argparse.Namespace) -> int:
    try:
        rows = list_agents(url=args.url)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"agents": rows}, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("No saved agents. Create one in the TrueForge UI or run: arka trueforge connect")
        return 0
    for row in rows:
        name = row.get("name") or "?"
        model = ((row.get("manifest") or {}).get("model") or {}).get("name") or "?"
        print(f"  {name}\tmodel={model}\tid={row.get('id')}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    try:
        names = list_models(url=args.url)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"models": names}, indent=2))
        return 0
    for name in names:
        print(name)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("Usage: arka trueforge run [--agent NAME|--model FQN] <prompt>", file=sys.stderr)
        return 2
    try:
        result = run_prompt(
            prompt,
            agent_name=args.agent or "",
            model=args.model or "",
            session_id=args.session or "",
            url=args.url,
            timeout=args.timeout,
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result.get("output") or "")
        if args.session:
            print(f"\n[session {result.get('session_id')} · turn {result.get('turn_status') or 'done'}]", file=sys.stderr)
    return 0 if result.get("ok") else 1


def cmd_connect(args: argparse.Namespace) -> int:
    payload = connect_payload(url=args.url, model=args.model or "", register_agent=not args.no_register)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload.get("ok") else 1
    if not payload.get("ok"):
        print(payload.get("error") or "connect failed", file=sys.stderr)
        return 1
    print("TrueForge ↔ Arka bridge")
    print(f"Server: {payload.get('base_url')}")
    for step in payload.get("steps") or []:
        print(f"  • {step}")
    print("\nArka MCP stdio launch spec (for TrueForge Connectors UI):")
    print(json.dumps(payload.get("mcp_stdio_launch") or {}, indent=2))
    agent = payload.get("agent")
    if isinstance(agent, dict):
        if agent.get("exists"):
            print(f"\nAgent `{ARKA_AGENT_NAME}` already exists in TrueForge.")
        elif agent.get("error"):
            print(f"\nCould not register `{ARKA_AGENT_NAME}` agent: {agent['error']}")
            print("Add MCP connector `arka` in the UI, then re-run connect.")
        else:
            print(f"\nRegistered agent `{ARKA_AGENT_NAME}` (model: {payload.get('recommended_model')}).")
    return 0


def cmd_setup(_args: argparse.Namespace) -> int:
    print(setup_text())
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    target = (args.url or base_url()).rstrip("/")
    if not webbrowser.open(target):
        print(target)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="TrueForge agent harness integration for Arka")
    parser.add_argument("--url", default=None, help="TrueForge base URL (default: TRUEFORGE_BASE_URL)")
    sub = parser.add_subparsers(dest="cmd")

    p_status = sub.add_parser("status", help="Check TrueForge server health")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_start = sub.add_parser("start", help="Start local TrueForge via npx")
    p_start.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_start.add_argument("--foreground", action="store_true", help="Run in foreground (no detach)")
    p_start.add_argument("--json", action="store_true")
    p_start.set_defaults(func=cmd_start)

    p_agents = sub.add_parser("agents", help="List saved TrueForge agents")
    p_agents.add_argument("--json", action="store_true")
    p_agents.set_defaults(func=cmd_agents)

    p_models = sub.add_parser("models", help="List configured models")
    p_models.add_argument("--json", action="store_true")
    p_models.set_defaults(func=cmd_models)

    p_run = sub.add_parser("run", help="Run a prompt through TrueForge")
    p_run.add_argument("--agent", default="", help="Saved agent name")
    p_run.add_argument("--model", default="", help="Inline model FQN when no --agent")
    p_run.add_argument("--session", default="", help="Reuse an existing session id")
    p_run.add_argument("--timeout", type=int, default=600)
    p_run.add_argument("--json", action="store_true")
    p_run.add_argument("prompt", nargs=argparse.REMAINDER)
    p_run.set_defaults(func=cmd_run)

    p_connect = sub.add_parser("connect", help="Register Arka agent + print MCP bridge spec")
    p_connect.add_argument("--model", default="", help="Model FQN for the arka agent")
    p_connect.add_argument("--no-register", action="store_true", help="Skip POST /agents")
    p_connect.add_argument("--json", action="store_true")
    p_connect.set_defaults(func=cmd_connect)

    sub.add_parser("setup", help="Print setup guide").set_defaults(func=cmd_setup)

    p_open = sub.add_parser("open", help="Open TrueForge UI in a browser")
    p_open.set_defaults(func=cmd_open)

    raw = list(argv if argv is not None else sys.argv[1:])
    if not raw or raw[0] in ("-h", "--help", "help"):
        parser.print_help()
        return 0

    args = parser.parse_args(raw)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
