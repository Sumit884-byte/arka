"""Tests for markdown_style NL routing."""

from __future__ import annotations

import unittest

from arka.core import markdown_style as ms
from arka.routing.symbolic import route_markdown_style


class MarkdownStyleRoutingTests(unittest.TestCase):
    def test_wants_markdown_style(self) -> None:
        self.assertTrue(ms.wants_markdown_style("style this as markdown"))
        self.assertTrue(ms.wants_markdown_style("render markdown README.md"))
        self.assertFalse(ms.wants_markdown_style("read markdown file docs/guide.md"))

    def test_route_command(self) -> None:
        self.assertEqual(
            ms.route_command("pretty print markdown notes/todo.md"),
            "markdown_style style notes/todo.md",
        )

    def test_symbolic_route(self) -> None:
        hit = route_markdown_style("format markdown CHANGELOG.md")
        self.assertEqual(hit, "markdown_style style CHANGELOG.md")


if __name__ == "__main__":
    unittest.main()
