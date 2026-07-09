"""Router and path resolution for find-files-by-size / Downloads queries."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from arka.charts.plot import nl_to_argv
from arka.paths import downloads_dir
from arka.router import route
from arka.routing.file_size import is_file_size_query, route_find_files_by_size


class RouteFindFilesBySizeTests(unittest.TestCase):
    def test_routes_downloads_bigger_than_mb(self) -> None:
        for query in (
            "show downloads bigger than 100 mb",
            "files in downloads over 100MB",
            "large files in downloads",
            "find files larger than 1gb in ~/Downloads",
        ):
            with self.subTest(query=query):
                hit = route_find_files_by_size(query)
                self.assertIsNotNone(hit, query)
                assert hit is not None
                self.assertTrue(hit.startswith("find_files_by_size "))
                self.assertIn(query, hit)

    def test_routes_downloads_size_range(self) -> None:
        for query in (
            "show downloads in range of 100mb to 200mb",
            "files between 50 and 200 mb in downloads",
            "downloads from 100mb to 200mb",
        ):
            with self.subTest(query=query):
                hit = route_find_files_by_size(query)
                self.assertIsNotNone(hit, query)
                assert hit is not None
                self.assertTrue(hit.startswith("find_files_by_size "))
                self.assertIn(query, hit)

    def test_symbolic_router_offline_range_query(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("show downloads in range of 100mb to 200mb")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "find_files_by_size")
        self.assertIn(result.source, ("offline", "fish"))

    def test_chart_does_not_hijack_size_range(self) -> None:
        query = "show downloads in range of 100mb to 200mb"
        self.assertTrue(is_file_size_query(query))
        self.assertEqual(nl_to_argv(query), [])

    def test_does_not_route_unrelated_queries(self) -> None:
        for query in (
            "show me competitions available on kaggle",
            "download the latest release",
            "what is in downloads folder",
        ):
            with self.subTest(query=query):
                self.assertIsNone(route_find_files_by_size(query))

    def test_symbolic_router_offline(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("show downloads bigger than 100 mb")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "find_files_by_size")
        self.assertIn(result.source, ("offline", "fish"))

    def test_fish_router_downloads_query(self) -> None:
        try:
            from arka.fish_bridge import fish_route_preview
        except ImportError:
            self.skipTest("fish_bridge unavailable")
        preview = fish_route_preview("show downloads bigger than 100 mb")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.kind, "skill")
        self.assertTrue(preview.action.startswith("find_files_by_size "))

    def test_fish_router_downloads_size_range(self) -> None:
        try:
            from arka.fish_bridge import fish_route_preview
        except ImportError:
            self.skipTest("fish_bridge unavailable")
        preview = fish_route_preview("show downloads in range of 100mb to 200mb")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.kind, "skill")
        self.assertTrue(preview.action.startswith("find_files_by_size "))
        self.assertNotIn("chart bar", preview.action)

    def test_fish_router_files_in_downloads(self) -> None:
        try:
            from arka.fish_bridge import fish_route_preview
        except ImportError:
            self.skipTest("fish_bridge unavailable")
        preview = fish_route_preview("files in downloads over 100MB")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.kind, "skill")
        self.assertTrue(preview.action.startswith("find_files_by_size "))


class DownloadsDirTests(unittest.TestCase):
    def test_downloads_dir_expands_home(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIE_DOWNLOADS_DIR", None)
            path = downloads_dir()
        self.assertEqual(path, Path.home() / "Downloads")
        self.assertNotIn("~", str(path))

    def test_downloads_dir_honors_override(self) -> None:
        override = "/tmp/custom-downloads"
        with mock.patch.dict(os.environ, {"AIE_DOWNLOADS_DIR": override}, clear=False):
            self.assertEqual(downloads_dir(), Path(override))


class FindFilesBySizeFishTests(unittest.TestCase):
    def test_resolves_downloads_without_tilde(self) -> None:
        import shutil
        import subprocess

        if not shutil.which("fish"):
            self.skipTest("fish not installed")
        cfg = Path(__file__).resolve().parents[1] / "src" / "arka" / "fish" / "config.fish"
        proc = subprocess.run(
            [
                "fish",
                "-c",
                f"source {cfg}; find_files_by_size 'show downloads bigger than 100 mb'; or test $status -eq 1",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        expected = str(Path.home() / "Downloads")
        self.assertIn(expected, proc.stdout)
        self.assertNotIn("~/Downloads", proc.stdout)
        self.assertIn("Files larger than 100MB under", proc.stdout)

    def test_parses_size_range_in_downloads(self) -> None:
        import shutil
        import subprocess

        if not shutil.which("fish"):
            self.skipTest("fish not installed")
        cfg = Path(__file__).resolve().parents[1] / "src" / "arka" / "fish" / "config.fish"
        proc = subprocess.run(
            [
                "fish",
                "-c",
                f"source {cfg}; find_files_by_size 'show downloads in range of 100mb to 200mb'; or test $status -eq 1",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        expected = str(Path.home() / "Downloads")
        self.assertIn(expected, proc.stdout)
        self.assertIn("Files between 100MB and 200MB under", proc.stdout)


if __name__ == "__main__":
    unittest.main()
