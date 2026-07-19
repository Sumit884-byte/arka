from __future__ import annotations

import sys
import types
from pathlib import Path


class _FakeVideo:
    def __init__(self, path: Path) -> None:
        self._path = path

    def path(self) -> str:
        return str(self._path)


class _FakeLocatorItem:
    def __init__(self, page: "_FakePage", selector: str, index: int) -> None:
        self.page = page
        self.selector = selector
        self.index = index

    def is_visible(self) -> bool:
        return self.selector == "button" and self.index == 0

    def inner_text(self) -> str:
        if self.selector == "body":
            return "WebGL racing physics battle game"
        return "Start Game" if self.selector == "button" and self.index == 0 else ""

    def click(self, timeout: int = 10_000) -> None:
        self.page.events.append(("click", self.selector, self.index, timeout))


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str) -> None:
        self.page = page
        self.selector = selector

    def count(self) -> int:
        if self.selector == "canvas":
            return 1
        if self.selector == "button":
            return 1
        return 0

    def nth(self, index: int) -> _FakeLocatorItem:
        return _FakeLocatorItem(self.page, self.selector, index)


class _FakeKeyboard:
    def __init__(self, page: "_FakePage") -> None:
        self.page = page

    def press(self, key: str) -> None:
        self.page.events.append(("key", key))


class _FakePage:
    def __init__(self, video_path: Path) -> None:
        self.events: list[tuple] = []
        self.keyboard = _FakeKeyboard(self)
        self.video = _FakeVideo(video_path)
        self.closed = False

    def on(self, *_args) -> None:
        return None

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.events.append(("goto", url, wait_until, timeout))

    def wait_for_timeout(self, ms: int) -> None:
        self.events.append(("wait", ms))

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def screenshot(self, *, path: str) -> None:
        Path(path).write_bytes(b"png")
        self.events.append(("screenshot", Path(path).name))

    def close(self) -> None:
        self.closed = True
        self.events.append(("page_close",))


class _FakeContext:
    def __init__(self, video_path: Path) -> None:
        self.video_path = video_path
        self.record_video_dir: str | None = None
        self.page = _FakePage(video_path)
        self.closed = False

    def new_page(self) -> _FakePage:
        return self.page

    def close(self) -> None:
        self.video_path.write_bytes(b"webm")
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self.context = context
        self.closed = False

    def new_context(self, *, record_video_dir: str | None = None) -> _FakeContext:
        self.context.record_video_dir = record_video_dir
        return self.context

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser

    def launch(self, *, headless: bool) -> _FakeBrowser:
        assert headless is True
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


def test_game_check_records_video_while_interacting(monkeypatch, tmp_path):
    from arka.agent.game_control import check_game

    video_path = tmp_path / "recording.webm"
    context = _FakeContext(video_path)
    browser = _FakeBrowser(context)
    fake_module = types.SimpleNamespace(sync_playwright=lambda: _FakePlaywrightManager(browser))
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)

    result = check_game("http://localhost:5173", output=str(tmp_path / "out"), record=True)

    assert context.record_video_dir == str(tmp_path / "out")
    assert result["video"] == str(video_path)
    assert result["recording_started_before_actions"] is True
    assert result["play_strategy"]["depth"] == "standard"
    assert "arrow-key movement" in result["play_strategy"]["edge_cases"]
    assert result["clicked_controls"] >= 2
    assert result["gameplay_started"] is True
    assert result["screenshots"][0].endswith("frame-000-loaded.png")
    assert context.page.closed is True
    assert context.closed is True
    assert browser.closed is True
    event_names = [event[0] for event in context.page.events]
    assert event_names.index("click") < event_names.index("key")


def test_gameplay_strategy_chooses_depth_and_caps_actions(tmp_path):
    from arka.agent.game_control import plan_gameplay

    page = _FakePage(tmp_path / "recording.webm")
    deep = plan_gameplay(page, url="http://localhost:5173/racing-physics", depth="auto")
    assert deep["depth"] == "deep"
    assert "pause/reset keys" in deep["edge_cases"]
    assert any(action.get("key") == "Escape" for action in deep["actions"])

    capped = plan_gameplay(page, url="http://localhost:5173/racing-physics", depth="auto", max_actions=3)
    assert capped["depth"] == "deep"
    assert len(capped["actions"]) == 3


def test_gameplay_duration_creates_safe_wait_chunks(tmp_path):
    from arka.agent.game_control import MAX_WAIT_MS, parse_duration, plan_gameplay

    page = _FakePage(tmp_path / "recording.webm")
    assert parse_duration("30s") == 30
    assert parse_duration("2m") == 120
    plan = plan_gameplay(page, url="http://localhost:5173", depth="smoke", duration_seconds=25)
    waits = [action for action in plan["actions"] if action.get("purpose", "").startswith("long-session observation")]
    assert [wait["ms"] for wait in waits] == [MAX_WAIT_MS, MAX_WAIT_MS, 5000]
    assert plan["duration_seconds"] == 25
    assert plan["wait_chunk_limit_ms"] == MAX_WAIT_MS


def test_verify_game_visuals_reports_good(monkeypatch, tmp_path):
    from arka.agent.game_control import verify_game_visuals

    frames = []
    for name in ("loaded.png", "mid.png", "final.png"):
        path = tmp_path / name
        path.write_bytes(b"png")
        frames.append(str(path))
    monkeypatch.setattr(
        "arka.agent.visual_diagnose.diagnose",
        lambda image: {"image": image, "diagnosis": '{"verdict":"good","issues":[],"fixes":[]}'},
    )

    result = verify_game_visuals(frames)

    assert result["status"] == "passed"
    assert result["verdict"] == "good"
    assert len(result["checked"]) == 3


def test_game_check_verify_blocks_done_on_visual_issue(monkeypatch, tmp_path):
    from arka.agent.game_control import check_game

    video_path = tmp_path / "recording.webm"
    context = _FakeContext(video_path)
    browser = _FakeBrowser(context)
    fake_module = types.SimpleNamespace(sync_playwright=lambda: _FakePlaywrightManager(browser))
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)
    monkeypatch.setattr(
        "arka.agent.visual_diagnose.diagnose",
        lambda image: {
            "image": image,
            "diagnosis": '{"verdict":"needs_fix","severity":"high","issues":["player hidden behind HUD"],"fixes":["move HUD"]}',
        },
    )

    result = check_game("http://localhost:5173", output=str(tmp_path / "out"), verify_visuals=True)

    assert result["status"] == "failed"
    assert result["visual_verification"]["status"] == "failed"
    assert "visual verification did not pass" in result["visual_errors"]
    assert "player hidden behind HUD" in result["visual_verification"]["checked"][0]["issues"]
