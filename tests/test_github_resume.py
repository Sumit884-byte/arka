import json
from pathlib import Path

import pytest


PROFILE = {
    "login": "devuser",
    "name": "Dev User",
    "bio": "Building tools with Python.",
    "location": "San Francisco",
    "company": "Acme",
    "blog": "https://dev.example",
    "email": "dev@example.com",
    "html_url": "https://github.com/devuser",
    "public_repos": 12,
    "followers": 42,
    "created_at": "2018-05-01T00:00:00Z",
}

REPOS = [
    {
        "name": "arka",
        "full_name": "devuser/arka",
        "description": "Agent toolkit",
        "html_url": "https://github.com/devuser/arka",
        "language": "Python",
        "stargazers_count": 120,
        "forks_count": 8,
        "topics": ["agents", "cli"],
        "updated_at": "2026-01-01T00:00:00Z",
        "fork": False,
    },
    {
        "name": "notes",
        "full_name": "devuser/notes",
        "description": "Personal notes",
        "html_url": "https://github.com/devuser/notes",
        "language": "Markdown",
        "stargazers_count": 3,
        "forks_count": 0,
        "topics": [],
        "updated_at": "2026-01-02T00:00:00Z",
        "fork": False,
    },
]


def _fake_github_get(path: str, *, params=None):
    if path == "/user":
        return {"login": "tokenuser", "name": "Token User"}
    if path == "/users/devuser":
        return PROFILE
    if path == "/users/tokenuser":
        return {
            **PROFILE,
            "login": "tokenuser",
            "name": "Token User",
            "html_url": "https://github.com/tokenuser",
            "public_repos": 16,
            "created_at": "2024-01-15T00:00:00Z",
        }
    if path in ("/users/devuser/repos", "/users/tokenuser/repos"):
        return REPOS
    raise AssertionError(f"unexpected github path: {path} params={params}")


def test_resolve_username_accepts_handle_and_url():
    from arka.agent.github_resume import resolve_username

    assert resolve_username("devuser") == "devuser"
    assert resolve_username("https://github.com/devuser") == "devuser"
    assert resolve_username("@devuser") == "devuser"


