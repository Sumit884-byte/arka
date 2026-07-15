from arka.llm import thinking


def test_thinking_level_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(thinking, "path", lambda: tmp_path / "thinking_level")
    assert thinking.set_level("high") == "high"
    assert thinking.get() == "high"
    assert "thorough" in thinking.instruction()
