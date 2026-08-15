"""Tests for adaptive infographic compositor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from arka.agent.infographic import (
    INFOGRAPHIC_CLI_HEADS,
    choose_layout,
    compose,
    is_infographic_cli_argv,
    main,
    nl_to_argv,
)
from arka.routing.symbolic import route_infographic


class TestChooseLayout:
    @pytest.mark.parametrize(
        ("count", "expected"),
        [
            (1, "row2"),
            (2, "row2"),
            (3, "row3"),
            (4, "grid4"),
            (5, "grid6"),
            (6, "grid6"),
            (7, "grid9"),
            (9, "grid9"),
            (10, "radial"),
        ],
    )
    def test_auto_layout(self, count: int, expected: str) -> None:
        assert choose_layout(count) == expected

    def test_explicit_layout(self) -> None:
        assert choose_layout(4, "radial") == "radial"


class TestInfographicRouting:
    def test_route_infographic_nl(self) -> None:
        hit = route_infographic(
            'infographic about "Types of Headaches" with items: tension, migraine, cluster, sinus'
        )
        assert hit is not None
        assert hit.startswith("infographic create ")
        assert "Headaches" in hit

    def test_nl_to_argv_title_and_items(self) -> None:
        argv = nl_to_argv(
            'infographic about "GitHub repos" items: frontend, backend, infra, docs, mobile, cli'
        )
        assert "--title" in argv
        assert argv.count("--item") >= 4

    def test_nl_no_match(self) -> None:
        assert nl_to_argv("make a drake meme") == []


class TestInfographicCli:
    def test_cli_heads(self) -> None:
        assert "infographic" in INFOGRAPHIC_CLI_HEADS
        assert is_infographic_cli_argv(["infographic", "styles"])
        assert not is_infographic_cli_argv(["meme", "styles"])

    def test_main_styles_not_create(self, capsys) -> None:
        code = main(["styles"])
        assert code == 0
        out = capsys.readouterr().out
        assert "clean" in out
        assert "doodle" in out

    def test_main_layouts(self, capsys) -> None:
        code = main(["layouts"])
        assert code == 0
        assert "grid4" in capsys.readouterr().out

    def test_main_create_without_subcommand(self, tmp_path: Path, capsys) -> None:
        out = tmp_path / "headaches.png"
        code = main(
            [
                "--title",
                "Types of Headaches",
                "--item",
                "Tension",
                "--item",
                "Migraine",
                "--item",
                "Cluster",
                "--item",
                "Sinus",
                "-o",
                str(out),
            ]
        )
        assert code == 0
        assert out.is_file()
        assert "grid4" in capsys.readouterr().out

    def test_main_json(self, tmp_path: Path, capsys) -> None:
        out = tmp_path / "radial.png"
        items = [f"Repo {i}" for i in range(10)]
        argv = ["create", "--title", "GitHub Repos", "--json", "-o", str(out)]
        for item in items:
            argv.extend(["--item", item])
        code = main(argv)
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["layout"] == "radial"
        assert payload["items"] == 10
        assert out.is_file()


class TestCompose:
    def test_compose_grid4(self, tmp_path: Path) -> None:
        target = tmp_path / "grid.png"
        result = compose(
            "Demo Title",
            ["One", "Two", "Three", "Four"],
            output=target,
        )
        assert result["layout"] == "grid4"
        assert target.is_file()

    def test_compose_requires_items(self) -> None:
        with pytest.raises(ValueError, match="at least one item"):
            compose("Title", [])

    @patch.dict("os.environ", {"IMAGE_OUTPUT_DIR": ""}, clear=False)
    def test_default_output_dir(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("IMAGE_OUTPUT_DIR", str(tmp_path))
        result = compose("Output Test", ["Alpha"], output=None)
        path = Path(str(result["output"]))
        assert path.parent == tmp_path
        assert path.is_file()
