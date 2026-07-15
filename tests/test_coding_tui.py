from arka.agent.coding_tui import status


def test_coding_tui_status(tmp_path):
    (tmp_path / "app.py").write_text("print('ok')")
    text = status(tmp_path)
    assert "files: 1" in text
    assert "/plan" in text
