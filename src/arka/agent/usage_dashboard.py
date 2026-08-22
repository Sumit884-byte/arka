"""Generate and serve a local HTML dashboard from Arka usage counters and MCP logs."""
from __future__ import annotations

import argparse
import html
import json
import os
import signal
import sys
import time
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8788


def _dashboard_host() -> str:
    return os.environ.get("ARKA_DASHBOARD_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def _dashboard_port() -> int:
    raw = os.environ.get("ARKA_DASHBOARD_PORT", str(DEFAULT_PORT)).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PORT


def collect_mcp_stats() -> dict[str, Any]:
    from arka.integrations.mcp_logs import mcp_log_path

    path = mcp_log_path()
    if not path.is_file():
        return {"available": False, "path": str(path)}

    tool_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    durations: dict[str, list[float]] = defaultdict(list)
    errors: list[dict[str, str]] = []
    total_calls = 0
    first_ts = ""
    last_ts = ""

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event") != "server.tools_call":
            continue
        tool = str(row.get("tool") or "").strip()
        if not tool:
            continue
        total_calls += 1
        tool_counts[tool] += 1
        status = str(row.get("status") or "unknown")
        status_counts[status] += 1
        duration = row.get("duration_ms")
        if duration is not None:
            try:
                durations[tool].append(float(duration))
            except (TypeError, ValueError):
                pass
        ts = str(row.get("ts") or "")
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        if status == "error" or row.get("error"):
            errors.append(
                {
                    "ts": ts,
                    "tool": tool,
                    "error": str(row.get("error") or "error")[:200],
                }
            )

    tools: list[dict[str, Any]] = []
    for tool, count in tool_counts.most_common(20):
        tool_durations = durations.get(tool, [])
        avg_ms = round(sum(tool_durations) / len(tool_durations), 1) if tool_durations else None
        tools.append({"tool": tool, "count": count, "avg_ms": avg_ms})

    return {
        "available": True,
        "path": str(path),
        "total_calls": total_calls,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "status": dict(status_counts),
        "tools": tools,
        "errors": errors[-10:],
        "error_count": int(status_counts.get("error", 0)),
    }


def collect_data() -> dict[str, Any]:
    from arka.core.skill_usage import report

    try:
        from arka.core.llm_usage import report as llm_usage_report
    except ImportError:
        llm_usage_report = None

    data = {
        "skills": report(),
        "mcp": collect_mcp_stats(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if llm_usage_report is not None:
        data["tokens"] = llm_usage_report(period="all")
    return data


def render_html(data: dict[str, Any]) -> str:
    skills = data["skills"]
    mcp = data["mcp"]
    tokens = data.get("tokens") or {}
    skill_rows = "".join(
        f"<tr><td>{html.escape(str(name))}</td><td>{count}</td></tr>"
        for name, count in skills["skills"]
    )
    mcp_rows = "".join(
        (
            f"<tr><td>{html.escape(str(row['tool']))}</td>"
            f"<td>{row['count']}</td>"
            f"<td>{row['avg_ms'] if row['avg_ms'] is not None else '—'}</td></tr>"
        )
        for row in mcp.get("tools", [])
    )
    error_rows = "".join(
        (
            f"<tr><td>{html.escape(str(row.get('ts') or ''))}</td>"
            f"<td>{html.escape(str(row.get('tool') or ''))}</td>"
            f"<td>{html.escape(str(row.get('error') or ''))}</td></tr>"
        )
        for row in mcp.get("errors", [])
    )
    mcp_status = ", ".join(f"{k}={v}" for k, v in sorted(mcp.get("status", {}).items()))
    mcp_range = ""
    if mcp.get("first_ts"):
        mcp_range = f"{mcp.get('first_ts')} .. {mcp.get('last_ts')}"

    token_cards = ""
    if tokens:
        token_cards = f"""
  <div class='card'><b>LLM tokens</b><h2>{int(tokens.get('total_tokens') or 0):,}</h2></div>
  <div class='card'><b>Spent (est.)</b><h2>${float(tokens.get('actual_cost_usd') or 0):.4f}</h2></div>
  <div class='card'><b>Saved (est.)</b><h2>${float(tokens.get('total_savings_usd') or 0):.4f}</h2></div>"""

    return f"""<!doctype html>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width'>
<meta http-equiv='refresh' content='30'>
<title>Arka usage</title>
<style>
body{{font:16px system-ui;max-width:980px;margin:40px auto;padding:0 20px;background:#0b1020;color:#edf2ff}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}}
.card{{background:#17213c;padding:18px;border-radius:12px;min-width:150px}}
section{{margin-top:32px}}
table{{margin-top:12px;width:100%;border-collapse:collapse}}
th,td{{padding:10px;border-bottom:1px solid #2b385d;text-align:left}}
th{{color:#c7d4f7}}
.muted{{color:#9eacce}}
h2{{margin-top:0}}
</style>
<h1>Arka usage dashboard</h1>
<p class='muted'>Local counters and MCP tool logs only; prompts and secrets are not stored. Updated {html.escape(str(data.get('generated_at') or ''))} · auto-refresh 30s</p>
<div class='cards'>
  <div class='card'><b>Skill invocations</b><h2>{skills['total']}</h2></div>
  <div class='card'><b>Tracking</b><h2>{'on' if skills['enabled'] else 'off'}</h2></div>
  <div class='card'><b>Skills used</b><h2>{len(skills['skills'])}</h2></div>
  <div class='card'><b>MCP tool calls</b><h2>{mcp.get('total_calls', 0) if mcp.get('available') else '—'}</h2></div>
  <div class='card'><b>MCP errors</b><h2>{mcp.get('error_count', 0) if mcp.get('available') else '—'}</h2></div>{token_cards}
</div>
<section>
  <h2>Token usage</h2>
  <p class='muted'>Local ledger only — compared to {html.escape(str(tokens.get('baseline_label') or 'GPT-4o-class'))} baseline.</p>
  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>LLM calls</td><td>{int(tokens.get('requests') or 0)}</td></tr>
    <tr><td>Offline routes</td><td>{int(tokens.get('offline_routes') or 0)}</td></tr>
    <tr><td>Input tokens</td><td>{int(tokens.get('input_tokens') or 0):,}</td></tr>
    <tr><td>Output tokens</td><td>{int(tokens.get('output_tokens') or 0):,}</td></tr>
    <tr><td>Baseline cost</td><td>${float(tokens.get('baseline_cost_usd') or 0):.4f}</td></tr>
    <tr><td>Estimated savings</td><td>${float(tokens.get('total_savings_usd') or 0):.4f}</td></tr>
  </table>
</section>
<section>
  <h2>Skill usage</h2>
  <p class='muted'>Source: {html.escape(str(skills.get('path') or ''))}</p>
  <table>
    <tr><th>Skill</th><th>Uses</th></tr>
    {skill_rows or '<tr><td colspan=2>No usage recorded yet.</td></tr>'}
  </table>
</section>
<section>
  <h2>MCP tool usage</h2>
  <p class='muted'>Source: {html.escape(str(mcp.get('path') or ''))}{(' · ' + html.escape(mcp_range)) if mcp_range else ''}{(' · ' + html.escape(mcp_status)) if mcp_status else ''}</p>
  <table>
    <tr><th>Tool</th><th>Calls</th><th>Avg ms</th></tr>
    {mcp_rows or '<tr><td colspan=3>No MCP tool calls logged yet.</td></tr>'}
  </table>
</section>
<section>
  <h2>Recent MCP errors</h2>
  <table>
    <tr><th>Time</th><th>Tool</th><th>Error</th></tr>
    {error_rows or '<tr><td colspan=3>No MCP errors logged.</td></tr>'}
  </table>
</section>
"""


def build(output: str = "arka-usage-dashboard.html") -> dict[str, object]:
    data = collect_data()
    document = render_html(data)
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return {
        "output": str(path),
        "total": data["skills"]["total"],
        "skills": len(data["skills"]["skills"]),
        "tracking": data["skills"]["enabled"],
        "mcp_calls": data["mcp"].get("total_calls", 0),
    }


class UsageDashboardHandler(BaseHTTPRequestHandler):
    server_version = "ArkaUsageDashboard/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/stats":
            body = json.dumps(collect_data(), indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return

        body = render_html(collect_data()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(*, host: str | None = None, port: int | None = None) -> int:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    listen_host = host or _dashboard_host()
    listen_port = port if port is not None else _dashboard_port()
    httpd = ThreadingHTTPServer((listen_host, listen_port), UsageDashboardHandler)
    url = f"http://{listen_host}:{listen_port}/"
    print(f"Arka usage dashboard listening on {url}")
    print("JSON stats: GET /api/stats")

    def _stop(*_args: object) -> None:
        httpd.shutdown()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return 0


def main(argv: list[str] | None = None, *, default_action: str = "build") -> int:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    p = argparse.ArgumentParser(prog="arka dashboard")
    p.add_argument("command", nargs="?", choices=("serve", "build"), help="serve HTTP dashboard or write HTML")
    p.add_argument("--serve", action="store_true", help="Serve dashboard over HTTP")
    p.add_argument("--host", default=None, help=f"Listen host (default: {DEFAULT_HOST} or ARKA_DASHBOARD_HOST)")
    p.add_argument("--port", type=int, default=None, help=f"Listen port (default: {DEFAULT_PORT} or ARKA_DASHBOARD_PORT)")
    p.add_argument("--output", default="arka-usage-dashboard.html", help="Output HTML path when building")
    p.add_argument("--json", action="store_true", help="Print build result as JSON")
    args = p.parse_args(argv)

    action = "serve" if args.serve else (args.command or default_action)
    if action == "serve":
        return serve(host=args.host, port=args.port)

    result = build(args.output)
    print(json.dumps(result, indent=2) if args.json else f"Usage dashboard: {result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
