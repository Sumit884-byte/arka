"""Tests for markdown terminal styling."""

from __future__ import annotations

import os

import pytest

from arka.core import markdown_style as ms


SAMPLE = """# Title

A **bold** point with `inline code`.

- first item
- second item
"""


def test_looks_like_markdown_positive():
    assert ms.looks_like_markdown(SAMPLE) is True


def test_looks_like_markdown_negative():
    assert ms.looks_like_markdown("hello world") is False
    assert ms.looks_like_markdown("run pytest -q") is False


def test_maybe_style_skips_plain_text():
    assert ms.maybe_style_markdown("plain answer") == "plain answer"


def test_maybe_style_respects_disable(monkeypatch):
    monkeypatch.setenv("ARKA_MARKDOWN_STYLE", "0")
    assert ms.maybe_style_markdown(SAMPLE) == SAMPLE


def test_style_markdown_ansi_backend():
    styled = ms.style_markdown(SAMPLE, backend="ansi")
    assert styled != SAMPLE
    assert "\033[" in styled
    assert "Title" in styled


def test_style_markdown_rich_backend():
    styled = ms.style_markdown(SAMPLE, backend="rich")
    assert "Title" in styled


def test_style_markdown_from_file(tmp_path):
    path = tmp_path / "note.md"
    path.write_text(SAMPLE, encoding="utf-8")
    styled = ms.style_markdown(path.read_text(encoding="utf-8"), backend="ansi")
    assert "Title" in styled


def test_route_command_with_file():
    route = ms.route_command("style markdown README.md")
    assert route == "markdown_style style README.md"


def test_route_command_without_file():
    route = ms.route_command("render markdown")
    assert route == "markdown_style style -"


def test_main_detect():
    assert ms.main(["detect", "# hello"]) == 0
