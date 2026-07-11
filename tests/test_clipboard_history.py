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

    def test_router_ai_only_prefers_clipboard_history(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "ai_only"}, clear=False):
            result = route("show clipboard history")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill, "clipboard_history list")
        self.assertNotEqual(result.source, "llm")

    def test_clipboard_caps_darwin_uses_pbpaste(self) -> None:
        fake = {
            "platform": "macos",
            "capabilities": {
                "clipboard_copy": "pbcopy",
                "clipboard_paste": "pbpaste",
            },
        }
        with mock.patch.object(ch, "detect_platform", return_value=fake):
            paste, copy = ch._clipboard_caps()
        self.assertEqual(paste, "pbpaste")
        self.assertEqual(copy, "pbcopy")

    def test_read_clipboard_darwin_calls_pbpaste(self) -> None:
        fake_caps = ("pbpaste", "pbcopy")
        completed = mock.Mock(returncode=0, stdout="real clipboard text\n", stderr="")
        with (
            mock.patch.object(ch, "_clipboard_caps", return_value=fake_caps),
            mock.patch.object(ch.platform, "system", return_value="Darwin"),
            mock.patch.object(ch, "_resolve_binary", return_value="/usr/bin/pbpaste") as resolve,
            mock.patch.object(ch.subprocess, "run", return_value=completed) as run,
        ):
            text = ch.read_clipboard()
        resolve.assert_called_once_with("pbpaste", darwin_default=ch._DARWIN_PBPASTE)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/usr/bin/pbpaste"])
        self.assertEqual(text, "real clipboard text\n")

    def test_read_clipboard_rejects_mock_stub(self) -> None:
        completed = mock.Mock(returncode=0, stdout="(mocked\n", stderr="")
        with (
            mock.patch.object(ch, "_clipboard_caps", return_value=("pbpaste", "pbcopy")),
            mock.patch.object(ch.platform, "system", return_value="Darwin"),
            mock.patch.object(ch, "_resolve_binary", return_value="/usr/bin/pbpaste"),
            mock.patch.object(ch.subprocess, "run", return_value=completed),
        ):
            text = ch.read_clipboard()
        self.assertEqual(text, "")

    def test_save_rejects_mock_stub_clipboard(self) -> None:
        self._patch_store()
        with mock.patch.object(ch, "_read_clipboard", return_value=""):
            rc = ch.cmd_save(argparse_namespace())
        self.assertEqual(rc, 1)
        self.assertFalse(self.store.is_file())


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
