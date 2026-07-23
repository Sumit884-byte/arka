from arka.agent.env_setup import create_env, fill_env_from_source, scan_source_constants


def test_env_template_preserves_existing_values(tmp_path) -> None:
    (tmp_path / "app.py").write_text("import os\nos.environ.get('API_KEY')\nos.environ.get('PORT')\n")
    env = tmp_path / ".env"
    env.write_text("API_KEY=real-value\n")
    create_env(tmp_path)
    text = env.read_text()
    assert "API_KEY=real-value" in text
    assert "PORT=" in text
    assert "your-secret-here" not in text


def test_scan_source_constants(tmp_path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "constants.py").write_text(
        'LINKEDIN_USERNAME = "ceo@company.com"\n'
        'LINKEDIN_PASSWORD = "s3cret"\n'
        'DEBUG = True\n'
    )
    found = scan_source_constants(tmp_path)
    assert found["LINKEDIN_USERNAME"] == "ceo@company.com"
    assert found["LINKEDIN_PASSWORD"] == "s3cret"
    assert "DEBUG" not in found


def test_fill_env_from_source_applies_matching_keys(tmp_path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "constants.py").write_text('LINKEDIN_USERNAME = "ceo@company.com"\n')
    (tmp_path / "app.py").write_text("import os\nos.environ.get('LINKEDIN_USERNAME')\n")

    dest, additions, _ = fill_env_from_source(tmp_path, apply=True)
    text = dest.read_text()
    assert additions == {"LINKEDIN_USERNAME": "ceo@company.com"}
    assert "LINKEDIN_USERNAME=ceo@company.com" in text


def test_fill_env_from_source_does_not_overwrite_existing(tmp_path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "constants.py").write_text('API_KEY = "from-constants"\n')
    (tmp_path / "app.py").write_text("import os\nos.environ.get('API_KEY')\n")
    env = tmp_path / ".env"
    env.write_text("API_KEY=keep-me\n")

    _, additions, _ = fill_env_from_source(tmp_path, apply=True)
    assert additions == {}
    assert env.read_text().strip() == "API_KEY=keep-me"
