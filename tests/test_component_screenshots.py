from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from arka.agent.component_screenshots import (
    _boxes_overlap,
    _normalize_url,
    _unique_filename,
    capture,
    discover_components,
    main,
    slugify,
)
from arka.routing.symbolic import route_component_screenshots, route_web_screenshot


class _FakeAttributeItem:
    def __init__(self, attrs: dict[str, str], text: str = "", visible: bool = True, box: dict[str, float] | None = None) -> None:
        self.attrs = attrs
        self.text = text
        self.visible = visible
        self.box = box or {"x": 0, "y": 0, "width": 120, "height": 40}
        self.events: list[tuple] = []

    def is_visible(self) -> bool:
        return self.visible

    def bounding_box(self) -> dict[str, float] | None:
        return self.box

    def get_attribute(self, name: str) -> str | None:
        return self.attrs.get(name)

    def inner_text(self, timeout: int = 500) -> str:
        return self.text

    def scroll_into_view_if_needed(self, timeout: int = 5_000) -> None:
        self.events.append(("scroll", timeout))

    def screenshot(self, *, path: str) -> None:
        Path(path).write_bytes(b"png")
        self.events.append(("screenshot", path))


class _FakeLocator:
    def __init__(self, items: list[_FakeAttributeItem]) -> None:
        self.items = items

    def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> _FakeAttributeItem:
        return self.items[index]


class _FakeFrameLocator:
    def __init__(self, page: "_FakePage") -> None:
        self.page = page

    def locator(self, selector: str) -> _FakeLocator:
        return self.page.locator(selector)


class _FakePage:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.elements: dict[str, list[_FakeAttributeItem]] = {
            "[data-testid]": [
                _FakeAttributeItem({"data-testid": "hero"}, box={"x": 10, "y": 10, "width": 200, "height": 80}),
                _FakeAttributeItem({"data-testid": "footer"}, box={"x": 10, "y": 500, "width": 200, "height": 60}),
            ],
            "button:not([type='hidden'])": [
                _FakeAttributeItem({}, text="Start", box={"x": 300, "y": 20, "width": 90, "height": 36}),
            ],
            "body": [_FakeAttributeItem({})],
        }

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.events.append(("goto", url, wait_until, timeout))

    def wait_for_timeout(self, ms: int) -> None:
        self.events.append(("wait", ms))

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self.elements.get(selector, []))

    def frame_locator(self, selector: str) -> _FakeFrameLocator:
        return _FakeFrameLocator(self)

    def screenshot(self, *, path: str, full_page: bool = False) -> None:
        Path(path).write_bytes(b"full")
        self.events.append(("screenshot", path, full_page))


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self, **kwargs) -> _FakePage:
        self.events = kwargs
        return self.page

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def launch(self) -> _FakeBrowser:
        return _FakeBrowser(_FakePage())


class _FakePlaywright:
    chromium = _FakeChromium()


class _FakePlaywrightManager:
    def __enter__(self) -> _FakePlaywright:
        return _FakePlaywright()

    def __exit__(self, *_args) -> None:
        return None


def test_slugify_and_unique_filename():
    assert slugify("Hero Button!") == "hero-button"
    used: set[str] = set()
    assert _unique_filename("hero", used) == "component-hero.png"
    assert _unique_filename("hero", used) == "component-hero-2.png"


def test_boxes_overlap():
    a = {"x": 0, "y": 0, "width": 100, "height": 100}
    b = {"x": 5, "y": 5, "width": 100, "height": 100}
    c = {"x": 200, "y": 200, "width": 50, "height": 50}
    assert _boxes_overlap(a, b)
    assert not _boxes_overlap(a, c)


def test_normalize_url(tmp_path):
    html = tmp_path / "demo.html"
    html.write_text("<html></html>", encoding="utf-8")
    assert _normalize_url(str(html)).startswith("file://")
    assert _normalize_url("localhost:3000") == "http://localhost:3000"


def test_discover_components_deduplicates_and_names():
    page = _FakePage()
    found = discover_components(page, include_common=True, max_components=10)
    names = {item["name"] for item in found}
    assert "hero" in names
    assert "footer" in names
    assert "start" in names
    assert len(found) == 3


def test_route_component_screenshots():
    routed = route_component_screenshots("screenshot all components on https://localhost:3000")
    assert routed is not None
    assert routed.startswith("component_screenshots ")
    assert "https://localhost:3000" in routed
    assert route_component_screenshots("capture component screenshots for localhost:5173 into ./shots") == (
        "component_screenshots localhost:5173 --output ./shots"
    )


def test_route_component_screenshots_before_web_screenshot():
    cmd = "screenshot all components on https://example.com"
    assert route_component_screenshots(cmd) is not None
    assert "component_screenshots" in route_component_screenshots(cmd)
    assert route_web_screenshot(cmd) is None


def test_capture_writes_manifest(monkeypatch, tmp_path):
    fake_module = types.SimpleNamespace(sync_playwright=lambda: _FakePlaywrightManager())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)

    manifest = capture("http://localhost:3000", str(tmp_path), include_common=True, settle_seconds=0)
    assert Path(manifest["full_page"]).is_file()
    assert manifest["total_discovered"] == 3
    assert manifest["total_captured"] == 3
    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.is_file()
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["url"] == "http://localhost:3000"
    assert all(Path(item["path"]).is_file() for item in saved["components"] if item["status"] == "ok")


def test_capture_rejects_unbounded_settle_time():
    try:
        capture("http://localhost:3000", settle_seconds=61)
    except ValueError as exc:
        assert "between 0 and 60" in str(exc)
    else:
        raise AssertionError("expected settle validation before browser startup")


def test_main_prints_paths(monkeypatch, tmp_path, capsys):
    fake_module = types.SimpleNamespace(sync_playwright=lambda: _FakePlaywrightManager())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)

    code = main(["http://localhost:3000", "--output", str(tmp_path), "--settle", "0"])
    out = capsys.readouterr().out
    assert code == 0
    assert "full-page.png" in out
    assert "manifest.json" in out
