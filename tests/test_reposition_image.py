"""Tests for smart image reframing / reposition_image skill."""

from __future__ import annotations

import json
from pathlib import Path


from arka.agent.reposition_image import (
    analyze_framing,
    css_for_image,
    detect_subject,
    fix_image,
    main,
    nl_to_argv,
    reposition_image_result,
)
from arka.routing.symbolic import route_reposition_image


def _portrait_with_high_face(tmp_path: Path, *, name: str = "avatar.jpg") -> Path:
    from PIL import Image, ImageDraw

    path = tmp_path / name
    img = Image.new("RGB", (400, 500), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    # Face placed high in frame — mimics Steve Jobs avatar crop issue.
    draw.ellipse((150, 20, 250, 140), fill=(210, 170, 140))
    draw.rectangle((170, 80, 230, 110), fill=(180, 120, 100))
    img.save(path, quality=95)
    return path


class TestRepositionImageDetection:
    def test_detect_subject_mass(self, tmp_path: Path) -> None:
        path = _portrait_with_high_face(tmp_path)
        from PIL import Image

        subject = detect_subject(Image.open(path))
        assert subject.source == "mass"
        assert subject.y < 0.25

    def test_analyze_framing_flags_top_cutoff(self, tmp_path: Path) -> None:
        path = _portrait_with_high_face(tmp_path)
        analysis = analyze_framing(path, shape="circle")
        assert analysis.head_cutoff_top is True
        assert analysis.severity == "bad"
        assert "Top of head likely clipped" in analysis.issues[0]
        assert analysis.object_position_y_pct < 45

    def test_css_for_circle_avatar(self, tmp_path: Path) -> None:
        path = _portrait_with_high_face(tmp_path)
        payload = css_for_image(path, shape="circle", selector=".profile-card img")
        assert "object-fit: cover;" in payload["css"]
        assert "object-position:" in payload["css"]
        assert "border-radius: 50%;" in payload["css"]
        assert ".profile-card img" in payload["css"]


class TestRepositionImageFix:
    def test_fix_image_writes_output(self, tmp_path: Path) -> None:
        src = _portrait_with_high_face(tmp_path, name="steve.jpg")
        out = tmp_path / "steve-fixed.jpg"
        payload = fix_image(src, out, shape="circle", size=256)
        assert out.is_file()
        assert payload["before_severity"] == "bad"
        assert payload["output"] == str(out.resolve())

    def test_batch_fix_processes_folder(self, tmp_path: Path) -> None:
        _portrait_with_high_face(tmp_path, name="a.jpg")
        _portrait_with_high_face(tmp_path, name="b.jpg")
        from arka.agent.reposition_image import batch_fix

        results = batch_fix(tmp_path, output_dir=tmp_path / "out", shape="circle", size=128)
        assert len(results) == 2
        assert (tmp_path / "out" / "a.jpg").is_file()


class TestRepositionImageRouting:
    def test_nl_to_argv_fix_avatar(self) -> None:
        argv = nl_to_argv("fix profile picture cropping on photo.jpg")
        assert argv[0] == "fix"
        assert argv[1] == "photo.jpg"

    def test_nl_to_argv_css_circle(self) -> None:
        argv = nl_to_argv("reposition avatar in avatar.png for circular profile")
        assert argv[0] in {"check", "css"}
        assert "--shape" in argv
        assert "circle" in argv

    def test_route_reposition_image(self) -> None:
        hit = route_reposition_image("center face in image headshot.png")
        assert hit is not None
        assert hit.startswith("reposition_image ")


class TestRepositionImageCli:
    def test_main_check_json(self, tmp_path: Path, capsys) -> None:
        path = _portrait_with_high_face(tmp_path)
        code = main(["check", str(path), "--shape", "circle", "--json"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["severity"] == "bad"

    def test_main_css(self, tmp_path: Path, capsys) -> None:
        path = _portrait_with_high_face(tmp_path)
        code = main(["css", str(path), "--shape", "circle"])
        assert code == 0
        assert "object-position:" in capsys.readouterr().out

    def test_main_fix(self, tmp_path: Path) -> None:
        src = _portrait_with_high_face(tmp_path)
        out = tmp_path / "fixed.jpg"
        code = main(["fix", str(src), "-o", str(out), "--shape", "circle", "--json"])
        assert code == 0
        assert out.is_file()


class TestRepositionImageMcp:
    def test_reposition_image_result_check(self, tmp_path: Path) -> None:
        path = _portrait_with_high_face(tmp_path)
        payload = reposition_image_result("check", path, shape="circle")
        assert payload["head_cutoff_top"] is True

    def test_handle_arka_reposition_image(self, tmp_path: Path) -> None:
        from arka.integrations.mcp_server import _handle_arka_reposition_image

        path = _portrait_with_high_face(tmp_path)
        raw = _handle_arka_reposition_image({"action": "css", "path": str(path), "shape": "circle"})
        payload = json.loads(raw)
        assert "css" in payload
        assert "object-position" in payload["css"]


def test_mcp_tool_registered() -> None:
    from arka.integrations.mcp_server import list_tool_names

    assert "arka_reposition_image" in list_tool_names()
