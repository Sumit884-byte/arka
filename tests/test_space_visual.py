from arka.agent.space_visual import create


def test_space_visual_is_regenerable(tmp_path):
    output = create(str(tmp_path / "space.svg"))
    assert output.endswith("space.svg")
    assert "SPACE TECHNOLOGY" in (tmp_path / "space.svg").read_text()
