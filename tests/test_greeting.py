from unittest import mock


def test_ok_great_thank_is_acknowledgment_not_code():
    from arka.integrations.greeting import greeting_text, is_acknowledgment, route_greeting

    assert is_acknowledgment("ok great thank")
    assert is_acknowledgment("ok great thanks")
    assert not is_acknowledgment("ok")
    assert not is_acknowledgment("build an shopping app")
    assert route_greeting("ok great thank") == "greeting ok great thank"
    assert "welcome" in greeting_text("ok great thank").lower()


def test_greeting_route_is_deterministic():
    from arka.integrations.greeting import greeting_text, route_greeting
    from arka.routing.symbolic import route_offline_extras

    assert route_greeting("hi") == "greeting hi"
    assert route_greeting("hello!") == "greeting hello!"
    assert route_greeting("fix tests") is None
    assert route_offline_extras("hi") == "greeting hi"
    assert "inspect a repo" in greeting_text("hi")


def test_direct_cli_hi_uses_greeting(capsys):
    from arka.cli import main

    with mock.patch("arka.core.auto_refetch.maybe_auto_refetch", lambda quiet=True: None):
        assert main(["hi"]) == 0

    out = capsys.readouterr().out
    assert "Hi — I’m Arka" in out
    assert "car" not in out.lower()


def test_dispatch_greeting(capsys):
    from arka.dispatch import run_skill

    assert run_skill("greeting hi") == 0
    assert "Hi — I’m Arka" in capsys.readouterr().out
