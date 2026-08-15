"""Tests for full AI video generation routing, MCP, and backend chain."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import pytest

from arka.integrations.mcp_server import _handle_arka_ai_video
from arka.media.ai_video import (
    AI_VIDEO_SUBCOMMANDS,
    _extract_video_prompt,
    _gemini_models,
    _is_ai_video_request,
    _is_compose_video_request,
    _is_subcommand,
    _normalize_argv,
    clamp_veo_duration,
    main,
    nl_to_argv,
)
from arka.routing.symbolic import route_ai_video, route_compose_video, route_create_video


class TestAiVideoRouting:
    def test_route_full_ai_video(self) -> None:
        routed = route_ai_video("generate full ai video of sunset mountains")
        assert routed is not None
        assert routed.startswith("ai_video ")
        assert "sunset mountains" in routed

    def test_route_ai_video_explicit(self) -> None:
        routed = route_ai_video("create ai video cinematic drone shot")
        assert routed is not None
        assert "cinematic drone shot" in routed

    def test_route_generate_video_alias(self) -> None:
        routed = route_ai_video("generate video of a cat walking")
        assert routed is not None
        assert "cat walking" in routed

    def test_route_not_compose_video(self) -> None:
        assert route_ai_video("create a 5 minute video on artificial intelligence") is None
        assert route_compose_video("create a 5 minute video on artificial intelligence") is not None

    def test_route_not_create_video(self) -> None:
        assert route_ai_video("create video from images in ./photos") is None
        assert route_create_video("create video from images in ./photos") is not None

    def test_route_not_music(self) -> None:
        from arka.routing.symbolic import route_generate_music

        assert route_ai_video("generate music about summer") is None
        assert route_generate_music("generate music about summer") is not None

    def test_nl_duration_and_output(self) -> None:
        argv = nl_to_argv("generate ai video ocean waves for 8 seconds to ~/out.mp4")
        assert "-d" in argv
        assert "8" in argv
        assert "-o" in argv
        assert "~/out.mp4" in argv


class TestAiVideoDetection:
    def test_is_ai_video_request(self) -> None:
        assert _is_ai_video_request("generate full ai video of mountains")
        assert _is_ai_video_request("text to video robot dancing")
        assert not _is_ai_video_request("create video from images in ./pics")

    def test_is_compose_video_request(self) -> None:
        assert _is_compose_video_request("create a 19 minute youtube video on rust")

    def test_extract_prompt(self) -> None:
        assert _extract_video_prompt("generate ai video of sunset mountains") == "sunset mountains"

    def test_gemini_model_chain(self) -> None:
        models = _gemini_models("veo-3.1-generate-preview")
        assert models[0] == "veo-3.1-generate-preview"
        assert "veo-3.1-fast-generate-preview" in models
        assert "veo-3.1-lite-generate-preview" in models


class TestAiVideoSubcommands:
    def test_subcommand_registry(self) -> None:
        assert "styles" in AI_VIDEO_SUBCOMMANDS
        assert _is_subcommand(["styles"])

    def test_normalize_argv_strips_leading_dashes(self) -> None:
        assert _normalize_argv(["--", "styles"]) == ["styles"]
        assert _normalize_argv(["--", "--", "check"]) == ["check"]

    def test_main_styles_not_generate(self) -> None:
        from io import StringIO

        buf = StringIO()
        with patch("sys.stdout", buf):
            code = main(["--", "styles"])
        assert code == 0
        assert "Video styles:" in buf.getvalue()
        assert "Generating full AI video" not in buf.getvalue()

    def test_main_styles_direct(self) -> None:
        from io import StringIO

        buf = StringIO()
        with patch("sys.stdout", buf):
            code = main(["styles"])
        assert code == 0
        assert "documentary" in buf.getvalue()


class TestVeoDuration:
    def test_clamp_veo_duration_bounds(self) -> None:
        assert clamp_veo_duration(3) == 4
        assert clamp_veo_duration(5) == 5
        assert clamp_veo_duration(15) == 8
        assert clamp_veo_duration("7") == 7
        assert clamp_veo_duration(None) == 5

    @mock.patch("google.genai.types.GenerateVideosSource")
    @mock.patch("google.genai.types.GenerateVideosConfig")
    @mock.patch("google.genai.Client")
    def test_generate_gemini_clamps_duration(
        self,
        mock_client_cls: mock.Mock,
        mock_config_cls: mock.Mock,
        _mock_source_cls: mock.Mock,
        tmp_path: Path,
    ) -> None:
        from arka.media.ai_video import generate_gemini

        captured: dict[str, object] = {}

        def _capture_config(**kwargs):
            captured.update(kwargs)
            return mock.Mock()

        mock_config_cls.side_effect = _capture_config
        mock_client = mock.Mock()
        mock_client_cls.return_value = mock_client
        operation = mock.Mock()
        operation.done = True
        operation.error = None
        operation.result = mock.Mock(generated_videos=[])
        mock_client.models.generate_videos.return_value = operation

        out = tmp_path / "clip.mp4"
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=False):
            with pytest.raises(RuntimeError, match="no video"):
                generate_gemini("test", out, "16:9", "veo-3.1-generate-preview", 15)

        assert captured.get("duration_seconds") == 8


class TestAiVideoCli:
    def test_cli_ai_video(self) -> None:
        from arka.cli import main

        with patch("arka.media.ai_video.main", return_value=0) as ai_main:
            code = main(["ai_video", "drone shot", "-o", "/tmp/x.mp4"])
        assert code == 0
        ai_main.assert_called_once_with(["drone shot", "-o", "/tmp/x.mp4"])

    def test_cli_generate_video_alias(self) -> None:
        from arka.cli import main

        with patch("arka.media.ai_video.main", return_value=0) as ai_main:
            code = main(["generate", "video", "ocean waves"])
        assert code == 0
        ai_main.assert_called_once_with(["ocean waves"])


def test_ai_video_manifest() -> None:
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "src/arka/skills/ai_video/skill.json").read_text()
    )
    assert manifest["name"] == "ai_video"
    assert "full ai video" in manifest["triggers"]


def test_mcp_parse() -> None:
    out = json.loads(_handle_arka_ai_video({"action": "parse", "text": "full ai video of cats"}))
    assert out["command"].startswith("ai_video ")
    assert "cats" in out["command"]


def test_mcp_check() -> None:
    out = json.loads(_handle_arka_ai_video({"action": "check"}))
    assert "exit_code" in out
    assert "report" in out


@mock.patch("arka.media.ai_video.generate_pollinations")
def test_generate_pollinations_backend(mock_poll: mock.Mock, tmp_path: Path) -> None:
    from arka.media.ai_video import generate

    out = tmp_path / "clip.mp4"
    mock_poll.return_value = out
    with mock.patch.dict("os.environ", {"POLLINATIONS_API_KEY": "pk_test", "VIDEO_BACKEND": "pollinations"}):
        saved, provider = generate(
            "test prompt",
            out,
            aspect="16:9",
            model="veo-3.1-generate-preview",
            duration=5,
            audio=True,
        )
    assert saved == out
    assert provider == "pollinations"
    mock_poll.assert_called_once()


@mock.patch("arka.media.ai_video.generate_gemini_chain")
def test_generate_auto_gemini_fallback(mock_gemini: mock.Mock, tmp_path: Path) -> None:
    from arka.media.ai_video import generate

    out = tmp_path / "clip.mp4"
    mock_gemini.return_value = (out, "gemini:veo-3.1-fast-generate-preview")
    env = {"GEMINI_API_KEY": "key_test", "VIDEO_BACKEND": "auto"}
    with mock.patch.dict("os.environ", env, clear=False):
        with mock.patch("arka.media.ai_video._pollinations_key", return_value=""):
            saved, provider = generate(
                "mountains",
                out,
                aspect="16:9",
                model="veo-3.1-generate-preview",
                duration=5,
                audio=True,
            )
    assert saved == out
    assert provider.startswith("gemini")
