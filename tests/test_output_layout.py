"""Tests for shared terminal output layout helpers."""

from __future__ import annotations

import io
import os
from unittest import mock

import pytest

from arka.core import output_layout as ol


@pytest.fixture(autouse=True)
def _clean_output_env(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("ARKA_OUTPUT_STYLE", raising=False)
    monkeypatch.delenv("ARKA_OUTPUT_EMOJI", raising=False)
    monkeypatch.delenv("ARKA_MARKDOWN_STYLE", raising=False)


def test_section_plain():
    buf = io.StringIO()
    with mock.patch.object(ol.sys.stdout, "isatty", return_value=False):
        ol.section("Test", stream=buf)
    out = buf.getvalue()
    assert "━━━ Test ━━━" in out
    assert "\033[" not in out


def test_section_colored_tty(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    buf = io.StringIO()
    buf.isatty = lambda: True  # type: ignore[attr-defined]
    ol.section("Test", stream=buf)
    assert "\033[" in buf.getvalue()
    assert "Test" in buf.getvalue()


def test_status_messages_respect_no_color():
    buf = io.StringIO()
    buf.isatty = lambda: True  # type: ignore[attr-defined]
    with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
        ol.success("done", stream=buf)
        ol.error("fail", stream=buf)
        ol.warn("careful", stream=buf)
        ol.info("note", stream=buf)
    combined = buf.getvalue()
    assert "\033[" not in combined
    assert "[ok] done" in combined
    assert "[error] fail" in combined
    assert "[warn] careful" in combined


def test_emoji_prefix_when_enabled(monkeypatch):
    monkeypatch.setenv("ARKA_OUTPUT_EMOJI", "1")
    buf = io.StringIO()
    buf.isatty = lambda: True  # type: ignore[attr-defined]
    ol.success("saved", stream=buf)
    assert "✓ saved" in buf.getvalue()


def test_plain_table_for_pipes():
    buf = io.StringIO()
    with mock.patch.object(ol.sys.stdout, "isatty", return_value=False):
        ol.table(["Name", "Path"], [["chair", "/tmp/chair.glb"]], stream=buf)
    assert buf.getvalue().strip() == "Name\tPath\nchair\t/tmp/chair.glb"


def test_result_box_indents_body():
    buf = io.StringIO()
    with mock.patch.object(ol.sys.stdout, "isatty", return_value=False):
        ol.result_box("Result", "line one\nline two", stream=buf)
    out = buf.getvalue()
    assert "━━━ Result ━━━" in out
    assert "  line one" in out
    assert "  line two" in out


def test_output_style_plain_disables_color():
    buf = io.StringIO()
    buf.isatty = lambda: True  # type: ignore[attr-defined]
    with mock.patch.dict(os.environ, {"ARKA_OUTPUT_STYLE": "plain"}):
        assert ol.color_enabled(stream=buf) is False
        ol.success("plain ok", stream=buf)
    assert "\033[" not in buf.getvalue()


def test_list_items_plain():
    buf = io.StringIO()
    with mock.patch.object(ol.sys.stdout, "isatty", return_value=False):
        ol.list_items(["alpha", "beta"], stream=buf)
    out = buf.getvalue()
    assert "  - alpha" in out
    assert "  - beta" in out
