"""Tests for AI music generation routing and helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from arka.generate.music import _compose_input, nl_to_argv
from arka.routing.symbolic import route_generate_music


class GenerateMusicRoutingTests(unittest.TestCase):
    def test_route_instrumental(self) -> None:
        routed = route_generate_music("generate music upbeat jazz --instrumental")
        assert routed is not None
        assert routed.startswith("generate_music ")
        assert "--instrumental" in routed
        assert "upbeat jazz" in routed

    def test_route_with_lyrics(self) -> None:
        routed = route_generate_music('compose a song indie folk with lyrics "hello world"')
        assert routed is not None
        assert "--lyrics" in routed

    def test_route_not_video(self) -> None:
        assert route_generate_music("generate video of a cat") is None

    def test_route_trailing_track_noun(self) -> None:
        routed = route_generate_music("create a summer pop track")
        assert routed is not None
        assert "summer pop" in routed

    def test_route_duration_flag(self) -> None:
        routed = route_generate_music("generate music jazz piano --instrumental for 45 seconds")
        assert routed is not None
        assert "-d" in routed
        assert "45" in routed

    def test_compose_input(self) -> None:
        assert "Lyrics:" in _compose_input("indie folk", "line one", instrumental=False)
        assert _compose_input("ambient", "", instrumental=True) == "ambient"


class GenerateMusicCliTests(unittest.TestCase):
    def test_cli_generate_music_subcommand(self) -> None:
        from arka.cli import main

        with patch("arka.generate.music.main", return_value=0) as music_main:
            code = main(["generate", "music", "lo-fi", "--instrumental"])
        assert code == 0
        music_main.assert_called_once_with(["lo-fi", "--instrumental"])

    def test_cli_help(self) -> None:
        from arka.cli import main

        code = main(["generate", "music", "--help"])
        assert code == 0


if __name__ == "__main__":
    unittest.main()
