"""Tests for open_url skill: parsing, routing, and browser open."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.integrations.open_url import (
    build_url,
    is_play_youtube_intent,
    nl_to_argv,
    open_in_browser,
    parse_open,
    route_command,
    wants_open_url,
)
from arka.router import route
from arka.routing.symbolic import route_offline_extras, route_open_url


class OpenUrlBuildTests(unittest.TestCase):
    def test_site_aliases(self) -> None:
        self.assertEqual(build_url("youtube"), "https://youtube.com")
        self.assertEqual(build_url("YouTube"), "https://youtube.com")
        self.assertEqual(build_url("google"), "https://google.com")
        self.assertEqual(build_url("github"), "https://github.com")

    def test_domain_and_full_url(self) -> None:
        self.assertEqual(build_url("github.com"), "https://github.com")
        self.assertEqual(
            build_url("https://news.ycombinator.com"),
            "https://news.ycombinator.com",
        )
        self.assertEqual(build_url("https://example.com/docs?a=1"), "https://example.com/docs?a=1")
        self.assertEqual(build_url("www.example.com/path"), "https://www.example.com/path")


class OpenUrlParseTests(unittest.TestCase):
    def test_open_site_names(self) -> None:
        self.assertEqual(parse_open("open youtube"), "https://youtube.com")
        self.assertEqual(parse_open("open YouTube"), "https://youtube.com")
        self.assertEqual(parse_open("open github.com"), "https://github.com")
        self.assertEqual(
            parse_open("open https://news.ycombinator.com"),
            "https://news.ycombinator.com",
        )

    def test_open_in_browser_phrasing(self) -> None:
        self.assertEqual(parse_open("open google in browser"), "https://google.com")
        self.assertEqual(parse_open("open google in the default browser"), "https://google.com")

    def test_browse_alias(self) -> None:
        self.assertEqual(parse_open("browse github"), "https://github.com")

    def test_play_youtube_not_open(self) -> None:
        self.assertIsNone(parse_open("play lofi on youtube"))
        self.assertIsNone(parse_open("play chilledcow lofi on youtube"))
        self.assertTrue(is_play_youtube_intent("play lofi on youtube"))
        self.assertFalse(is_play_youtube_intent("open youtube"))

    def test_reserved_open_targets(self) -> None:
        self.assertIsNone(parse_open("open project myapp"))
        self.assertIsNone(parse_open("open news"))
        self.assertIsNone(parse_open("open finance"))
        self.assertIsNone(parse_open("help"))
        self.assertIsNone(parse_open("open help"))
        self.assertIsNone(parse_open("hi"))
        self.assertIsNone(parse_open("hello"))
        self.assertIsNone(parse_open("good morning"))
        self.assertIsNone(parse_open("thanks"))

    def test_open_full_url(self) -> None:
        self.assertTrue(wants_open_url("open https://news.ycombinator.com"))
        hit = route_command("open https://news.ycombinator.com")
        self.assertIn("news.ycombinator.com", hit)
        self.assertIn("https://news.ycombinator.com", hit)

    def test_nl_to_argv(self) -> None:
        self.assertEqual(nl_to_argv("open youtube"), ["https://youtube.com"])
        self.assertEqual(nl_to_argv("play lofi on youtube"), [])


class OpenUrlRoutingTests(unittest.TestCase):
    def test_wants_open_url(self) -> None:
        self.assertTrue(wants_open_url("open youtube"))
        self.assertTrue(wants_open_url("open google in browser"))
        self.assertFalse(wants_open_url("hi"))
        self.assertFalse(wants_open_url("hello"))
        self.assertFalse(wants_open_url("play lofi on youtube"))

    def test_route_command(self) -> None:
        hit = route_command("open youtube")
        self.assertTrue(hit.startswith("open_url "))
        self.assertIn("youtube.com", hit)

    def test_symbolic_route(self) -> None:
        hit = route_open_url("open YouTube")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("open_url "))
        self.assertIn("youtube.com", hit)

    def test_route_keeps_user_url_path(self) -> None:
        hit = route_open_url("open https://example.com/docs?a=1")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("https://example.com/docs?a=1", hit)

    def test_symbolic_beats_play_youtube(self) -> None:
        phrase = "open YouTube"
        hit = route_offline_extras(phrase)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("open_url "))
        self.assertNotIn("play_youtube", hit)

    def test_play_still_not_open(self) -> None:
        self.assertIsNone(route_open_url("play lofi on youtube"))

    def test_greetings_are_not_open_url(self) -> None:
        self.assertIsNone(route_open_url("hi"))
        self.assertIsNone(route_open_url("hello"))
        self.assertFalse((route_offline_extras("hi") or "").startswith("open_url "))

    def test_router_symbolic_only(self) -> None:
        phrase = "open github.com"
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route(phrase)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.skill.startswith("open_url "))


class OpenUrlBrowserTests(unittest.TestCase):
    def test_open_in_browser_mock(self) -> None:
        with mock.patch("arka.integrations.open_url.webbrowser.open", return_value=True) as opener:
            self.assertTrue(open_in_browser("youtube"))
            opener.assert_called_once_with("https://youtube.com", new=2)


if __name__ == "__main__":
    unittest.main()
