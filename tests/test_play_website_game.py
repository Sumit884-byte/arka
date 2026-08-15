"""Tests for play_website_game — routing, search, open, and MCP."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from arka.agent.play_website_game import (
    is_play_website_game_cli_argv,
    nl_to_argv,
    open_game,
    pick_game_url,
    play_website_game_result,
    run_play_website_game_cli,
    search_games,
)
from arka.integrations.mcp_server import _handle_arka_play_website_game, _mcp_disabled_skill_heads
from arka.integrations.open_url import route_command, wants_open_url
from arka.router import route
from arka.routing.symbolic import route_play_website_game


class _FakeKeyboard:
    def __init__(self, page: "_FakePage") -> None:
        self.page = page

    def press(self, key: str) -> None:
        self.page.events.append(("key", key))


class _FakeLocatorItem:
    def __init__(self, page: "_FakePage", selector: str, index: int) -> None:
        self.page = page
        self.selector = selector
        self.index = index

    def is_visible(self) -> bool:
        return self.selector == "button" and self.index == 0

    def inner_text(self) -> str:
        if self.selector == "body":
            return "Classic snake browser game"
        return "Play" if self.selector == "button" and self.index == 0 else ""

    def click(self, timeout: int = 10_000) -> None:
        self.page.events.append(("click", self.selector, self.index, timeout))


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str) -> None:
        self.page = page
        self.selector = selector

    def count(self) -> int:
        if self.selector in {"canvas", "button"}:
            return 1
        return 0

    def nth(self, index: int) -> _FakeLocatorItem:
        return _FakeLocatorItem(self.page, self.selector, index)


class _FakeResponse:
    status = 200


class _FakePage:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.keyboard = _FakeKeyboard(self)

    def on(self, *_args) -> None:
        return None

    def goto(self, url: str, *, wait_until: str, timeout: int) -> _FakeResponse:
        self.events.append(("goto", url, wait_until, timeout))
        return _FakeResponse()

    def wait_for_timeout(self, ms: int) -> None:
        self.events.append(("wait", ms))

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def title(self) -> str:
        return "Snake Game"

    def screenshot(self, *, path: str | None = None, full_page: bool = False, type: str = "png") -> bytes | None:
        data = b"fake-png-bytes"
        if path:
            Path(path).write_bytes(data)
            self.events.append(("screenshot", Path(path).name, full_page))
            return None
        self.events.append(("screenshot_bytes", type, full_page))
        return data


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> _FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser

    def launch(self, *, headless: bool) -> _FakeBrowser:
        return self.browser


class _FakePlaywright:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.chromium = _FakeChromium(browser)


class _FakePlaywrightManager:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser

    def __enter__(self) -> _FakePlaywright:
        return _FakePlaywright(self.browser)

    def __exit__(self, *_args) -> None:
        return None


def _install_fake_playwright(monkeypatch: pytest.MonkeyPatch, page: _FakePage) -> _FakeBrowser:
    browser = _FakeBrowser(page)
    fake_module = types.SimpleNamespace(sync_playwright=lambda: _FakePlaywrightManager(browser))
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)
    return browser


class TestPlayWebsiteGameRouting:
    def test_route_open_url(self) -> None:
        routed = route_play_website_game("open browser game at https://example.com/snake")
        assert routed is not None
        assert routed.startswith("play_website_game open ")
        assert "https://example.com/snake" in routed

    def test_route_search_online(self) -> None:
        routed = route_play_website_game("play snake online")
        assert routed is not None
        assert "search" in routed
        assert "snake" in routed
        assert "--open" in routed

    def test_route_skips_qa_game_check(self) -> None:
        assert route_play_website_game("check my game at https://localhost:5173") is None

    def test_nl_to_argv_open(self) -> None:
        argv = nl_to_argv("play website game at https://example.com/game")
        assert argv[:2] == ["open", "https://example.com/game"]

    def test_nl_to_argv_explicit_open(self) -> None:
        argv = nl_to_argv("play_website_game open https://shadowfight2.com/play/")
        assert argv == ["open", "https://shadowfight2.com/play/"]

    def test_route_explicit_open(self) -> None:
        routed = route_play_website_game("play_website_game open https://shadowfight2.com/play/")
        assert routed == "play_website_game open https://shadowfight2.com/play/"

    def test_route_explicit_subcommands(self) -> None:
        assert route_play_website_game("play_website_game check") == "play_website_game check"
        assert route_play_website_game("play_website_game search snake") == "play_website_game search snake"

    def test_router_prefers_play_website_game_over_open_url(self) -> None:
        cmd = "play_website_game open https://shadowfight2.com/play/"
        hit = route(cmd)
        assert hit is not None
        assert hit.skill.startswith("play_website_game open ")
        assert not wants_open_url(cmd)
        assert route_command(cmd) == ""

    def test_is_play_website_game_cli_argv(self) -> None:
        assert is_play_website_game_cli_argv(["play_website_game", "check"])
        assert not is_play_website_game_cli_argv(["open", "https://example.com"])

    def test_run_play_website_game_cli_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "arka.agent.play_website_game.cmd_check",
            lambda _args: 0,
        )
        assert run_play_website_game_cli(["play_website_game", "check"]) == 0


def test_search_games_mocked() -> None:
    rows = [
        {"link": "https://example.com/snake", "title": "Snake", "snippet": "Classic game"},
        {"link": "https://example.com/other", "title": "Other", "snippet": "Unrelated"},
    ]
    with mock.patch("arka.agent.chat.duckduckgo_search", return_value=rows):
        results = search_games("snake")
    assert len(results) == 2
    assert results[0]["url"] == "https://example.com/snake"


def test_pick_game_url_prefers_query_match() -> None:
    rows = [
        {"link": "https://example.com/other", "title": "Other", "snippet": "Unrelated"},
        {"link": "https://example.com/snake", "title": "Snake", "snippet": "Classic snake game"},
    ]
    with mock.patch("arka.agent.play_website_game.search_games", return_value=[
        {"url": row["link"], "title": row["title"], "snippet": row["snippet"]} for row in rows
    ]):
        picked = pick_game_url("snake")
    assert picked is not None
    assert picked["url"] == "https://example.com/snake"


def test_open_game_headless_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    page = _FakePage()
    browser = _install_fake_playwright(monkeypatch, page)
    monkeypatch.chdir(tmp_path)

    result = open_game("example.com/game", headless=True, wait_seconds=0, auto_start=True)

    assert result["ok"] is True
    assert result["url"] == "https://example.com/game"
    assert result["title"] == "Snake Game"
    assert result["headless"] is True
    assert result["screenshot"] is not None
    assert browser.closed is True
    assert any(event[0] == "goto" for event in page.events)


def test_play_website_game_result_search_only() -> None:
    with mock.patch(
        "arka.agent.play_website_game.search_games",
        return_value=[{"url": "https://example.com/snake", "title": "Snake", "snippet": ""}],
    ), mock.patch(
        "arka.agent.play_website_game.pick_game_url",
        return_value={"url": "https://example.com/snake", "title": "Snake", "snippet": ""},
    ):
        result = play_website_game_result(query="snake", open_best=False)
    assert result["ok"] is True
    assert result["picked"]["url"] == "https://example.com/snake"


def test_mcp_disabled_by_default() -> None:
    assert "play_website_game" in _mcp_disabled_skill_heads()


def test_mcp_requires_allow_browser() -> None:
    with pytest.raises(ValueError, match="allow_browser"):
        _handle_arka_play_website_game({"action": "open", "url": "https://example.com/game"})


def test_mcp_open_headless_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage()
    _install_fake_playwright(monkeypatch, page)
    payload = _handle_arka_play_website_game(
        {
            "action": "open",
            "url": "https://example.com/game",
            "headless": True,
        }
    )
    data = json.loads(payload)
    assert data["ok"] is True
    assert data["url"] == "https://example.com/game"


def test_mcp_parse() -> None:
    payload = _handle_arka_play_website_game({"action": "parse", "text": "play tetris online"})
    data = json.loads(payload)
    assert data["argv"][0] == "search"
    assert "tetris" in data["argv"][1]


def test_nl_to_argv_agent() -> None:
    argv = nl_to_argv("play game with ai agent https://example.com/snake")
    assert argv[:2] == ["agent", "https://example.com/snake"]


def test_parse_agent_action_json() -> None:
    from arka.agent.game_agent import parse_agent_action

    action = parse_agent_action('{"action":{"type":"key","key":"ArrowUp"},"reason":"avoid wall"}')
    assert action["type"] == "key"
    assert action["key"] == "ArrowUp"


def test_pattern_save_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from arka.agent.game_learning import (
        load_game_state,
        q_update,
        remember_pattern,
        save_game_state,
        state_path,
    )

    monkeypatch.setattr("arka.agent.game_learning.patterns_dir", lambda: tmp_path)
    remember_pattern(
        "example.com",
        url="https://example.com/snake",
        actions=[{"type": "key", "key": "ArrowUp"}],
        reward=1.5,
        screen_hint="snake menu",
    )
    state = load_game_state("example.com")
    assert state["patterns"]
    assert state["patterns"][0]["reward"] == 1.5
    q_update(state, "screen-a", "key:ArrowUp", 0.8, "screen-b")
    save_game_state("example.com", state)
    reloaded = json.loads(state_path("example.com").read_text(encoding="utf-8"))
    assert "screen-a" in reloaded["q_table"]
    assert reloaded["q_table"]["screen-a"]["key:ArrowUp"] > 0


def test_run_agent_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from arka.agent import game_agent

    page = _FakePage()
    _install_fake_playwright(monkeypatch, page)
    monkeypatch.setattr("arka.agent.game_learning.patterns_dir", lambda: tmp_path)

    def _fake_turn(*_args, **_kwargs):
        return {
            "status": "passed",
            "action": {"type": "key", "key": "ArrowUp"},
            "source": "vision",
            "reward": 0.2,
            "screen_key": "abc",
            "next_screen_key": "def",
            "reward_signals": {"survival_turn": 1},
        }

    monkeypatch.setattr(game_agent, "run_agent_turn", _fake_turn)
    result = game_agent.run_agent(
        "https://example.com/snake",
        turns=2,
        learn=True,
        rl=True,
        headless=True,
        auto_start=False,
    )
    assert result["ok"] is True
    assert result["turns"] == 2
    assert len(result["turns_log"]) == 2
    assert result["total_reward"] == pytest.approx(0.4)


def test_mcp_agent_headless_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from arka.agent import game_agent

    page = _FakePage()
    _install_fake_playwright(monkeypatch, page)
    monkeypatch.setattr("arka.agent.game_learning.patterns_dir", lambda: tmp_path)
    monkeypatch.setattr(
        game_agent,
        "run_agent_turn",
        lambda *_a, **_k: {
            "status": "passed",
            "action": {"type": "key", "key": "ArrowRight"},
            "source": "q_table",
            "reward": 0.1,
            "screen_key": "x",
            "next_screen_key": "y",
            "reward_signals": {},
        },
    )
    payload = _handle_arka_play_website_game(
        {
            "action": "agent",
            "url": "https://example.com/game",
            "headless": True,
            "turns": 1,
            "learn": True,
        }
    )
    data = json.loads(payload)
    assert data["ok"] is True
    assert data["turns"] == 1
    assert data["experimental"] is True

