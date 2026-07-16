from arka.agent.coding_tui import status


def test_coding_tui_route_command():
    from arka.agent.coding_tui import route_command

    assert route_command("coding-tui .") == "coding-tui ."
    assert route_command("coding-tui /tmp/repo") == "coding-tui /tmp/repo"
    assert route_command("open coding tui") == "coding-tui ."
    assert route_command("start coding workspace") == "coding-tui ."
    assert route_command("what is python") == ""


def test_coding_tui_status(tmp_path):
    (tmp_path / "app.py").write_text("print('ok')")
    text = status(tmp_path)
    assert "files: 1" in text
    assert "/plan" in text
