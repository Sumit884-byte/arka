from unittest.mock import patch
import sys
import types

def test_background_remove_route() -> None:
    from arka.routing.symbolic import route_background_remove
    assert route_background_remove("remove background from photo.png") == "background_remove photo.png"

def test_background_remove_writes_png(tmp_path) -> None:
    from arka.agent.background_remove import remove_background
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"input")
    with patch.dict(sys.modules, {"rembg": types.SimpleNamespace(remove=lambda _: b"png")}):
        assert remove_background(str(source)).read_bytes() == b"png"