def test_resolve_username_from_token_only(monkeypatch):
    from arka.agent import github_resume as gr

    monkeypatch.delenv("GITHUB_USERNAME", raising=False)
    monkeypatch.delenv("GITHUB_USER", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")

    def fake_get(path: str, *, params=None):
        assert path == "/user"
        return {"login": "tokenuser", "name": "Token User"}

    monkeypatch.setattr(gr, "_github_get", fake_get)
    monkeypatch.setattr(gr, "_gh_current_user", lambda: None)
    monkeypatch.setattr(gr, "load_env_file", lambda: None)

    assert gr.resolve_username() == "tokenuser"


def test_generate_resume_with_token_only(monkeypatch, tmp_path):
    pytest.importorskip("reportlab")
    from arka.agent import github_resume as gr

    monkeypatch.delenv("GITHUB_USERNAME", raising=False)
    monkeypatch.delenv("GITHUB_USER", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")
    monkeypatch.setattr(gr, "_github_get", _fake_github_get)
    monkeypatch.setattr(gr, "_gh_current_user", lambda: None)
    monkeypatch.setattr(gr, "load_env_file", lambda: None)
    monkeypatch.setattr(gr, "generated_data_dir", lambda: tmp_path)

    result = gr.generate_resume(write_markdown=False, style="modern")

    assert result["ok"] is True
    assert result["username"] == "tokenuser"
    assert result["public_repos"] == 2
    assert result["repo_count"] == 2
    assert result["member_since"] == "2024"
    assert result["username_source"] == "token"
    assert result["about_me_source"] == "bio"
    assert "Building tools with Python." in result["about_me"]
    assert Path(result["pdf_path"]).is_file()


def test_build_markdown_includes_profile_and_projects(monkeypatch):
    from arka.agent import github_resume as gr
    from arka.agent.github_resume import GitHubProfile, GitHubRepo, build_markdown

    monkeypatch.setattr(gr, "load_env_file", lambda: None)
    monkeypatch.delenv("RESUME_NAME", raising=False)
    monkeypatch.delenv("USER_FULL_NAME", raising=False)
    monkeypatch.delenv("FULL_NAME", raising=False)

    profile = GitHubProfile(
        login="devuser",
        name="Dev User",
        bio="Building tools with Python.",
        location="San Francisco",
        company="Acme",
        blog="https://dev.example",
        email="dev@example.com",
        html_url="https://github.com/devuser",
        public_repos=12,
        followers=42,
        created_at="2018-05-01T00:00:00Z",
    )
    repos = [
        GitHubRepo(
            name="arka",
            full_name="devuser/arka",
            description="Agent toolkit",
            html_url="https://github.com/devuser/arka",
            language="Python",
            stargazers_count=120,
            forks_count=8,
            topics=("agents", "cli"),
            updated_at="2026-01-01T00:00:00Z",
        )
    ]
    md = build_markdown(profile, repos)
    assert "# Dev User" in md
    assert "## About Me" in md
    assert "Building tools with Python." in md
    assert "### arka" in md
    assert "Agent toolkit" in md


def test_build_markdown_synthesizes_about_me_when_bio_empty(monkeypatch):
    from arka.agent import github_resume as gr
    from arka.agent.github_resume import GitHubProfile, GitHubRepo, build_markdown

    monkeypatch.setattr(gr, "load_env_file", lambda: None)
    monkeypatch.delenv("RESUME_NAME", raising=False)
    monkeypatch.delenv("USER_FULL_NAME", raising=False)
    monkeypatch.delenv("FULL_NAME", raising=False)

    profile = GitHubProfile(
        login="devuser",
        name="Dev User",
        bio="",
        location="San Francisco",
        company="Acme",
        blog="",
        email="",
        html_url="https://github.com/devuser",
        public_repos=12,
        followers=42,
        created_at="2018-05-01T00:00:00Z",
    )
    repos = [
        GitHubRepo(
            name="arka",
            full_name="devuser/arka",
            description="Agent toolkit",
            html_url="https://github.com/devuser/arka",
            language="Python",
            stargazers_count=120,
            forks_count=8,
            topics=("agents", "cli"),
            updated_at="2026-01-01T00:00:00Z",
        )
    ]
    md = build_markdown(profile, repos)
    assert "## About Me" in md
    assert "I'm a developer at Acme." in md
    assert "I maintain 1 public project." in md
    assert "My primary language is Python." in md
    assert "I'm based in San Francisco." in md


def test_resolve_about_me_prefers_bio_then_profile_readme(monkeypatch):
    from arka.agent import github_resume as gr
    from arka.agent.github_resume import GitHubProfile, GitHubRepo

    profile = GitHubProfile(
        login="devuser",
        name="Dev User",
        bio="Building tools with Python.",
        location="",
        company="",
        blog="",
        email="",
        html_url="https://github.com/devuser",
        public_repos=1,
        followers=0,
        created_at="2018-05-01T00:00:00Z",
    )
    repos: list[GitHubRepo] = []

    text, source = gr.resolve_about_me(profile, repos)
    assert text == "Building tools with Python."
    assert source == "bio"

    empty_bio = GitHubProfile(
        login=profile.login,
        name=profile.name,
        bio="",
        location=profile.location,
        company=profile.company,
        blog=profile.blog,
        email=profile.email,
        html_url=profile.html_url,
        public_repos=profile.public_repos,
        followers=profile.followers,
        created_at=profile.created_at,
    )
    monkeypatch.setattr(gr, "fetch_profile_readme", lambda username: "Profile README intro.")
    text, source = gr.resolve_about_me(empty_bio, repos)
    assert text == "Profile README intro."
    assert source == "profile_readme"


def test_fetch_profile_readme_decodes_github_payload(monkeypatch):
    import base64

    from arka.agent import github_resume as gr

    encoded = base64.b64encode(b"# Dev User\n\nOpen-source builder.").decode("ascii")

    def fake_get(path: str, *, params=None):
        assert path == "/repos/devuser/devuser/readme"
        return {"encoding": "base64", "content": encoded}

    monkeypatch.setattr(gr, "_github_get", fake_get)
    assert gr.fetch_profile_readme("devuser") == "Open-source builder."


def test_generate_resume_writes_pdf_and_markdown(monkeypatch, tmp_path):
    pytest.importorskip("reportlab")
    from arka.agent import github_resume as gr

    monkeypatch.setattr(gr, "_github_get", _fake_github_get)
    monkeypatch.setattr(gr, "generated_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        gr,
        "resolve_display_name",
        lambda profile: profile.name.strip() or profile.login,
    )

    result = gr.generate_resume("devuser", write_markdown=True, style="modern")

    pdf_path = Path(result["pdf_path"])
    md_path = Path(result["markdown_path"])
    assert result["ok"] is True
    assert result["username"] == "devuser"
    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 100
    assert md_path.is_file()
    md_text = md_path.read_text(encoding="utf-8")
    assert "Dev User" in md_text
    assert "## About Me" in md_text
    assert "Building tools with Python." in md_text


def test_route_command_maps_natural_language():
    from arka.agent.github_resume import route_command

    assert route_command("generate resume from my github profile") == "github resume"
    assert route_command("create resume from github") == "github resume"
    assert route_command("github resume") == "github resume"
    assert route_command("create a github resume for devuser") == "github resume --user devuser"
    assert route_command("resume from https://github.com/devuser") == "github resume --user devuser"


def test_symbolic_route_github_resume():
    from arka.routing.symbolic import route_offline_extras

    assert route_offline_extras("generate resume from my github profile") == "github resume"
    assert route_offline_extras("create resume from github") == "github resume"
    assert route_offline_extras("github resume") == "github resume"


def test_router_routes_github_resume_without_llm():
    from arka.router import route, route_preview

    for phrase in (
        "generate resume from my github profile",
        "create resume from github",
        "github resume",
    ):
        hit = route(phrase)
        assert hit is not None, phrase
        assert hit.skill == "github resume", phrase
        assert hit.source == "offline", phrase
        preview = route_preview(phrase)
        assert preview is not None, phrase
        assert preview.skill == "github resume", phrase


def test_fish_route_preview_github_resume():
    try:
        from arka.fish_bridge import _find_fish, fish_route_preview
    except ImportError:
        pytest.skip("fish_bridge unavailable")
    if _find_fish() is None:
        pytest.skip("fish not installed")

    preview = fish_route_preview("generate resume from my github profile")
    assert preview is not None
    assert preview.action == "github resume"


def test_cli_github_resume_direct_command(monkeypatch, capsys, tmp_path):
    pytest.importorskip("reportlab")
    from arka import cli
    from arka.agent import github_resume as gr

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr(gr, "_github_get", _fake_github_get)
    monkeypatch.setattr(gr, "generated_data_dir", lambda: tmp_path)

    assert cli.main(["github", "resume", "--user", "devuser", "--json"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["username"] == "devuser"
    assert Path(payload["pdf_path"]).is_file()


def test_mcp_github_resume_action(monkeypatch, tmp_path):
    pytest.importorskip("reportlab")
    from arka.agent import github_resume as gr
    from arka.integrations.mcp_server import _handle_arka_github

    monkeypatch.setattr(gr, "_github_get", _fake_github_get)
    monkeypatch.setattr(gr, "generated_data_dir", lambda: tmp_path)

    raw = _handle_arka_github({"action": "resume", "username": "devuser", "markdown": True})
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["username"] == "devuser"
    assert Path(payload["pdf_path"]).is_file()
    assert Path(payload["markdown_path"]).is_file()


def test_explicit_user_uses_requested_profile_not_token_holder(monkeypatch, tmp_path):
    pytest.importorskip("reportlab")
    from arka.agent import github_resume as gr

    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")
    monkeypatch.setattr(gr, "_github_get", _fake_github_get)
    monkeypatch.setattr(gr, "_gh_current_user", lambda: None)
    monkeypatch.setattr(gr, "load_env_file", lambda: None)
    monkeypatch.setattr(gr, "generated_data_dir", lambda: tmp_path)

    result = gr.generate_resume("devuser", write_markdown=True)

    assert result["ok"] is True
    assert result["username"] == "devuser"
    assert result["public_repos"] == 2
    assert result["repo_count"] == 2
    assert result["public_repos_profile"] == 12
    assert result["member_since"] == "2018"
    assert result["username_source"] == "explicit"
    assert result["authenticated_as"] == "tokenuser"
    assert "token is authenticated as tokenuser" in result["auth_note"]
    md_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "2 public projects" in md_text
    assert "GitHub member since 2018" in md_text
    assert "token is authenticated as tokenuser" in md_text


def test_profile_stats_lines_use_member_year_only():
    from arka.agent.github_resume import GitHubProfile, profile_stats_lines

    profile = GitHubProfile(
        login="devuser",
        name="Dev User",
        bio="",
        location="",
        company="",
        blog="",
        email="",
        html_url="https://github.com/devuser",
        public_repos=7,
        followers=0,
        created_at="2012-05-22T07:15:25Z",
    )
    assert profile_stats_lines(profile) == ["7 public projects", "GitHub member since 2012"]


def test_github_token_falls_back_to_gh_auth(monkeypatch):
    from arka.agent import github_resume as gr

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("github_token", raising=False)
    monkeypatch.setattr(gr, "env_get", lambda key, default="": default)
    monkeypatch.setattr(gr, "_gh_auth_token", lambda: "gh-token-from-cli")
    assert gr._github_token() == "gh-token-from-cli"


def test_resolve_display_name_prefers_env(monkeypatch):
    from arka.agent import github_resume as gr
    from arka.agent.github_resume import GitHubProfile

    profile = GitHubProfile(
        login="devuser",
        name="Dev User",
        bio="",
        location="",
        company="",
        blog="",
        email="",
        html_url="https://github.com/devuser",
        public_repos=2,
        followers=0,
        created_at="2018-05-01T00:00:00Z",
    )
    monkeypatch.setenv("RESUME_NAME", "Sumit Mishra")
    monkeypatch.setattr(gr, "load_env_file", lambda: None)
    assert gr.resolve_display_name(profile) == "Sumit Mishra"


def test_fetch_non_fork_repos_skips_forks(monkeypatch):
    from arka.agent import github_resume as gr

    rows = [
        *REPOS,
        {
            "name": "forked-tool",
            "full_name": "devuser/forked-tool",
            "description": "A fork",
            "html_url": "https://github.com/devuser/forked-tool",
            "language": "Python",
            "stargazers_count": 99,
            "forks_count": 0,
            "topics": [],
            "updated_at": "2026-01-03T00:00:00Z",
            "fork": True,
        },
    ]

    def fake_get(path: str, *, params=None):
        assert path == "/users/devuser/repos"
        return rows

    monkeypatch.setattr(gr, "_github_get", fake_get)
    repos = gr.fetch_non_fork_repos("devuser")
    assert [repo.name for repo in repos] == ["arka", "notes"]
    assert gr.fetch_non_fork_repos("devuser", limit=1)[0].name == "arka"


def test_resolve_username_detailed_marks_explicit_source():
    from arka.agent.github_resume import resolve_username_detailed

    resolved = resolve_username_detailed("sumitmishra")
    assert resolved.login == "sumitmishra"
    assert resolved.source == "explicit"
    assert resolved.requested == "sumitmishra"
