"""Tests for the reusable persona system."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from arka.agent.personas import base, cli, io, schema
from arka.agent.personas import elon


@pytest.fixture
def personas_tmp(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ARKA_CONFIG_DIR", str(tmp_path))
    io.ensure_layout()
    return tmp_path / "personas"


def test_slugify():
    assert schema.slugify("Steve Jobs") == "steve-jobs"
    assert schema.slugify("elon") == "elon"


def test_parse_persona_requires_system_prompt():
    with pytest.raises(ValueError, match="system_prompt"):
        schema.parse_persona({"name": "test"})


def test_seed_and_load_elon(personas_tmp):
    path = io.seed_persona("elon")
    assert path is not None
    persona = io.load_persona("elon")
    assert persona.name == "elon"
    assert "simulated" in persona.system_prompt.lower()
    assert persona.formatted_disclaimer.startswith("Note:")


def test_list_personas(personas_tmp):
    io.seed_persona("elon")
    names = io.list_personas()
    assert "elon" in names


def test_save_persona(personas_tmp):
    persona = schema.Persona(
        name="coach",
        display_name="Coach",
        description="Supportive mentor",
        system_prompt="You are a simulated supportive coach.",
    )
    path = io.save_persona(persona)
    assert path.is_file()
    loaded = io.load_persona("coach")
    assert loaded.display_name == "Coach"


def test_wants_persona_general():
    assert base.wants_persona("talk to socrates about virtue")
    assert base.wants_persona("persona elon about rockets")
    assert base.wants_persona("create persona for steve jobs")
    assert base.wants_persona("arka persona list")


def test_wants_persona_negative():
    assert not base.wants_persona("")
    assert not base.wants_persona("who is elon musk")
    assert not base.wants_persona("weather today")


def test_route_persona_chat():
    assert base.route_command("talk to socrates about virtue") == "persona chat socrates virtue"
    assert base.route_command("persona chat elon about Rust") == "persona chat elon Rust"
    assert base.route_command("create persona for steve jobs") == "persona create steve-jobs"


def test_route_elon_backward_compat():
    assert elon.route_command("talk to elon about Rust") == "elon Rust"
    assert elon.route_command("elon chat") == "elon chat"
    assert elon.nl_to_argv("talk to elon about Mars") == ["Mars"]


def test_sanitize_prompt():
    assert base.sanitize_prompt("talk to elon about Rust", persona_name="elon") == "Rust"
    assert base.sanitize_prompt("persona socrates about wisdom", persona_name="socrates") == "wisdom"


def test_chat_once_mock(personas_tmp):
    io.seed_persona("elon")
    persona = io.resolve_persona("elon")
    with mock.patch.object(base, "_llm_reply", return_value="First principles."):
        out = base.chat_once(persona, "rockets?", show_disclaimer=True)
    assert out.startswith("Note:")
    assert "First principles." in out


def test_cmd_create_from_template(personas_tmp, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    code = cli.cmd_create("my-elon", template="elon", yes=False)
    assert code == 0
    persona = io.load_persona("my-elon")
    assert persona.name == "my-elon"
    assert persona.system_prompt


def test_cmd_chat_missing(personas_tmp, capsys):
    code = cli.cmd_chat("nobody", "hello")
    assert code == 1
    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_routing_symbolic():
    from arka.routing.symbolic import route_elon

    assert route_elon("talk to elon about AI") == "persona chat elon AI"
    assert route_elon("create persona for marie curie") == "persona create marie-curie"

def test_run_legacy_module_forwards_argv_to_personalize_parse(capsys):
    import sys

    from arka._bootstrap import run_legacy_module

    old = sys.argv
    sys.argv = ["arka_personalize.py", "parse", "talk to elon about manufacturing at scale"]
    try:
        assert run_legacy_module("arka.core.personalize") == 0
        assert capsys.readouterr().out.strip() == ""
    finally:
        sys.argv = old


def test_run_legacy_module_personalize_parse_recommend(capsys):
    import sys

    from arka._bootstrap import run_legacy_module

    old = sys.argv
    sys.argv = ["arka_personalize.py", "parse", "recommend skills for me"]
    try:
        assert run_legacy_module("arka.core.personalize") == 0
        assert capsys.readouterr().out.strip() == "recommend"
    finally:
        sys.argv = old

def test_persona_cli_chat_multi_word_question():
    from arka.agent.personas import cli

    with __import__("unittest").mock.patch.object(cli, "cmd_chat", return_value=0) as chat:
        assert cli.main(["chat", "elon", "manufacturing", "at", "scale"]) == 0
    chat.assert_called_once_with("elon", "manufacturing at scale")

def test_persona_cli_strips_fish_double_dash():
    from arka.agent.personas import cli

    with __import__("unittest").mock.patch.object(cli, "cmd_chat", return_value=0) as chat:
        assert cli.main(["--", "chat", "elon", "manufacturing", "at", "scale"]) == 0
    chat.assert_called_once_with("elon", "manufacturing at scale")

