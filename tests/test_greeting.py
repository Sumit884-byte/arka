from unittest import mock


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
