def test_skill_usage_records_without_arguments(tmp_path, monkeypatch) -> None:
    from arka.core import skill_usage
    monkeypatch.setattr(skill_usage, "_path", lambda: tmp_path / "usage.json")
    skill_usage.record("repo_health", 0, 12.4)
    result = skill_usage.report()
    assert result["total"] == 1
    assert result["skills"] == [("repo_health", 1)]
