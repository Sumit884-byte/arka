import io


from arka.agent.usage_dashboard import (
    UsageDashboardHandler,
    build,
    collect_mcp_stats,
    main,
    render_html,
    serve,
)
from arka.routing.symbolic import route_offline_extras


def test_usage_dashboard_is_local_and_rendered(tmp_path):
    result = build(str(tmp_path / "usage.html"))
    assert result["output"].endswith("usage.html")
    text = (tmp_path / "usage.html").read_text()
    assert "Arka usage dashboard" in text
    assert "MCP tool usage" in text


def test_usage_dashboard_route():
    assert route_offline_extras("show my Arka usage dashboard") == "usage dashboard"


def test_collect_mcp_stats_from_logs(tmp_path, monkeypatch):
    from arka.integrations.mcp_logs import log_mcp_event

    monkeypatch.setenv("ARKA_MCP_LOG_PATH", str(tmp_path / "mcp.jsonl"))
    log_mcp_event("server.tools_call", tool="arka_ask", status="ok", duration_ms=120)
    log_mcp_event("server.tools_call", tool="arka_ask", status="error", duration_ms=80, error="boom")
    log_mcp_event("client.call_tool", server="demo", tool="search", status="ok")

    stats = collect_mcp_stats()
    assert stats["available"] is True
    assert stats["total_calls"] == 2
    assert stats["tools"][0]["tool"] == "arka_ask"
    assert stats["tools"][0]["avg_ms"] == 100.0
    assert stats["error_count"] == 1
    assert len(stats["errors"]) == 1


def test_render_html_includes_mcp_section():
    data = {
        "generated_at": "2026-01-01T00:00:00Z",
        "skills": {"total": 3, "enabled": True, "skills": [("help", 2)], "path": "/tmp/skill-usage.json"},
        "mcp": {
            "available": True,
            "path": "/tmp/mcp.jsonl",
            "total_calls": 5,
            "first_ts": "a",
            "last_ts": "b",
            "status": {"ok": 5},
            "tools": [{"tool": "arka_ask", "count": 5, "avg_ms": 42.0}],
            "errors": [],
            "error_count": 0,
        },
    }
    html_doc = render_html(data)
    assert "arka_ask" in html_doc
    assert "42.0" in html_doc


def test_dashboard_handler_serves_html():
    handler = UsageDashboardHandler.__new__(UsageDashboardHandler)
    handler.headers = {}
    handler.requestline = "GET / HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.command = "GET"
    handler.wfile = io.BytesIO()

    handler.path = "/"
    handler.do_GET()
    raw = handler.wfile.getvalue().decode("utf-8")
    body = raw.split("\r\n\r\n", 1)[-1]
    assert "Arka usage dashboard" in body


def test_collect_data_includes_skill_and_mcp_sections():
    from arka.agent.usage_dashboard import collect_data

    payload = collect_data()
    assert "skills" in payload
    assert "mcp" in payload
    assert "generated_at" in payload


def test_serve_binds_dashboard_port(monkeypatch):
    seen = {}

    class FakeServer:
        def __init__(self, addr, handler):
            seen["addr"] = addr

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setenv("ARKA_DASHBOARD_PORT", "8799")
    monkeypatch.setattr("arka.agent.usage_dashboard.ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr("arka.agent.usage_dashboard.signal.signal", lambda *_a, **_k: None)

    assert serve() == 0
    assert seen["addr"] == ("127.0.0.1", 8799)


def test_main_defaults_to_build(tmp_path, capsys):
    out = tmp_path / "dash.html"
    assert main(["build", "--output", str(out)]) == 0
    assert out.is_file()
    assert "Usage dashboard:" in capsys.readouterr().out


def test_main_default_serve_flag(monkeypatch):
    called = {}

    def fake_serve(*, host=None, port=None):
        called["host"] = host
        called["port"] = port
        return 0

    import arka.agent.usage_dashboard as mod

    monkeypatch.setattr(mod, "serve", fake_serve)
    assert mod.main([], default_action="serve") == 0
    assert called == {"host": None, "port": None}
    assert mod.main(["--serve"], default_action="build") == 0
