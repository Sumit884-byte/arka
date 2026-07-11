"""Tests for simulated Elon persona chat skill."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from arka.agent.personas import base, elon, io


@pytest.fixture
def personas_tmp(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("CONFIG_DIR", raising=False)
    monkeypatch.delenv("ARKA_PERSONAS_DIR", raising=False)
    monkeypatch.delenv("PERSONAS_DIR", raising=False)
    monkeypatch.setenv("ARKA_CONFIG_DIR", str(tmp_path))
    io.ensure_layout()
    return tmp_path / "personas"


def test_wants_elon_direct_commands():
    assert elon.wants_elon("elon")
    assert elon.wants_elon("elon chat")
    assert elon.wants_elon("talk_to_elon should I learn Rust?")
    assert elon.wants_elon("arka elon chat")


def test_wants_elon_natural_language():
    assert elon.wants_elon("talk to elon about rockets")
    assert elon.wants_elon("chat with elon musk about AI")
    assert elon.wants_elon("what would elon say about manufacturing")
    assert elon.wants_elon("elon persona")


def test_wants_elon_negative():
    assert not elon.wants_elon("")
    assert not elon.wants_elon("who is elon musk")
    assert not elon.wants_elon("weather today")


def test_sanitize_prompt():
    assert elon.sanitize_prompt("talk to elon about Rust") == "Rust"
    assert elon.sanitize_prompt('elon "should I learn Rust?"') == "should I learn Rust?"
    assert elon.sanitize_prompt("what would elon say about first principles") == "first principles"


def test_route_command_one_shot():
    assert elon.route_command("talk to elon about Rust") == "elon Rust"
    assert elon.route_command("what would elon say about sleep") == "elon sleep"
    assert elon.route_command("elon chat") == "elon chat"


def test_route_command_negative():
    assert elon.route_command("weather today") == ""


def test_nl_to_argv():
    assert elon.nl_to_argv("elon chat") == ["chat"]
    assert elon.nl_to_argv("talk to elon about Mars") == ["Mars"]


def test_chat_once_mock_llm(personas_tmp):
    with mock.patch.object(base, "_llm_reply", return_value="Do hard things."):
        out = elon.chat_once("should I learn Rust?", show_disclaimer=True)
    assert "Note:" in out
    assert "──" in out
    assert "Do hard things." in out


def test_chat_once_empty_question():
    assert elon.chat_once("   ") == ""
