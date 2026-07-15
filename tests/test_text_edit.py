from arka.agent.text_edit import inspect, remove


def test_inspect_and_safe_remove(tmp_path, capsys):
    path = tmp_path / "note.txt"
    path.write_text("keep\nREMOVE\nREMOVE\n")
    assert inspect(str(path), "REMOVE") == 0
    assert "2 match" in capsys.readouterr().out
    assert remove(str(path), "REMOVE") == 2
    assert remove(str(path), "REMOVE", all_matches=True, yes=True) == 0
    assert path.read_text() == "keep\n\n\n"
    assert path.with_suffix(".txt.bak").exists()
