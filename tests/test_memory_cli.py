"""Tests for top-level arka memory CLI alias."""

from __future__ import annotations

import unittest
from unittest import mock

from arka.integrations.memory_cli import main, normalize_memory_argv


class NormalizeMemoryArgvTests(unittest.TestCase):
    def test_empty_defaults_to_status(self) -> None:
        self.assertEqual(normalize_memory_argv([]), ["status"])

    def test_remember_aliases(self) -> None:
        self.assertEqual(normalize_memory_argv(["remember", "dark mode"]), ["remember", "dark mode"])
        self.assertEqual(normalize_memory_argv(["store", "x"]), ["remember", "x"])

    def test_recall_aliases(self) -> None:
        self.assertEqual(normalize_memory_argv(["recall", "theme"]), ["recall", "theme"])
        self.assertEqual(normalize_memory_argv(["ctx", "theme"]), ["recall", "theme"])

    def test_scratchpad_flattens_scope(self) -> None:
        self.assertEqual(
            normalize_memory_argv(["scratchpad", "list", "--team", "research"]),
            ["scope", "scratchpad", "list", "--team", "research"],
        )

    def test_promote_flattens_scope(self) -> None:
        self.assertEqual(normalize_memory_argv(["promote", "abc123"]), ["scope", "promote", "abc123"])

    def test_scope_passthrough(self) -> None:
        self.assertEqual(normalize_memory_argv(["scope", "status"]), ["scope", "status"])


class MemoryMainTests(unittest.TestCase):
    def test_empty_shows_status_and_usage(self) -> None:
        with (
            mock.patch("arka.integrations.memory_cli.print_status") as status,
            mock.patch("arka.integrations.memory_cli.run_cli") as run_cli,
        ):
            code = main([])
        self.assertEqual(code, 0)
        status.assert_called_once()
        run_cli.assert_not_called()

    def test_delegates_normalized_argv(self) -> None:
        with mock.patch("arka.integrations.memory_cli.run_cli", return_value=0) as run_cli:
            code = main(["scratchpad", "list"])
        self.assertEqual(code, 0)
        run_cli.assert_called_once_with(["scope", "scratchpad", "list"])


if __name__ == "__main__":
    unittest.main()
