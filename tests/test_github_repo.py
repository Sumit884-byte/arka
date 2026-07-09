"""Tests for GitHub repo activity skill."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import github_repo as gr


class GithubRepoParseTests(unittest.TestCase):
    def test_parse_github_repo(self) -> None:
        parsed = gr.parse_github_repo("files changed https://github.com/Sumit884-byte/arka")
        self.assertEqual(parsed, ("Sumit884-byte", "arka"))

    def test_wants_activity(self) -> None:
        q = "which files changed in 2 days for https://github.com/Sumit884-byte/arka"
        self.assertTrue(gr.wants_github_repo_activity(q))

    def test_route_command(self) -> None:
        route = gr.route_command(
            "which files changed in 2 days for https://github.com/Sumit884-byte/arka"
        )
        self.assertEqual(route, "github_repo activity Sumit884-byte/arka --days 2")

    def test_parse_local_repo_name(self) -> None:
        self.assertEqual(gr.parse_local_repo_name("changed in 2 days for this repo:arka"), "arka")
        self.assertEqual(
            gr.parse_local_repo_name("tell which files where changed for this repo arka"),
            "arka",
        )

    def test_route_command_local_repo_name(self) -> None:
        checkout = Path("/tmp/arka-checkout")
        with (
            mock.patch.object(gr, "_find_clone_by_name", return_value=checkout),
            mock.patch.object(
                gr, "_owner_repo_from_root", return_value=("Sumit884-byte", "arka")
            ),
        ):
            route = gr.route_command(
                "tell which files where changed in 2 days for this repo:arka"
            )
        self.assertEqual(route, "github_repo activity Sumit884-byte/arka --days 2")


class GithubRepoCloneDiscoveryTests(unittest.TestCase):
    def test_find_local_clone_uses_checkout_root(self) -> None:
        checkout = Path("/tmp/arka-checkout")
        wrong = Path("/tmp/wrong-repo")

        def fake_roots() -> list[Path]:
            return [wrong, checkout]

        with (
            mock.patch.object(gr, "_candidate_git_roots", side_effect=fake_roots),
            mock.patch.object(
                gr,
                "_local_remote_matches",
                side_effect=lambda root, owner, repo: root == checkout,
            ),
        ):
            found = gr._find_local_clone("Sumit884-byte", "arka")
        self.assertEqual(found, checkout)

    def test_find_local_clone_prefers_cwd_match(self) -> None:
        cwd_root = Path("/tmp/cwd-arka")
        other = Path("/tmp/other")

        def fake_roots() -> list[Path]:
            return [cwd_root, other]

        with (
            mock.patch.object(gr, "_candidate_git_roots", side_effect=fake_roots),
            mock.patch.object(gr, "_local_remote_matches", return_value=True),
        ):
            found = gr._find_local_clone("Sumit884-byte", "arka")
        self.assertEqual(found, cwd_root)

    def test_candidate_git_roots_includes_install_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "my-arka-install"
            install.mkdir()
            with (
                mock.patch.object(gr, "git_root", return_value=None),
                mock.patch("arka.paths.checkout_root", return_value=None),
                mock.patch("arka.paths.arka_home", return_value=None),
                mock.patch.dict(os.environ, {"INSTALL_HOME": str(install)}, clear=False),
            ):
                roots = gr._candidate_git_roots()
            self.assertIn(install.resolve(), [p.resolve() for p in roots])


class GithubRepoFormatFilesTests(unittest.TestCase):
    def test_format_groups_by_directory(self) -> None:
        files = gr.OrderedDict(
            [
                (".env.example", 1),
                ("bin/arka_github_repo.py", 2),
                ("bin/arka_heartbeat.py", 1),
                ("src/arka/agent/github_repo.py", 1),
                ("src/arka/agent/goal.py", 1),
                ("tests/test_llm_fallback.py", 1),
            ]
        )
        lines = gr._format_modified_files(files)
        text = "\n".join(lines)
        self.assertIn("(root)/", text)
        self.assertIn(".env.example", text)
        self.assertIn("bin/", text)
        self.assertIn("arka_github_repo.py (2 commits)", text)
        self.assertIn("src/arka/agent/", text)
        self.assertIn("github_repo.py", text)
        self.assertIn("tests/", text)
        self.assertLess(text.index("bin/"), text.index("src/arka/agent/"))
        self.assertLess(text.index("(root)/"), text.index("bin/"))

    def test_format_truncates_beyond_max(self) -> None:
        files = gr.OrderedDict((f"dir/file{i}.py", 1) for i in range(65))
        lines = gr._format_modified_files(files, max_files=60)
        self.assertTrue(any("... and 5 more file(s)" in line for line in lines))


class GithubRepoFetchTests(unittest.TestCase):
    def test_fetch_uses_local_clone_outside_cwd_repo(self) -> None:
        clone = Path("/tmp/arka-clone")
        commits = [{"sha": "abc1234", "message": "fix", "author": "dev", "date": "2026-07-01"}]
        files = gr.OrderedDict([("src/foo.py", 1)])
        with (
            mock.patch.object(gr, "_find_local_clone", return_value=clone),
            mock.patch.object(gr, "_fetch_via_local_git", return_value=(commits, files)) as local_git,
            mock.patch.object(gr, "_fetch_via_gh_api") as gh_api,
        ):
            out = gr.fetch_repo_activity("Sumit884-byte", "arka", days=2)
        local_git.assert_called_once_with(clone, days=2)
        gh_api.assert_not_called()
        self.assertIn("Source: local git", out)
        self.assertIn("src/", out)
        self.assertIn("foo.py", out)

    def test_unavailable_when_no_clone_and_gh_missing(self) -> None:
        with (
            mock.patch.object(gr, "_find_local_clone", return_value=None),
            mock.patch.object(gr, "_gh_status", return_value="not_installed"),
        ):
            out = gr.fetch_repo_activity("Sumit884-byte", "arka", days=2)
        self.assertIn("gh) is not installed", out)

    def test_unavailable_when_gh_not_authenticated(self) -> None:
        with (
            mock.patch.object(gr, "_find_local_clone", return_value=None),
            mock.patch.object(gr, "_gh_status", return_value="not_authenticated"),
        ):
            out = gr.fetch_repo_activity("Sumit884-byte", "arka", days=2)
        self.assertIn("not authenticated", out)
        self.assertIn("gh auth login", out)

    def test_fetch_via_gh_when_authenticated(self) -> None:
        commits = [{"sha": "def5678", "message": "api", "author": "bot", "date": "2026-07-02"}]
        files = gr.OrderedDict()
        with (
            mock.patch.object(gr, "_find_local_clone", return_value=None),
            mock.patch.object(gr, "_gh_status", return_value="available"),
            mock.patch.object(gr, "_fetch_via_gh_api", return_value=(commits, files)) as gh_api,
        ):
            out = gr.fetch_repo_activity("Sumit884-byte", "arka", days=2)
        gh_api.assert_called_once_with("Sumit884-byte", "arka", days=2)
        self.assertIn("Source: GitHub API", out)


if __name__ == "__main__":
    unittest.main()
