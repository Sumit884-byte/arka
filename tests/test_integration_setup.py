from arka.agent import integration_setup


def test_integration_setup_status_includes_common_tools(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    assert integration_setup.main(["status"]) == 0
    output = capsys.readouterr().out
    assert "context7\tmissing" in output
    assert "supermemory" in output
    assert "github" in output
    assert "sentry" in output
    assert "huggingface" in output
    assert "notion" in output
    assert "supabase" in output
    assert "netlify" in output
    assert "dockerhub" in output
    assert "postgres" in output
    assert "datadog" in output
    assert "langfuse" in output
    assert "langsmith" in output
    assert "modal" in output
    assert "ollama" in output
    assert "groq" in output
    assert "cloudflare" in output
    assert "resend" in output
    assert "clerk" in output
    assert "posthog" in output
    assert "launchdarkly" in output
    assert "telegram" in output


def test_integration_setup_writes_key(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    assert integration_setup.main(["setup", "tavily", "--key", "demo"]) == 0
    assert "TAVILY_API_KEY=demo" in target.read_text()


def test_integration_doctor_is_non_secret_and_actionable(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert integration_setup.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "openrouter" in output
    assert "OPENROUTER_API_KEY" not in output


def test_interactive_setup_prompts_when_key_is_missing(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "prompted-key")
    assert integration_setup.main(["setup", "context7"]) == 0
    assert "CONTEXT7_API_KEY=prompted-key" in target.read_text()


def test_integration_setup_quotes_keys_with_spaces(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["setup", "google", "--key", "key with spaces"]) == 0
    assert "GOOGLE_API_KEY='key with spaces'" in target.read_text()


def test_integration_doctor_reports_missing_cli(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert integration_setup.main(["doctor"]) == 0
    assert "Missing optional CLIs" in capsys.readouterr().out


def test_doctor_provider_checks_matching_cli(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    monkeypatch.setattr("shutil.which", lambda name: "/bin/tool" if name == "npm" else None)
    assert integration_setup.main(["doctor", "--provider", "npm"]) == 0
    assert "Missing optional CLIs" not in capsys.readouterr().out


def test_integration_init_generates_project_env_example(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: tmp_path / "global" / ".env")
    assert integration_setup.main(["init", "--config-dir", str(tmp_path)]) == 0
    content = (tmp_path / ".env.example").read_text()
    assert "SERPER_API_KEY=" in content
    assert "STRIPE_SECRET_KEY=" in content


def test_integration_init_json_is_machine_readable(tmp_path, monkeypatch, capsys):
    import json
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: tmp_path / "global" / ".env")
    assert integration_setup.main(["init", "--config-dir", str(tmp_path), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["created"] is True
    assert result["providers"] > 10


def test_integration_init_protects_existing_template(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: tmp_path / "global" / ".env")
    target = tmp_path / ".env.example"
    target.write_text("keep me\n")
    assert integration_setup.main(["init", "--config-dir", str(tmp_path)]) == 2
    assert target.read_text() == "keep me\n"


def test_integration_init_can_update_gitignore(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: tmp_path / "global" / ".env")
    assert integration_setup.main(["init", "--config-dir", str(tmp_path), "--gitignore"]) == 0
    assert ".env" in (tmp_path / ".gitignore").read_text()


def test_key_write_restricts_env_permissions(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    target.write_text("OLD=value\n")
    target.chmod(0o644)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["setup", "stripe", "--key", "new"]) == 0
    assert target.stat().st_mode & 0o077 == 0


def test_integration_list_aliases_status(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    assert integration_setup.main(["list"]) == 0
    assert "linear" in capsys.readouterr().out


def test_integration_status_can_filter_provider(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    assert integration_setup.main(["status", "--provider", "sentry"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("sentry\t")
    assert "linear" not in output


def test_integration_remove_requires_confirmation_and_removes_key(tmp_path, monkeypatch, capsys):
    target = tmp_path / ".env"
    target.write_text("SENTRY_AUTH_TOKEN=secret\nLINEAR_API_KEY=keep\n")
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["remove", "sentry"]) == 2
    assert integration_setup.main(["remove", "sentry", "--yes"]) == 0
    assert "SENTRY_AUTH_TOKEN" not in target.read_text()
    assert "LINEAR_API_KEY=keep" in target.read_text()


def test_setup_all_prompts_only_for_missing_providers(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    for name, *_ in integration_setup.PROVIDERS.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SERPER_API_KEY", "already-set")
    answers = iter(["new-tavily", *([""] * 70)])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))
    assert integration_setup.main(["setup", "all"]) == 0
    assert "TAVILY_API_KEY=new-tavily" in target.read_text()
    assert "SERPER_API_KEY" not in target.read_text()


def test_setup_all_json_returns_structured_result(tmp_path, monkeypatch, capsys):
    import json
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    for name, *_ in integration_setup.PROVIDERS.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "")
    assert integration_setup.main(["setup", "all", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["count"] == 0


def test_provider_alias_and_connect_command(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["setup", "gh", "--key", "demo"]) == 0
    assert "GH_TOKEN=demo" in target.read_text()


def test_key_stdin_avoids_command_line_key(tmp_path, monkeypatch):
    import io
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    monkeypatch.setattr("sys.stdin", io.StringIO("stdin-secret\n"))
    assert integration_setup.main(["setup", "linear", "--key-stdin"]) == 0
    assert "LINEAR_API_KEY=stdin-secret" in target.read_text()


def test_key_file_reads_secret_without_printing_it(tmp_path, monkeypatch, capsys):
    target = tmp_path / ".env"
    secret = tmp_path / "secret"
    secret.write_text("file-secret\n")
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["setup", "linear", "--key-file", str(secret)]) == 0
    assert "file-secret" not in capsys.readouterr().out
    assert "LINEAR_API_KEY=file-secret" in target.read_text()


def test_setup_can_target_project_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: tmp_path / "global" / ".env")
    project = tmp_path / "project-config"
    assert integration_setup.main(["setup", "stripe", "--key", "demo", "--config-dir", str(project)]) == 0
    assert "STRIPE_SECRET_KEY=demo" in (project / ".env").read_text()


def test_setup_json_does_not_include_secret(tmp_path, monkeypatch, capsys):
    import json
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["setup", "stripe", "--key", "secret", "--json"]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["configured"] is True
    assert "secret" not in output


def test_setup_supports_custom_endpoint(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.search_setup.env_file", lambda: target)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["setup", "signoz", "--key", "secret", "--url", "https://signoz.local/"]) == 0
    text = target.read_text()
    assert "SIGNOZ_URL=https://signoz.local" in text


def test_local_model_endpoint_is_supported(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["setup", "ollama", "--url", "http://localhost:11434", "--key", "local"]) == 0
    assert "OLLAMA_BASE_URL=http://localhost:11434" in target.read_text()


def test_integration_status_json_is_structured(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    assert integration_setup.main(["status", "--provider", "sentry", "--json"]) == 0
    import json
    data = json.loads(capsys.readouterr().out)
    assert data[0]["provider"] == "sentry"
    assert data[0]["state"] == "missing"


def test_doctor_json_reports_configured_providers(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "configured")
    assert integration_setup.main(["doctor", "--provider", "stripe", "--json"]) == 0
    import json
    result = json.loads(capsys.readouterr().out)
    assert result["configured_providers"] == ["stripe"]


def test_doctor_json_flags_unsafe_env_permissions(tmp_path, monkeypatch, capsys):
    target = tmp_path / ".env"
    target.write_text("STRIPE_SECRET_KEY=x\n")
    target.chmod(0o644)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["doctor", "--provider", "stripe", "--json"]) == 0
    import json
    assert json.loads(capsys.readouterr().out)["unsafe_permissions"] is True


def test_doctor_fix_repairs_env_permissions(tmp_path, monkeypatch, capsys):
    target = tmp_path / ".env"
    target.write_text("TOKEN=x\n")
    target.chmod(0o644)
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: target)
    assert integration_setup.main(["doctor", "--provider", "stripe", "--fix", "--json"]) == 0
    result = __import__("json").loads(capsys.readouterr().out)
    assert result["fixed_permissions"] is True
    assert target.stat().st_mode & 0o077 == 0


def test_alias_works_for_status(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    assert integration_setup.main(["status", "--provider", "gh"]) == 0
    assert capsys.readouterr().out.startswith("github\t")


def test_model_provider_alias_works_for_status(monkeypatch, capsys):
    monkeypatch.setattr("arka.agent.integration_setup.env_file", lambda: __import__("pathlib").Path("/nonexistent"))
    assert integration_setup.main(["status", "--provider", "hf"]) == 0
    assert capsys.readouterr().out.startswith("huggingface\t")
