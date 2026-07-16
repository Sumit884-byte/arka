import json


def test_external_skill_is_normalized(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    plugin = root / "demo-plugin"
    plugin.mkdir(parents=True)
    (plugin / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setenv("SKILLS_PATH", str(root))
    monkeypatch.setattr("arka.agent.skills.REGISTRY_FILE", tmp_path / "registry.json")

    from arka.agent.skills import discover_skills

    row = next(s for s in discover_skills(refresh=True) if s["name"] == "demo_plugin")
    assert row["adapter"] == "claude-skill"
    assert row["capabilities"] == ["execute"]
    assert row["health"] == "ok"


def test_trigger_conflict_blocks_both_plugins(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    for name in ("one", "two"):
        plugin = root / name
        plugin.mkdir(parents=True)
        (plugin / "skill.json").write_text(
            json.dumps({"name": name, "entry": "run.py", "triggers": ["same action"]}),
            encoding="utf-8",
        )
        (plugin / "run.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("SKILLS_PATH", str(root))
    monkeypatch.setattr("arka.agent.skills.REGISTRY_FILE", tmp_path / "registry.json")

    from arka.agent.skills import discover_skills

    rows = discover_skills(refresh=True)
    assert all(not row["gate_ok"] for row in rows if row["name"] in {"one", "two"})
    assert all("same action" in row["conflicts"] for row in rows if row["name"] in {"one", "two"})


def test_command_plugin_rejects_shell_injection(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    plugin = root / "safe"
    plugin.mkdir(parents=True)
    (plugin / "skill.json").write_text(
        json.dumps({"name": "safe", "type": "command", "entry": "echo {args}"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SKILLS_PATH", str(root))
    monkeypatch.setattr("arka.agent.skills.REGISTRY_FILE", tmp_path / "registry.json")

    from arka.agent.skills import run_skill

    assert run_skill("safe", ["ok;", "touch", "/tmp/pwned"]) == 2
