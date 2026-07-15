from pathlib import Path

from arka.agent.move_file import move
from arka.routing.symbolic import route_offline_extras


def test_move_previews_and_applies(tmp_path: Path):
    source = tmp_path / "old.py"
    source.write_text("x = 1")
    preview = move(str(source), str(tmp_path / "new.py"))
    assert preview["applied"] is False
    result = move(str(source), str(tmp_path / "new.py"), yes=True)
    assert result["applied"] is True
    assert (tmp_path / "new.py").is_file()


def test_move_nl_route():
    result = route_offline_extras("move file src/old.py to src/new.py and update imports")
    assert result == "move_file src/old.py src/new.py --update-refs"
