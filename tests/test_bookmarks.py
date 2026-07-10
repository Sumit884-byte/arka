"""Tests for bookmark manager skill."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import bookmarks as bm
from arka.router import route


class BookmarksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "bookmarks.json"

    def _patch_store(self) -> None:
        patcher = mock.patch.object(bm, "_store_path", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_wants_bookmarks(self) -> None:
        self.assertTrue(bm.wants_bookmarks("save this url https://example.com"))
        self.assertTrue(bm.wants_bookmarks("list my bookmarks"))
        self.assertFalse(bm.wants_bookmarks("what is python"))

    def test_save_and_list(self) -> None:
        self._patch_store()
        args = argparse_namespace(url="https://example.com", title="Example", tags="docs,dev", note="")
        self.assertEqual(bm.cmd_save(args), 0)
        out = self._capture_list()
        self.assertIn("Example", out)
        self.assertIn("https://example.com", out)

    def test_search(self) -> None:
        self._patch_store()
        bm.cmd_save(argparse_namespace(url="https://docs.python.org", title="Python docs", tags="python", note=""))
        args = argparse_namespace(query=["python"])
        out = capture_stdout(bm.cmd_search, args)
        self.assertIn("Python docs", out)

    def test_route_save_and_list(self) -> None:
        self.assertEqual(
            bm.route_command("save bookmark https://arka.dev --tags docs"),
            "bookmarks save https://arka.dev --tags docs",
        )
        self.assertEqual(bm.route_command("list my bookmarks"), "bookmarks list")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("list my saved bookmarks")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "bookmarks")

    def _capture_list(self) -> str:
        return capture_stdout(bm.cmd_list, argparse_namespace(tag=None))


def argparse_namespace(**kwargs):
    from argparse import Namespace

    return Namespace(**kwargs)


def capture_stdout(func, args) -> str:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        func(args)
    return buf.getvalue()


if __name__ == "__main__":
    unittest.main()
