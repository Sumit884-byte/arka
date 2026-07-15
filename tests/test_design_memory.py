from arka.agent import design_memory


def test_design_reference_context(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    design_memory.remember("reference.png", "keep the dark card style")
    text = design_memory.context()
    assert "reference.png" in text
    assert "button order" in text
