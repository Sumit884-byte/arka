"""Tests for open_url skill: parsing, routing, and browser open."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.integrations.open_url import (
    build_url,
    is_browser_app_name,
    is_play_youtube_intent,
    launch_application,
    nl_to_argv,
    open_in_browser,
    parse_open,
    parse_open_app,
    route_command,
    wants_open_url,
    _looks_like_macos_open,
    _fallback_open_urls,
)
from arka.router import route
from arka.routing.symbolic import route_offline_extras, route_open_url


class OpenUrlBuildTests(unittest.TestCase):
    def test_site_aliases(self) -> None:
        self.assertEqual(build_url("youtube"), "https://youtube.com")
        self.assertEqual(build_url("YouTube"), "https://youtube.com")
        self.assertEqual(build_url("google"), "https://google.com")
        self.assertEqual(build_url("github"), "https://github.com")

    def test_browser_app_names_are_not_urls(self) -> None:
        self.assertTrue(is_browser_app_name("brave"))
        self.assertIsNone(build_url("brave"))
        self.assertFalse(is_browser_app_name("brave.com"))
        self.assertEqual(build_url("brave.com"), "https://brave.com")

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

    def test_open_browser_app_names(self) -> None:
        self.assertIsNone(parse_open("open brave"))
        self.assertEqual(parse_open_app("open brave"), "brave")
        self.assertEqual(parse_open_app("brave"), "brave")
        self.assertEqual(nl_to_argv("open brave"), ["brave"])

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
        brave_hit = route_command("open brave")
        self.assertEqual(brave_hit, "open_url brave")

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

    def test_play_website_game_open_is_not_open_url(self) -> None:
        phrase = "play_website_game open https://shadowfight2.com/play/"
        self.assertFalse(wants_open_url(phrase))
        self.assertEqual(route_command(phrase), "")
        self.assertIsNone(route_open_url(phrase))

    def test_macos_open_is_not_browser_open(self) -> None:
        self.assertTrue(_looks_like_macos_open(["-a", "Cursor", "."]))
        self.assertTrue(_looks_like_macos_open(["."]))
        self.assertTrue(_looks_like_macos_open(["./README.md"]))
        self.assertFalse(_looks_like_macos_open(["youtube"]))
        self.assertFalse(_looks_like_macos_open(["github.com"]))
        self.assertFalse(wants_open_url("open -a Cursor ."))
        self.assertEqual(route_command("open -a Cursor ."), "")
        self.assertEqual(_fallback_open_urls(["-a", "Cursor", "."]), [])

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

    def test_launch_application_mock(self) -> None:
        with mock.patch("arka.integrations.open_url.subprocess.run", return_value=mock.Mock(returncode=0)) as runner:
            self.assertTrue(launch_application("brave"))
            runner.assert_called_once_with(["open", "-a", "Brave Browser"], check=False, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
