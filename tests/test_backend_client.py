import io
import json
from unittest import mock


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_backend_status_uses_health_endpoint(monkeypatch, capsys):
    from arka.integrations import backend_client

    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return FakeResponse({"ok": True, "agent": "arka-test"})

    monkeypatch.setattr(backend_client.urllib.request, "urlopen", fake_urlopen)

    assert backend_client.main(["--url", "https://example.test", "status"]) == 0

    out = capsys.readouterr().out
    assert "Arka backend OK" in out
    assert "arka-test" in out
    assert seen == {"url": "https://example.test/v1/health", "auth": None}


def test_backend_ask_sends_bearer_token_and_prompt(monkeypatch, capsys):
    from arka.integrations import backend_client

    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        seen["data"] = json.loads(req.data.decode())
        return FakeResponse({"ok": True, "output": f"echo:{seen['data']['text']}", "exit_code": 0})

    monkeypatch.setenv("ARKA_BACKEND_TOKEN", "secret")
    monkeypatch.setattr(backend_client.urllib.request, "urlopen", fake_urlopen)

    assert backend_client.main(["--url", "https://example.test", "ask", "hello", "backend"]) == 0

    assert capsys.readouterr().out.strip() == "echo:hello backend"
    assert seen["url"] == "https://example.test/v1/agent"
    assert seen["auth"] == "Bearer secret"
    assert seen["data"]["text"] == "hello backend"


def test_backend_ask_requires_token(monkeypatch, capsys):
    from arka.integrations.backend_client import main

    monkeypatch.delenv("ARKA_BACKEND_TOKEN", raising=False)
    monkeypatch.delenv("ARKA_REMOTE_TOKEN", raising=False)
    monkeypatch.delenv("REMOTE_TOKEN", raising=False)

    assert main(["ask", "hi"]) == 2
    assert "Missing backend token" in capsys.readouterr().err


def test_backend_media_uploads_file(monkeypatch, tmp_path, capsys):
    from arka.integrations import backend_client

    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        seen["data"] = json.loads(req.data.decode())
        return FakeResponse(
            {
                "ok": True,
                "media": {
                    "name": seen["data"]["name"],
                    "type": seen["data"]["type"],
                    "bytes": len(seen["data"]["data"]),
                    "path": "/tmp/uploaded",
                },
            }
        )

    sample = tmp_path / "note.txt"
    sample.write_text("hello", encoding="utf-8")
    monkeypatch.setenv("REMOTE_TOKEN", "secret")
    monkeypatch.setattr(backend_client.urllib.request, "urlopen", fake_urlopen)

    assert backend_client.main(["--url", "https://example.test", "media", "--type", "text/plain", str(sample)]) == 0

    out = capsys.readouterr().out
    assert "Uploaded: note.txt" in out
    assert seen["url"] == "https://example.test/v1/media"
    assert seen["auth"] == "Bearer secret"
    assert seen["data"]["name"] == "note.txt"
    assert seen["data"]["type"] == "text/plain"


def test_request_json_parses_http_error(monkeypatch):
    from arka.integrations import backend_client
    from urllib.error import HTTPError

    err = HTTPError(
        "https://example.test/v1/agent",
        401,
        "Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b'{"ok":false,"error":"unauthorized"}'),
    )
    monkeypatch.setattr(backend_client.urllib.request, "urlopen", mock.Mock(side_effect=err))

    status, data = backend_client.request_json("/v1/agent", method="POST", payload={"text": "hi"})

    assert status == 401
    assert data["error"] == "unauthorized"
