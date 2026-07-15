from arka.agent.env_setup import create_env

def test_env_template_preserves_existing_values(tmp_path) -> None:
    (tmp_path / "app.py").write_text("import os\nos.environ.get('API_KEY')\nos.environ.get('PORT')\n")
    env = tmp_path / ".env"
    env.write_text("API_KEY=real-value\n")
    create_env(tmp_path)
    text = env.read_text()
    assert "API_KEY=real-value" in text
    assert "PORT=" in text
    assert "your-secret-here" not in text
