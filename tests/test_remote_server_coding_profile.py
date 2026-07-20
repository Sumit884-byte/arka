from unittest import mock
import base64


def test_coding_remote_reports_capabilities():
    from arka.integrations.remote_server import run_coding_remote

    output, speak, code = run_coding_remote("capabilities")

    assert code == 0
    assert "repo_health" in output
    assert "github_repo" in output
    assert "GitHub URL" in output
    assert speak


def test_coding_remote_greeting_does_not_route_to_blocked_skill():
    from arka.integrations.remote_server import run_coding_remote

    output, speak, code = run_coding_remote("hi")

    assert code == 0
    assert "hosted coding demo" in output
    assert "Blocked in Railway coding profile" not in output
    assert speak == output


def test_remote_demo_ui_is_react_chat_shell():
    from arka.integrations.remote_server import MOBILE_HTML

    assert "ReactDOM.createRoot" in MOBILE_HTML
    assert "Ask Arka to inspect, test, or edit" in MOBILE_HTML
    assert 'fetch("/v1/agent"' in MOBILE_HTML
    assert 'fetch("/v1/media"' in MOBILE_HTML
    assert "attach screenshots, videos, audio, PDFs" in MOBILE_HTML
    assert "Paste a GitHub repo URL" in MOBILE_HTML
    assert "init https://github.com/org/repo" in MOBILE_HTML
    assert "Authorization" in MOBILE_HTML
    assert "Arka Codex" in MOBILE_HTML
    assert "AI coding workspace" in MOBILE_HTML
    assert "hosted / coding" in MOBILE_HTML
    assert "ArkaErrorBoundary" in MOBILE_HTML
    assert "chat has-messages" in MOBILE_HTML
    assert "overflow-wrap:anywhere" in MOBILE_HTML
    assert "endRef.current?.scrollIntoView" in MOBILE_HTML
    assert "useEffect(() => endRef.current?.scrollIntoView" not in MOBILE_HTML
    assert "lightweight ChatGPT-style console" not in MOBILE_HTML


def test_remote_github_repo_url_parsing():
    from arka.integrations import remote_server

    repo = remote_server.parse_github_repo_url("init https://github.com/Owner/my-repo.git for coding")

    assert repo is not None
    assert repo.owner == "Owner"
    assert repo.repo == "my-repo"
    assert repo.url == "https://github.com/Owner/my-repo.git"
    assert str(repo.path).endswith("remote-repos/Owner/my-repo")


def test_remote_github_init_intent_detection():
    from arka.integrations.remote_server import wants_remote_repo_init

    assert wants_remote_repo_init("init this repo https://github.com/foo/bar")
    assert wants_remote_repo_init("code init https://github.com/foo/bar")
    assert not wants_remote_repo_init("what changed in https://github.com/foo/bar yesterday")


def test_remote_github_workspace_clone_initializes_code_project(tmp_path, monkeypatch):
    from arka.integrations import remote_server

    calls = []

    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        target = tmp_path / "remote-repos" / "foo" / "bar"
        (target / ".git").mkdir(parents=True, exist_ok=True)
        return Proc()

    initialized = {}
    monkeypatch.setattr(remote_server, "REMOTE_REPOS_DIR", tmp_path / "remote-repos")
    monkeypatch.setattr(remote_server.subprocess, "run", fake_run)
    monkeypatch.setattr("arka.core.code_project.init_project", lambda path: initialized.setdefault("path", path))

    root, msg, code = remote_server.ensure_remote_github_workspace("init https://github.com/foo/bar")

    assert code == 0
    assert root == tmp_path / "remote-repos" / "foo" / "bar"
    assert initialized["path"] == root
    assert calls[0][:3] == ["git", "clone", "--depth"]
    assert "Code workspace cloned: foo/bar" in msg


def test_remote_github_workspace_auth_failure_explains_gh_token(tmp_path, monkeypatch):
    from arka.integrations import remote_server

    class Proc:
        returncode = 128
        stdout = ""
        stderr = "fatal: Authentication failed for token-secret"

    monkeypatch.setattr(remote_server, "REMOTE_REPOS_DIR", tmp_path / "remote-repos")
    monkeypatch.setenv("GH_TOKEN", "token-secret")
    monkeypatch.setattr(remote_server.subprocess, "run", lambda *a, **k: Proc())

    root, msg, code = remote_server.ensure_remote_github_workspace("init https://github.com/foo/private")

    assert root is None
    assert code == 128
    assert "GH_TOKEN or GITHUB_TOKEN" in msg
    assert "gh auth login" in msg
    assert "token-secret" not in msg


def test_remote_media_upload_saves_sanitized_file(tmp_path, monkeypatch):
    from arka.integrations import remote_server

    monkeypatch.setattr(remote_server, "UPLOAD_DIR", tmp_path)
    media = remote_server.save_media_upload(
        {
            "name": "../screen shot.png",
            "type": "image/png",
            "data": base64.b64encode(b"png-ish").decode("ascii"),
        }
    )

    assert media["name"] == "screen-shot.png"
    assert media["type"] == "image/png"
    assert media["bytes"] == len(b"png-ish")
    assert media["path"].startswith(str(tmp_path))
    assert (tmp_path / f"{media['id']}-screen-shot.png").read_bytes() == b"png-ish"


def test_coding_remote_blocks_non_coding_skill(monkeypatch):
    from arka.integrations import remote_server

    class Decision:
        skill = "play_spotify song"

    monkeypatch.setattr("arka.router.route", lambda text: Decision())

    output, _speak, code = remote_server.run_coding_remote("play music")

    assert code == 2
    assert "Blocked in Railway coding profile" in output


def test_coding_remote_runs_allowed_skill(monkeypatch):
    from arka.integrations import remote_server

    class Decision:
        skill = "repo_health scan"

    monkeypatch.setattr("arka.router.route", lambda text: Decision())
    ran = {}

    def fake_run_skill(line):
        ran["line"] = line
        print("repo health ok")
        return 0

    monkeypatch.setattr("arka.dispatch.run_skill", fake_run_skill)

    output, _speak, code = remote_server.run_coding_remote("check repo health")

    assert code == 0
    assert ran["line"] == "repo_health scan"
    assert "repo health ok" in output


def test_serve_uses_railway_port_and_hosted_defaults(monkeypatch):
    from arka.integrations import remote_server

    seen = {}

    class FakeServer:
        def __init__(self, addr, handler):
            seen["addr"] = addr

        def serve_forever(self):
            return None

    monkeypatch.setenv("PORT", "9999")
    monkeypatch.setenv("ARKA_REMOTE_PROFILE", "coding")
    monkeypatch.setenv("REMOTE_TOKEN", "token")
    monkeypatch.setattr(remote_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(remote_server, "write_pid", lambda: None)
    monkeypatch.setattr(remote_server, "remove_pid", lambda: None)
    monkeypatch.setattr(remote_server, "local_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(remote_server.signal, "signal", mock.Mock())

    assert remote_server.serve() == 0
    assert seen["addr"] == ("0.0.0.0", 9999)
