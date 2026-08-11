"""Tests for duplicate text detection skill."""

from __future__ import annotations

import unittest
from unittest import mock

from arka.agent import duplicate_text as dt
from arka.router import route
from arka.routing.symbolic import route_duplicate_text, route_offline_extras


class DuplicateTextTests(unittest.TestCase):
    def test_exact_duplicates_across_files(self) -> None:
        with unittest.mock.patch.object(dt, "_iter_files") as iter_files:
            root = mock.Mock()
            file_a = mock.Mock()
            file_a.suffix = ".tsx"
            file_b = mock.Mock()
            file_b.suffix = ".tsx"
            iter_files.return_value = [file_a, file_b]
            with mock.patch.object(dt, "_extract_from_file") as extract:
                extract.side_effect = [
                    [(3, "Save changes")],
                    [(8, "Save changes")],
                ]
                payload = dt.scan(str(root))
        self.assertEqual(len(payload["exact"]), 1)
        self.assertEqual(payload["exact"][0]["normalized"], "save changes")
        self.assertEqual(len(payload["exact"][0]["occurrences"]), 2)

    def test_normalized_duplicates(self) -> None:
        with unittest.mock.patch.object(dt, "_iter_files") as iter_files:
            root = mock.Mock()
            file_a = mock.Mock()
            file_a.suffix = ".html"
            file_b = mock.Mock()
            file_b.suffix = ".html"
            iter_files.return_value = [file_a, file_b]
            with mock.patch.object(dt, "_extract_from_file") as extract:
                extract.side_effect = [
                    [(1, "Save Changes!")],
                    [(2, "save changes")],
                ]
                payload = dt.scan(str(root))
        self.assertEqual(len(payload["exact"]), 1)
        self.assertEqual(payload["exact"][0]["normalized"], "save changes")

    def test_near_duplicates(self) -> None:
        with unittest.mock.patch.object(dt, "_iter_files") as iter_files:
            root = mock.Mock()
            file_a = mock.Mock()
            file_a.suffix = ".tsx"
            file_b = mock.Mock()
            file_b.suffix = ".tsx"
            iter_files.return_value = [file_a, file_b]
            with mock.patch.object(dt, "_extract_from_file") as extract:
                extract.side_effect = [
                    [(1, "Save your changes now")],
                    [(2, "Save your changes today")],
                ]
                payload = dt.scan(str(root), near_threshold=0.75)
        self.assertEqual(len(payload["exact"]), 0)
        self.assertGreaterEqual(len(payload["near"]), 1)

    def test_route_command(self) -> None:
        self.assertEqual(dt.route_command("check for duplicate text"), "duplicate_text .")
        self.assertEqual(dt.route_command("find semantically same copy in src"), "duplicate_text src")
        self.assertEqual(dt.route_command("no repeating text under web/"), "duplicate_text web/")
        self.assertEqual(dt.route_command("lint this repo"), "")

    def test_symbolic_route(self) -> None:
        self.assertEqual(route_duplicate_text("check for duplicate text"), "duplicate_text .")
        hit = route_offline_extras("find duplicate text in src/ui")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "duplicate_text")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict("os.environ", {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("check for duplicate text")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "duplicate_text")

    def test_integration_scan(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A.tsx").write_text('<button>Save changes</button>\n', encoding="utf-8")
            (root / "B.tsx").write_text('<Chip label="Save changes" />\n', encoding="utf-8")
            payload = dt.scan(str(root))
            self.assertEqual(len(payload["exact"]), 1)
            self.assertEqual(len(payload["exact"][0]["occurrences"]), 2)


if __name__ == "__main__":
    unittest.main()
