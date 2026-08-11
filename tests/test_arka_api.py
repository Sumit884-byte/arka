import io
import json

from arka.integrations.ollama_tunnel import RateLimiter


def _handler(monkeypatch, *, path: str, method: str = "GET", headers=None, body: bytes = b"", rpm: int = 60):
    from arka.integrations import arka_api

    monkeypatch.setenv("ARKA_API_TOKEN", "test-token")

    class MockServer:
        rate_limiter = RateLimiter(rpm)

    class Handler(arka_api.ArkaApiHandler):
        def __init__(self):
            self.server = MockServer()
            self.headers = headers or {}
            self.client_address = ("127.0.0.1", 54321)
            self.wfile = io.BytesIO()
            self.rfile = io.BytesIO(body)
            self.path = path
            self.status = 0

        def send_response(self, code):
            self.status = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

    handler = Handler()
    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    payload = json.loads(handler.wfile.getvalue().decode("utf-8") or "{}")
    return handler.status, payload


def test_health_does_not_require_auth(monkeypatch):
    status, payload = _handler(monkeypatch, path="/v1/health")
    assert status == 200
    assert payload["ok"] is True
    assert payload["service"] == "arka-api"


def test_models_requires_bearer_token(monkeypatch):
    status, payload = _handler(monkeypatch, path="/v1/models")
    assert status == 401
    assert payload["error"] == "unauthorized"

    status, payload = _handler(
        monkeypatch,
        path="/v1/models",
        headers={"Authorization": "Bearer test-token"},
    )
    assert status == 200
    assert payload["object"] == "list"


def test_chat_completions_requires_bearer_token(monkeypatch):
    body = json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode()
    status, payload = _handler(
        monkeypatch,
        path="/v1/chat/completions",
        method="POST",
        body=body,
        headers={"Content-Length": str(len(body))},
    )
    assert status == 401
    assert payload["error"] == "unauthorized"


def test_x_arka_token_header_accepted(monkeypatch):
    status, payload = _handler(
        monkeypatch,
        path="/v1/models",
        headers={"X-Arka-Token": "test-token"},
    )
    assert status == 200
    assert payload["object"] == "list"


def test_rate_limit_returns_429(monkeypatch):
    from arka.integrations import arka_api

    limiter = RateLimiter(1)

    class MockServer:
        rate_limiter = limiter

    class Handler(arka_api.ArkaApiHandler):
        def __init__(self):
            self.server = MockServer()
            self.headers = {}
            self.client_address = ("127.0.0.1", 54321)
            self.wfile = io.BytesIO()
            self.rfile = io.BytesIO()
            self.path = "/v1/health"
            self.status = 0

        def send_response(self, code):
            self.status = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

    first = Handler()
    first.do_GET()
    assert first.status == 200

    second = Handler()
    second.do_GET()
    payload = json.loads(second.wfile.getvalue().decode("utf-8"))
    assert second.status == 429
    assert payload["error"] == "rate limit exceeded"


def test_serve_refuses_without_token(monkeypatch):
    from arka.integrations import arka_api

    monkeypatch.setenv("ARKA_API_ENABLED", "1")
    monkeypatch.delenv("ARKA_API_TOKEN", raising=False)
    monkeypatch.delenv("REMOTE_TOKEN", raising=False)
    assert arka_api.serve() == 1


def test_serve_binds_localhost(monkeypatch, tmp_path):
    from arka.integrations import arka_api

    seen = {}

    class FakeServer:
        def __init__(self, addr, handler):
            seen["addr"] = addr

        def serve_forever(self):
            return None

    monkeypatch.setenv("ARKA_API_ENABLED", "1")
    monkeypatch.setenv("ARKA_API_TOKEN", "secret")
    monkeypatch.delenv("ARKA_API_HOST", raising=False)
    monkeypatch.setattr(arka_api, "CACHE", tmp_path)
    monkeypatch.setattr(arka_api, "PID_PATH", tmp_path / "arka_api.pid")
    monkeypatch.setattr(arka_api, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(arka_api.signal, "signal", lambda *_a, **_k: None)

    assert arka_api.serve() == 0
    assert seen["addr"] == ("127.0.0.1", 8768)


def test_security_findings_flags_enabled_api_without_token(monkeypatch):
    from arka.core import api_security

    monkeypatch.setenv("ARKA_API_ENABLED", "1")
    monkeypatch.delenv("ARKA_API_TOKEN", raising=False)
    monkeypatch.delenv("REMOTE_TOKEN", raising=False)
    findings = api_security.security_findings()
    assert any(f.severity == "critical" and "ARKA_API" in f.message for f in findings)
