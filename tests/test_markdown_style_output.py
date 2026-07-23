"""Tests for auto markdown styling in print_block."""

from __future__ import annotations

from arka.output import print_block


def test_print_block_styles_markdown_body(capsys):
    body = "# Hello\n\n- **one**\n- two\n"
    print_block("Answer", body)
    out = capsys.readouterr().out
    assert "━━━ Answer ━━━" in out
    assert "Hello" in out
    assert "  # Hello" not in out
