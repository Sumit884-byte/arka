"""Router tests for show-me listing queries (must not route to describe_image)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.router import route
from arka.routing.symbolic import route_describe_image
from arka.vision.describe import nl_to_argv


class DescribeImageParseTests(unittest.TestCase):
    def test_kaggle_competitions_not_parsed_as_image(self) -> None:
        for query in (
            "show me competitions available on kaggle",
            "show me competetions available on kaggle",
            "show me jobs on linkedin",
        ):
            with self.subTest(query=query):
                self.assertEqual(nl_to_argv(query), [])
                self.assertIsNone(route_describe_image(query))

    def test_show_me_with_image_path_still_parses(self) -> None:
        argv = nl_to_argv("show me photo.jpg")
        self.assertEqual(argv[0], "describe")
        self.assertEqual(argv[1], "photo.jpg")

    def test_describe_with_bare_noun_not_parsed(self) -> None:
        self.assertEqual(nl_to_argv("describe competitions on kaggle"), [])


class RouterShowMeTests(unittest.TestCase):
    def test_routes_kaggle_competitions_to_competitions(self) -> None:
        for query in (
            "show me competitions available on kaggle",
            "show me competetions available on kaggle",
        ):
            with self.subTest(query=query):
                with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
                    result = route(query)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.skill.split()[0], "competitions")
                self.assertIn("kaggle", result.skill.lower())

    def test_does_not_route_kaggle_competitions_to_describe_image(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("show me competitions available on kaggle")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertNotEqual(result.skill.split()[0], "describe_image")


if __name__ == "__main__":
    unittest.main()
