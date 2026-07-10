"""Tests for clipboard history skill."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.integrations import clipboard_history as ch
from arka.router import route


class ClipboardHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "clipboard_history.json"

    def _patch_store(self) -> None:
        patcher = mock.patch.object(ch, "_store_path", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_wants_clipboard_history(self) -> None:
        self.assertTrue(ch.wants_clipboard_history("save clipboard to history"))
        self.assertTrue(ch.wants_clipboard_history("show clipboard history"))
        self.assertFalse(ch.wants_clipboard_history("copy file to clipboard"))

    def test_save_and_list(self) -> None:
        self._patch_store()
        with mock.patch.object(ch, "_read_clipboard", return_value="hello world"):
            self.assertEqual(ch.cmd_save(argparse_namespace()), 0)
        out = capture_stdout(ch.cmd_list, argparse_namespace())
        self.assertIn("hello world", out)

    def test_paste_stdout(self) -> None:
        self._patch_store()
        with mock.patch.object(ch, "_read_clipboard", return_value="snippet one"):
            ch.cmd_save(argparse_namespace())
        out = capture_stdout(ch.cmd_paste, argparse_namespace(index="1", stdout=True))
        self.assertEqual(out, "snippet one")

    def test_route_commands(self) -> None:
        self.assertEqual(ch.route_command("save clipboard"), "clipboard_history save")
        self.assertEqual(ch.route_command("paste clipboard entry 2"), "clipboard_history paste 2")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("show clipboard history")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "clipboard_history")


def argparse_namespace(**kwargs):
    from argparse import Namespace

    defaults = {"stdout": False}
    defaults.update(kwargs)
    return Namespace(**defaults)


def capture_stdout(func, args) -> str:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        func(args)
    return buf.getvalue()


if __name__ == "__main__":
    unittest.main()
