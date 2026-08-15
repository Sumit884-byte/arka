"""NL routing for local vs cloud music generation."""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from arka.agent.local_music_gen import nl_to_argv, route_command, wants_local_music
from arka.media.music_generate import nl_to_argv as cloud_nl_to_argv
from arka.router import route
from arka.routing.symbolic import route_generate_music, route_local_music_gen


def test_wants_local_music_phrases():
    assert wants_local_music("generate music locally upbeat jazz")
    assert wants_local_music("create a song offline lo-fi")
    assert wants_local_music("compose track with ffmpeg calm ambient")
    assert not wants_local_music("generate music upbeat jazz")
    assert not wants_local_music("play local music")
    assert not wants_local_music("play a random song from local music")


def test_local_nl_to_argv_extracts_prompt():
    assert nl_to_argv("generate music locally upbeat lo-fi hip hop") == [
        "generate",
        "upbeat lo-fi hip hop",
    ]
    assert nl_to_argv("create song offline jazz piano --instrumental") == [
        "generate",
        "--instrumental",
        "jazz piano",
    ]


def test_cloud_nl_defers_to_local():
    assert cloud_nl_to_argv("generate music locally calm ambient") == []
    assert route_generate_music("generate music locally calm ambient") is None


def test_route_local_music_gen_symbolic():
    result = route_local_music_gen("generate music locally jazz piano")
    assert result == "music local generate 'jazz piano'"


def test_route_symbolic_prefers_local_over_cloud():
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        result = route("generate music locally neon synthwave")
    assert result is not None
    assert result.skill == "music local generate 'neon synthwave'"


def test_local_music_parse_subcommand(capsys):
    from arka.agent.local_music_gen import main

    assert main(["parse", "generate music locally calm ambient"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("generate ")
    assert "calm ambient" in out


def test_mcp_local_music_parse():
    from arka.integrations.mcp_server import _handle_arka_local_music

    payload = json.loads(
        _handle_arka_local_music(
            {"action": "parse", "text": "generate music locally upbeat jazz --instrumental"}
        )
    )
    assert payload["command"] == "music local generate --instrumental 'upbeat jazz'"


def test_mcp_local_music_generate_mocked(tmp_path: Path):
    from arka.integrations.mcp_server import _handle_arka_local_music

    out = tmp_path / "song.mp3"
    with mock.patch(
        "arka.agent.local_music_gen.local_music_result",
        return_value={"output": str(out), "backend": "synthesize", "prompt": "jazz", "duration": 12},
    ):
        payload = json.loads(
            _handle_arka_local_music({"action": "generate", "prompt": "jazz", "duration": 12})
        )
    assert payload["backend"] == "synthesize"
    assert payload["output"] == str(out)


def test_run_nl_stdout_format(capsys, tmp_path):
    from arka.cli import _try_local_music_nl

    out = tmp_path / "local.mp3"
    with mock.patch(
        "arka.agent.local_music_gen.local_music_result",
        return_value={"output": str(out), "backend": "synthesize", "prompt": "ambient", "duration": 10},
    ):
        code = _try_local_music_nl("generate music locally calm ambient")
    assert code == 0
    assert f"Generated local music: {out}" in capsys.readouterr().out
