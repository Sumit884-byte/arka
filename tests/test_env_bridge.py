from pathlib import Path

from arka.agent.env_bridge import _apply_aliases, _parse_env_file, bridge_env


def test_apply_aliases_maps_linkedin_email() -> None:
    out, mapping = _apply_aliases({"linkedin_email": "u@example.com"}, {"linkedin_email": "LINKEDIN_USERNAME"})
    assert out["LINKEDIN_USERNAME"] == "u@example.com"
    assert mapping["LINKEDIN_USERNAME"] == "linkedin_email"


def test_bridge_updates_existing_project_keys(tmp_path, monkeypatch) -> None:
    project = tmp_path / "bot"
    project.mkdir()
    (project / "app.py").write_text(
        "import os\nos.environ.get('LINKEDIN_USERNAME')\nos.environ.get('LINKEDIN_PASSWORD')\n"
    )
    (project / ".env").write_text("LINKEDIN_USERNAME=old@example.com\n")
    arka_env = tmp_path / "arka.env"
    arka_env.write_text("linkedin_email=new@example.com\nlinkedin_password=secret\n")

    target, additions, _ = bridge_env(
        project,
        source_file=arka_env,
        update_existing=True,
        apply=True,
    )
    text = target.read_text()
    assert "LINKEDIN_USERNAME=new@example.com" in text
    assert "LINKEDIN_PASSWORD=secret" in text
    assert "old@example.com" not in text
    assert set(additions) == {"LINKEDIN_USERNAME", "LINKEDIN_PASSWORD"}


def test_plan_discovers_required_then_resolves(tmp_path) -> None:
    project = tmp_path / "bot"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "constants.py").write_text(
        'LINKEDIN_SEARCH_KEYWORDS = "mits"\nLINKEDIN_NAME = "Bot Name"\n'
    )
    (project / "app.py").write_text(
        "import os\n"
        "os.environ.get('LINKEDIN_USERNAME')\n"
        "os.environ.get('LINKEDIN_PASSWORD')\n"
        "os.environ.get('LINKEDIN_SEARCH_KEYWORDS')\n"
    )
    arka_env = tmp_path / "arka.env"
    arka_env.write_text("linkedin_email=u@example.com\nlinkedin_password=secret\n")

    from arka.agent.env_bridge import apply_env_bridge, plan_env_bridge

    plan = plan_env_bridge(project, source_file=arka_env, update_existing=True)
    assert plan.required == ["LINKEDIN_PASSWORD", "LINKEDIN_SEARCH_KEYWORDS", "LINKEDIN_USERNAME"]
    assert plan.from_arka["LINKEDIN_USERNAME"] == "u@example.com"
    assert plan.from_constants["LINKEDIN_SEARCH_KEYWORDS"] == "mits"
    assert apply_env_bridge(plan) == 3
    text = plan.target.read_text()
    assert "LINKEDIN_USERNAME=u@example.com" in text
    assert "LINKEDIN_PASSWORD=secret" in text
    assert "LINKEDIN_SEARCH_KEYWORDS=mits" in text


def test_parse_env_file_skips_placeholders(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text("REAL_KEY=abc\nFAKE_KEY=your-secret-here\n")
    parsed = _parse_env_file(path)
    assert parsed == {"REAL_KEY": "abc"}
