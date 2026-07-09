"""Router tests for github_repo NL routing."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.router import route


class RouterGithubRepoTests(unittest.TestCase):
    def test_routes_github_url_offline(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route(
                "which files changed in 2 days for https://github.com/Sumit884-byte/arka"
            )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill, "github_repo activity Sumit884-byte/arka --days 2")
        self.assertIn(result.source, ("offline", "fish"))

    def test_routes_local_repo_name_offline(self) -> None:
        with (
            mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False),
            mock.patch(
                "arka.agent.github_repo._find_clone_by_name",
                return_value=__import__("pathlib").Path("/tmp/arka"),
            ),
            mock.patch(
                "arka.agent.github_repo._owner_repo_from_root",
                return_value=("Sumit884-byte", "arka"),
            ),
        ):
            result = route(
                "tell which files where changed in 2 days for this repo:arka"
            )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill, "github_repo activity Sumit884-byte/arka --days 2")
        self.assertNotEqual(result.skill.split()[0], "web_answer")


if __name__ == "__main__":
    unittest.main()
