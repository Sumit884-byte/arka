"""Tests for describe_video skill — NL parse, frame sampling, routing."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.router import route
from arka.routing.symbolic import route_describe_video
from arka.vision.video import (
    DEFAULT_FRAME_COUNT,
    extract_frame,
    is_video_people_request,
    nl_to_argv,
    sample_timestamps,
)


class VideoParseTests(unittest.TestCase):
    def test_parses_common_phrases_with_path(self) -> None:
        cases = {
            "who is in meeting.mp4": ["describe", "meeting.mp4"],
            "which people are in clip.mp4 and where they are": ["describe", "clip.mp4"],
            "who appears in ~/Videos/party.mov": ["describe", "~/Videos/party.mov"],
            "find the people in interview.webm": ["describe", "interview.webm"],
            "where are the people in demo.mkv": ["describe", "demo.mkv"],
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertTrue(is_video_people_request(query))
                self.assertEqual(nl_to_argv(query), expected)

    def test_phrase_without_path_matches_intent_but_no_argv(self) -> None:
        query = "which people are in the video and where they are"
        self.assertTrue(is_video_people_request(query))
        self.assertEqual(nl_to_argv(query), [])

    def test_rejects_unrelated_queries(self) -> None:
        for query in (
            "summarize lecture.mp4",
            "who is the villain in movie.mp4",
            "transcribe meeting.mp4",
            "compose video about cats",
            "describe photo.jpg",
            "what is on my screen",
        ):
            with self.subTest(query=query):
                self.assertFalse(is_video_people_request(query))
                self.assertEqual(nl_to_argv(query), [])

    def test_route_describe_video(self) -> None:
        hit = route_describe_video("who is in party.mp4")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "describe_video")
        self.assertIn("party.mp4", hit)

    def test_router_symbolic_only(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("who is in meeting.mp4")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "describe_video")


class FrameSamplingTests(unittest.TestCase):
    def test_sample_timestamps_even_spacing(self) -> None:
        stamps = sample_timestamps(100.0, 4)
        self.assertEqual(len(stamps), 4)
        self.assertAlmostEqual(stamps[0], 20.0)
        self.assertAlmostEqual(stamps[-1], 80.0)

    def test_single_frame_uses_midpoint(self) -> None:
        self.assertEqual(sample_timestamps(60.0, 1), [30.0])

    def test_default_frame_count(self) -> None:
        self.assertEqual(DEFAULT_FRAME_COUNT, 5)

    def test_extract_frame_calls_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clip.mp4"
            video.write_bytes(b"fake")
            out = Path(tmp) / "frame.jpg"
            out.write_bytes(b"jpg")

            with (
                mock.patch("arka.vision.video._which", return_value="/usr/bin/ffmpeg"),
                mock.patch("arka.vision.video.subprocess.run") as run,
            ):
                run.return_value = mock.Mock(returncode=0)
                ok = extract_frame(video, 12.5, out)
            self.assertTrue(ok)
            args = run.call_args[0][0]
            self.assertIn("/usr/bin/ffmpeg", args)
            self.assertIn("12.500", args)
            self.assertIn(str(video), args)
            self.assertIn(str(out), args)


class DescribeVideoIntegrationTests(unittest.TestCase):
    def test_describe_video_aggregates_frame_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "test.mp4"
            video.write_bytes(b"fake")

            def fake_extract(_video, _t, out_path: Path) -> bool:
                out_path.write_bytes(b"jpg")
                return True

            with (
                mock.patch("arka.vision.video._resolve_source", return_value=video),
                mock.patch("arka.vision.video._probe_duration", return_value=30.0),
                mock.patch("arka.vision.video.extract_frame", side_effect=fake_extract),
                mock.patch("arka.vision.video.cache_dir", return_value=Path(tmp)),
                mock.patch(
                    "arka.vision.describe.describe_source",
                    side_effect=lambda _src, _prompt: "Person A at center (50%, 50%)",
                ),
            ):
                from arka.vision.video import describe_video

                out = describe_video(str(video), frame_count=2)

            self.assertIn("test.mp4", out)
            self.assertIn("Person A at center", out)
            self.assertIn("### t=", out)


if __name__ == "__main__":
    unittest.main()
