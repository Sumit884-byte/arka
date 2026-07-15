"""Tests for frontend visual review and retry loop."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from arka.agent.frontend_loop import (
    ReviewResult,
    nl_to_argv,
    parse_request,
    review_frontend,
    run_frontend_loop,
    route_command,
)


def test_parse_request_extracts_loops_and_source() -> None:
    source, loops, prompt, retry = parse_request("review this frontend screenshot.png for 3 loops")
    assert source == "screenshot.png"
    assert loops == 3
    assert retry is None
    assert prompt


def test_nl_to_argv_routes_frontend_loop() -> None:
    argv = nl_to_argv("review this frontend and retry 2 loops")
    assert argv[0] == "review"
    assert "--loops" in argv
    assert "2" in argv


def test_route_command_prefers_frontend_loop() -> None:
    assert route_command("review this frontend and retry 2 loops").startswith("frontend_loop ")


def test_review_frontend_parses_json_verdict() -> None:
    payload = '{"verdict":"retry","score":4,"reasons":["crowded"],"fixes":["increase spacing"],"summary":"tighten hierarchy"}'
    with mock.patch("arka.agent.frontend_loop.describe_source", return_value=payload):
        result = review_frontend("preview.html")
    assert result.verdict == "retry"
    assert result.score == 4
    assert result.reasons == ["crowded"]
    assert result.fixes == ["increase spacing"]


def test_run_frontend_loop_retries_until_good() -> None:
    responses = iter(
        [
            ReviewResult("retry", 3, ["too dense"], ["reduce clutter"], "needs work", "raw1"),
            ReviewResult("good", 8, ["clean"], [], "ready to ship", "raw2"),
        ]
    )

    with mock.patch("arka.agent.frontend_loop.review_frontend", side_effect=lambda *_a, **_k: next(responses)):
        with mock.patch("arka.agent.frontend_loop._run_retry") as retry_cmd:
            result = run_frontend_loop(
                "preview.html",
                loops=2,
                retry="npm run build",
                cwd=Path("."),
            )
    assert result.verdict == "good"
    retry_cmd.assert_called_once()


def test_run_frontend_loop_stops_without_retry_command() -> None:
    with mock.patch(
        "arka.agent.frontend_loop.review_frontend",
        return_value=ReviewResult("retry", 3, ["too dense"], ["fix spacing"], "needs work", "raw"),
    ):
        result = run_frontend_loop("preview.html", loops=2)
    assert result.verdict == "retry"
