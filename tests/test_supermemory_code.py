from arka.integrations import supermemory as sm


def test_remember_code_chunks(tmp_path, monkeypatch):
    path = tmp_path / "app.py"
    path.write_text("\n".join(f"line_{i}" for i in range(45)))
    saved = []
    monkeypatch.setattr(sm, "remember", lambda text, **kwargs: saved.append((text, kwargs)) or {"backend": "local"})
    result = sm.remember_code(str(path), chunk_lines=20)
    assert result["chunks"] == 3
    assert all("code" in kwargs["tags"] for _, kwargs in saved)
