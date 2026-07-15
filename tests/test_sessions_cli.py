from __future__ import annotations

from unittest.mock import patch


def test_session_skill_dispatches_to_message_sessions() -> None:
    from arka.dispatch import run_skill

    with patch("arka.integrations.message_sessions.main", return_value=0) as main:
        assert run_skill("session list") == 0
        main.assert_called_once_with(["list"])


def test_natural_language_session_routes() -> None:
    from arka.router import route

    with patch.dict("os.environ", {"ROUTE_MODE": "symbolic_only"}):
        assert route("list my sessions").skill == "session list"
        assert route("resume my session").skill == "session resume cli default"
