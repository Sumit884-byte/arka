import io
import json
from unittest import mock


def test_safe_ollama_host_rewrites_public_bind(monkeypatch):
    from arka.core import api_security

    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    assert api_security.safe_ollama_host() == "127.0.0.1:11434"


def test_resolve_remote_host_defaults_local(monkeypatch):
    from arka.core import api_security

    monkeypatch.delenv("REMOTE_HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert api_security.resolve_remote_host() == "127.0.0.1"


def test_resolve_remote_host_uses_port_env_for_cloud(monkeypatch):
    from arka.core import api_security

    monkeypatch.delenv("REMOTE_HOST", raising=False)
    monkeypatch.setenv("PORT", "8080")
    assert api_security.resolve_remote_host() == "0.0.0.0"


def test_security_findings_flags_public_ollama(monkeypatch):
    from arka.core import api_security

    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    monkeypatch.setenv("REMOTE_HOST", "127.0.0.1")
    monkeypatch.setenv("REMOTE_TOKEN", "secret-token")
    findings = api_security.security_findings()
    assert any(f.severity == "critical" and "OLLAMA_HOST" in f.message for f in findings)


def test_doctor_lines_include_mcp_note(monkeypatch):
    from arka.core import api_security

    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    monkeypatch.setenv("REMOTE_HOST", "127.0.0.1")
    monkeypatch.setenv("REMOTE_TOKEN", "secret-token")
    lines = api_security.doctor_lines()
    assert any("API security" in line for line in lines)
    assert any("stdio-only" in line for line in lines)
    assert any("ARKA_API_TOKEN" in line for line in lines)


def test_security_findings_flags_public_arka_api(monkeypatch):
    from arka.core import api_security

    monkeypatch.setenv("ARKA_API_ENABLED", "1")
    monkeypatch.setenv("ARKA_API_HOST", "0.0.0.0")
    monkeypatch.setenv("ARKA_API_TOKEN", "secret-token")
    findings = api_security.security_findings()
    assert any(f.severity == "warn" and "Arka API" in f.message for f in findings)


def test_remote_check_auth_requires_token(monkeypatch):
    from arka.integrations.remote_server import ArkaRemoteHandler

    monkeypatch.delenv("REMOTE_TOKEN", raising=False)

    class Handler(ArkaRemoteHandler):
        def __init__(self):
            self.headers = {}

    assert Handler()._check_auth() is False

    monkeypatch.setenv("REMOTE_TOKEN", "abc")
    assert Handler()._check_auth() is False

    class Authed(ArkaRemoteHandler):
        def __init__(self):
            self.headers = {"Authorization": "Bearer abc"}

    assert Authed()._check_auth() is True


def test_remote_get_handoff_requires_auth(monkeypatch):
    from arka.integrations import remote_server

    monkeypatch.setenv("REMOTE_TOKEN", "test-token")

    class Handler(remote_server.ArkaRemoteHandler):
        requestline = "GET /v1/handoff HTTP/1.1"
        request_version = "HTTP/1.1"
        command = "GET"
        path = "/v1/handoff"

        def __init__(self):
            self.headers = {}
            self.wfile = io.BytesIO()
            self.rfile = io.BytesIO()

        def send_response(self, code):
            self.status = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

    handler = Handler()
    handler.do_GET()
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status == 401
    assert payload["ok"] is False

    handler = Handler()
    handler.headers = {"Authorization": "Bearer test-token"}
    handler.wfile = io.BytesIO()
    handler.do_GET()
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status == 200
    assert payload["ok"] is True


def test_serve_local_bind_without_port(monkeypatch):
    from arka.integrations import remote_server

    seen = {}

    class FakeServer:
        def __init__(self, addr, handler):
            seen["addr"] = addr

        def serve_forever(self):
            return None

    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("REMOTE_HOST", raising=False)
    monkeypatch.setenv("REMOTE_TOKEN", "token")
    monkeypatch.setattr(remote_server, "_bootstrap_env", lambda: None)
    monkeypatch.setattr(remote_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(remote_server, "write_pid", lambda: None)
    monkeypatch.setattr(remote_server, "remove_pid", lambda: None)
    monkeypatch.setattr(remote_server.signal, "signal", mock.Mock())

    assert remote_server.serve() == 0
    assert seen["addr"] == ("127.0.0.1", 8765)


def test_serve_uses_railway_port_and_hosted_defaults(monkeypatch):
    from arka.integrations import remote_server

    seen = {}

    class FakeServer:
        def __init__(self, addr, handler):
            seen["addr"] = addr

        def serve_forever(self):
            return None

    monkeypatch.setenv("PORT", "9999")
    monkeypatch.delenv("REMOTE_HOST", raising=False)
    monkeypatch.setenv("ARKA_REMOTE_PROFILE", "coding")
    monkeypatch.setenv("REMOTE_TOKEN", "token")
    monkeypatch.setattr(remote_server, "_bootstrap_env", lambda: None)
    monkeypatch.setattr(remote_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(remote_server, "write_pid", lambda: None)
    monkeypatch.setattr(remote_server, "remove_pid", lambda: None)
    monkeypatch.setattr(remote_server, "local_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(remote_server.signal, "signal", mock.Mock())

    assert remote_server.serve() == 0
    assert seen["addr"] == ("0.0.0.0", 9999)
