"""Tests for arka.env env_int helper."""

from __future__ import annotations

import importlib

from arka.env import _is_placeholder, _scrub_placeholder_env, env_int


def test_env_int_uses_default_for_missing(monkeypatch) -> None:
    monkeypatch.delenv("TEST_ENV_INT", raising=False)
    assert env_int("TEST_ENV_INT", 42) == 42


def test_env_int_uses_default_for_empty_string(monkeypatch) -> None:
    monkeypatch.setenv("TEST_ENV_INT", "")
    assert env_int("TEST_ENV_INT", 42) == 42


def test_placeholder_matches_hyphen_form() -> None:
    assert _is_placeholder("your-secret-here")
    assert _is_placeholder("your_secret_here")
    assert not _is_placeholder("real-api-key-value")


def test_scrub_drops_sslkeylogfile_placeholder(monkeypatch) -> None:
    monkeypatch.setenv("SSLKEYLOGFILE", "your-secret-here")
    monkeypatch.setenv("KEYCHAIN_PATH", "your-secret-here")
    _scrub_placeholder_env()
    assert "SSLKEYLOGFILE" not in __import__("os").environ
    assert "KEYCHAIN_PATH" not in __import__("os").environ


def test_self_improve_imports_with_empty_rounds_env(monkeypatch) -> None:
    monkeypatch.setenv("SELF_IMPROVE_MAX_ROUNDS", "")
    monkeypatch.setenv("SELF_IMPROVE_MAX_STEPS", "")
    import arka.agent.self_improve as self_improve

    importlib.reload(self_improve)
    assert self_improve.DEFAULT_MAX_ROUNDS == 3
    assert self_improve.DEFAULT_MAX_STEPS == 15
