"""Tests for Google Flow skill — routing, NL parsing, MCP, and backends."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from arka.integrations.mcp_server import _handle_arka_google_flow
from arka.media.google_flow import (
    _extract_prompt,
    _is_google_flow_request,
    nl_to_argv,
    open_flow,
)
from arka.routing.symbolic import route_flow, route_google_flow, route_offline_extras


class TestGoogleFlowRouting:
    def test_route_create_video_in_google_flow(self) -> None:
        routed = route_google_flow("create video in google flow of a cat walking in the rain")
        assert routed is not None
        assert routed.startswith("google_flow ")
        assert "cat walking in the rain" in routed

    def test_route_use_google_flow_to_make_movie(self) -> None:
        routed = route_google_flow("use google flow to make a movie about space exploration")
        assert routed is not None

    def test_offline_extras_beats_stock_prediction(self) -> None:
        routed = route_offline_extras("create video in google flow of sunset over mountains")
        assert routed is not None
        assert routed.startswith("google_flow ")
        assert "sunset over mountains" in routed

    def test_route_open_google_flow(self) -> None:
        routed = route_google_flow("open google flow")
        assert routed == "google_flow open"

    def test_route_not_plain_flow_howto(self) -> None:
        assert route_google_flow("flow how to install docker on mac") is None
        assert route_flow("flow how to install docker on mac") is not None

    def test_route_flow_skips_google_flow_requests(self) -> None:
        assert route_flow("create video in google flow of sunset") is None
        assert route_google_flow("create video in google flow of sunset") is not None

    def test_route_not_stock_prediction(self) -> None:
        routed = route_google_flow("google flow video cinematic forest fog")
        assert routed is not None
        assert routed.startswith("google_flow ")
        assert "forest fog" in routed


class TestGoogleFlowNl:
    def test_is_google_flow_request(self) -> None:
        assert _is_google_flow_request("create video in google flow of waves")
        assert not _is_google_flow_request("generate video of a cat")
        assert not _is_google_flow_request("flow how to bake bread")

    def test_extract_prompt(self) -> None:
        assert _extract_prompt("create video in google flow of ocean waves at dawn") == "ocean waves at dawn"

    def test_nl_to_argv_duration_and_aspect(self) -> None:
        argv = nl_to_argv("google flow video sunset city --aspect 9:16 for 8 seconds")
        assert "-a" in argv
        assert "9:16" in argv
        assert "-d" in argv
        assert "8" in argv
        prompt = argv[-1]
        assert "sunset city" in prompt


def test_google_flow_manifest() -> None:
    manifest = json.loads(
        (Path(__file__).parents[1] / "src/arka/skills/google_flow/skill.json").read_text()
    )
    assert manifest["name"] == "google_flow"
    assert "google flow" in manifest["triggers"]


def test_open_flow_returns_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_FLOW_URL", "https://labs.google/fx/tools/flow")
    payload = open_flow(prompt="test prompt")
    assert payload["flow_url"] == "https://labs.google/fx/tools/flow"
    assert payload["prompt"] == "test prompt"


def test_mcp_parse() -> None:
    payload = json.loads(
        _handle_arka_google_flow({"action": "parse", "text": "use google flow to make a movie about mars"})
    )
    assert payload["command"].startswith("google_flow ")
    assert "mars" in " ".join(payload["argv"])


def test_mcp_open() -> None:
    payload = json.loads(_handle_arka_google_flow({"action": "open"}))
    assert "flow_url" in payload


def test_mcp_generate_mocked(tmp_path: Path) -> None:
    out = tmp_path / "clip.mp4"
    out.write_bytes(b"ftyp")
    with mock.patch(
        "arka.media.google_flow.google_flow_result",
        return_value={"prompt": "drone", "output": str(out), "provider": "gemini"},
    ):
        payload = json.loads(_handle_arka_google_flow({"action": "generate", "prompt": "drone"}))
    assert payload["provider"] == "gemini"
    assert payload["output"] == str(out)


def test_cli_google_flow_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from arka.cli import main

    monkeypatch.setenv("GOOGLE_FLOW_BACKEND", "open")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("arka.fish_bridge.delegate_to_fish", lambda *_a, **_k: None)

    with mock.patch("arka.media.google_flow.main", return_value=0) as flow_main:
        code = main(["google_flow", "sunset", "-d", "8"])
    assert code == 0
    flow_main.assert_called_once_with(["sunset", "-d", "8"])


def test_generate_gemini_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from arka.media.google_flow import generate

    out = tmp_path / "veo.mp4"
    out.write_bytes(b"ftyp")
    monkeypatch.setenv("GOOGLE_FLOW_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with mock.patch("arka.media.google_flow.generate_gemini", return_value=out):
        saved, provider = generate("mountains", out, backend="gemini")
    assert saved == out
    assert provider == "gemini"
