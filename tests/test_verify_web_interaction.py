"""Tests for verify_web_interaction — parsing, routing, MCP, and Playwright."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from arka.agent.verify_web_interaction import (
    build_interaction_plan,
    build_vision_verify_prompt,
    nl_to_argv,
    parse_code_context,
    parse_spec,
    parse_vision_verdict,
    run_vision_verification,
    verify,
    verify_screenshot_with_vision,
    vision_enabled,
)
from arka.integrations.mcp_server import _handle_arka_verify_web_interaction, _mcp_disabled_skill_heads
from arka.routing.symbolic import route_verify_web_interaction


class _FakeLocatorItem:
    def __init__(self, page: "_FakePage", selector: str, index: int = 0) -> None:
        self.page = page
        self.selector = selector
        self.index = index

    def click(self, timeout: int = 10_000) -> None:
        self.page.events.append(("click", self.selector, timeout))

    def fill(self, value: str) -> None:
        self.page.events.append(("fill", self.selector, value))

    def wait_for(self, *, state: str, timeout: int = 10_000) -> None:
        self.page.events.append(("wait_for", self.selector, state, timeout))


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> _FakeLocatorItem:
        return _FakeLocatorItem(self.page, self.selector)

    def click(self, timeout: int = 10_000) -> None:
        self.page.events.append(("click", self.selector, timeout))

    def fill(self, value: str) -> None:
        self.page.events.append(("fill", self.selector, value))

    def wait_for(self, *, state: str, timeout: int = 10_000) -> None:
        self.page.events.append(("wait_for", self.selector, state, timeout))


class _FakeGetBy:
    def __init__(self, page: "_FakePage", kind: str, value: str) -> None:
        self.page = page
        self.kind = kind
        self.value = value

    @property
    def first(self) -> "_FakeGetBy":
        return self

    def click(self, timeout: int = 10_000) -> None:
        self.page.events.append(("click_by", self.kind, self.value, timeout))

    def wait_for(self, *, state: str, timeout: int = 10_000) -> None:
        self.page.events.append(("wait_for_by", self.kind, self.value, state, timeout))


class _FakeResponse:
    status = 200


class _FakePage:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on(self, *_args) -> None:
        return None

    def goto(self, url: str, *, wait_until: str, timeout: int) -> _FakeResponse:
        self.events.append(("goto", url, wait_until, timeout))
        return _FakeResponse()

    def wait_for_timeout(self, ms: int) -> None:
        self.events.append(("wait", ms))

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def get_by_text(self, text: str, exact: bool = False) -> _FakeGetBy:
        return _FakeGetBy(self, "text", text)

    def get_by_role(self, role: str, name: str | None = None) -> _FakeGetBy:
        return _FakeGetBy(self, "role", f"{role}:{name}")

    def title(self) -> str:
        return "Demo App"

    def screenshot(self, *, path: str | None = None, full_page: bool = False) -> None:
        if path:
            Path(path).write_bytes(b"fake-png")
            self.events.append(("screenshot", Path(path).name, full_page))


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


SAMPLE_COMPONENT = """
export function LoginForm() {
  return (
    <form name="login">
      <input data-testid="email-input" name="email" />
      <button data-testid="submit-btn">Sign in</button>
      <a href="/register">Create account</a>
    </form>
  );
}
"""

SAMPLE_SPEC = """
test('login flow', async ({ page }) => {
  await page.goto('http://127.0.0.1:3000/login');
  await page.fill('[data-testid="email-input"]', 'user@example.com');
  await page.click('[data-testid="submit-btn"]');
  await expect(page.getByText('Welcome')).toBeVisible();
});
"""


class TestCodeParsing:
    def test_parse_code_context(self, tmp_path: Path) -> None:
        path = tmp_path / "LoginForm.tsx"
        path.write_text(SAMPLE_COMPONENT, encoding="utf-8")
        parsed = parse_code_context(path)
        assert '[data-testid="email-input"]' in parsed["selectors"]
        assert '[data-testid="submit-btn"]' in parsed["selectors"]
        assert "Sign in" in parsed["texts"]
        assert "/register" in parsed["hrefs"]

    def test_parse_spec(self, tmp_path: Path) -> None:
        path = tmp_path / "login.spec.ts"
        path.write_text(SAMPLE_SPEC, encoding="utf-8")
        steps = parse_spec(path)
        actions = [step["action"] for step in steps]
        assert "goto" in actions
        assert "fill" in actions
        assert "click" in actions
        assert "assert_text_visible" in actions

    def test_build_interaction_plan(self, tmp_path: Path) -> None:
        component = tmp_path / "LoginForm.tsx"
        component.write_text(SAMPLE_COMPONENT, encoding="utf-8")
        spec = tmp_path / "login.spec.ts"
        spec.write_text(SAMPLE_SPEC, encoding="utf-8")
        plan = build_interaction_plan(
            "http://127.0.0.1:3000",
            context=parse_code_context(component),
            spec_steps=parse_spec(spec),
        )
        assert plan[0]["action"] == "goto"
        assert any(step.get("selector") == '[data-testid="submit-btn"]' for step in plan)
        assert any(step.get("text") == "Sign in" for step in plan)


class TestRouting:
    def test_route_verify_with_url(self) -> None:
        routed = route_verify_web_interaction(
            "verify website interactions on https://example.com with component.tsx"
        )
        assert routed is not None
        assert routed.startswith("verify_web_interaction check ")
        assert "https://example.com" in routed

    def test_route_test_ui_against_component(self) -> None:
        routed = route_verify_web_interaction("test ui against component.tsx on http://localhost:3000")
        assert routed is not None
        assert "verify_web_interaction" in routed

    def test_route_skips_generic_browser_check(self) -> None:
        assert route_verify_web_interaction("check browser ui at http://localhost:3000") is None

    def test_nl_to_argv(self) -> None:
        argv = nl_to_argv("verify website interactions on https://example.com with src/Button.tsx")
        assert argv[0] == "check"
        assert "https://example.com" in argv
        assert "--context" in argv

    def test_nl_to_argv_vllm(self) -> None:
        argv = nl_to_argv("verify website interactions with vllm on https://example.com")
        assert "--vllm-verify" in argv


class TestVisionVerification:
    def test_parse_vision_verdict_json(self) -> None:
        raw = json.dumps(
            {
                "pass": True,
                "expected_elements_visible": ["Sign in"],
                "missing_elements": [],
                "interaction_outcome": "Login form visible",
                "layout_issues": [],
                "errors_visible": [],
                "confidence": 0.92,
                "reason": "Matches LoginForm intent",
            }
        )
        verdict = parse_vision_verdict(raw)
        assert verdict["pass"] is True
        assert "Sign in" in verdict["expected_elements_visible"]
        assert verdict["confidence"] == 0.92

    def test_parse_vision_verdict_fails_on_missing_elements(self) -> None:
        verdict = parse_vision_verdict(
            '{"pass": true, "missing_elements": ["submit button"], "layout_issues": [], "errors_visible": []}'
        )
        assert verdict["pass"] is False

    def test_build_vision_verify_prompt_includes_context(self, tmp_path: Path) -> None:
        component = tmp_path / "LoginForm.tsx"
        component.write_text(SAMPLE_COMPONENT, encoding="utf-8")
        context = parse_code_context(component)
        prompt = build_vision_verify_prompt(
            context=context,
            context_sources=[str(component)],
            step={"action": "assert_text", "text": "Sign in"},
            page_title="Demo App",
            current_url="http://127.0.0.1:3000/login",
        )
        assert "Sign in" in prompt
        assert "LoginForm.tsx" in prompt
        assert '"pass"' in prompt

    def test_verify_screenshot_with_vision_mocked(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        shot = tmp_path / "step.png"
        shot.write_bytes(b"fake-png")
        component = tmp_path / "LoginForm.tsx"
        component.write_text(SAMPLE_COMPONENT, encoding="utf-8")
        context = parse_code_context(component)

        def fake_describe(source: str, prompt: str) -> str:
            assert source == str(shot)
            assert "Sign in" in prompt
            return json.dumps(
                {
                    "pass": True,
                    "expected_elements_visible": ["Sign in"],
                    "missing_elements": [],
                    "interaction_outcome": "Login form rendered",
                    "layout_issues": [],
                    "errors_visible": [],
                    "confidence": 0.95,
                    "reason": "Matches component intent",
                }
            )

        monkeypatch.setattr("arka.vision.describe.describe_source", fake_describe)
        verdict = verify_screenshot_with_vision(
            str(shot),
            context=context,
            context_sources=[str(component)],
            step={"action": "assert_text", "text": "Sign in"},
            page_title="Demo App",
            current_url="http://127.0.0.1:3000",
            vision_backend="vllm",
        )
        assert verdict["pass"] is True
        assert verdict["vision_backend"] == "vllm"

    def test_run_vision_verification_aggregates_failures(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        shot = tmp_path / "bad.png"
        shot.write_bytes(b"fake-png")

        def fake_describe(_source: str, _prompt: str) -> str:
            return json.dumps(
                {
                    "pass": False,
                    "expected_elements_visible": [],
                    "missing_elements": ["Sign in"],
                    "interaction_outcome": "Empty page",
                    "layout_issues": ["header overlap"],
                    "errors_visible": ["404 Not Found"],
                    "confidence": 0.8,
                    "reason": "Expected login UI missing",
                }
            )

        monkeypatch.setattr("arka.vision.describe.describe_source", fake_describe)
        result = run_vision_verification(
            screenshots=[{"path": str(shot), "step": {"action": "goto"}, "index": 1}],
            context={"selectors": [], "texts": ["Sign in"], "routes": [], "hrefs": []},
            context_sources=[],
            page_title="Demo App",
            current_url="http://127.0.0.1:3000",
            vision_backend="vllm",
        )
        assert result["enabled"] is True
        assert result["pass"] is False
        assert result["failed"] == 1

    def test_vision_enabled_respects_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARKA_WEB_VERIFY_VISION", raising=False)
        monkeypatch.setattr(
            "arka.agent.verify_web_interaction._vision_backend_ready",
            lambda _name: False,
        )
        assert vision_enabled(explicit=None, vllm_verify=False) is False
        monkeypatch.setenv("ARKA_WEB_VERIFY_VISION", "1")
        assert vision_enabled(explicit=None, vllm_verify=False) is True


def test_verify_headless_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    component = tmp_path / "LoginForm.tsx"
    component.write_text(SAMPLE_COMPONENT, encoding="utf-8")
    page = _FakePage()
    browser = _install_fake_playwright(monkeypatch, page)
    monkeypatch.chdir(tmp_path)

    result = verify(
        "http://127.0.0.1:3000",
        context_path=str(component),
        headless=True,
    )

    assert result["ok"] is True
    assert result["url"] == "http://127.0.0.1:3000"
    assert result["title"] == "Demo App"
    assert result["headless"] is True
    assert browser.closed is True
    assert any(event[0] == "goto" for event in page.events)


def test_verify_mcp_parse_action() -> None:
    payload = json.loads(
        _handle_arka_verify_web_interaction(
            {"action": "parse", "text": "verify website interactions on https://example.com with Login.tsx"}
        )
    )
    assert payload["argv"][0] == "check"
    assert "https://example.com" in payload["argv"]


def test_verify_mcp_check_headless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    component = tmp_path / "LoginForm.tsx"
    component.write_text(SAMPLE_COMPONENT, encoding="utf-8")
    page = _FakePage()
    _install_fake_playwright(monkeypatch, page)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARKA_WEB_VERIFY_VISION", "0")

    payload = json.loads(
        _handle_arka_verify_web_interaction(
            {
                "action": "check",
                "url": "http://127.0.0.1:3000",
                "context": str(component),
                "headless": True,
                "no_vision": True,
            }
        )
    )
    assert payload["ok"] is True


def test_verify_mcp_check_with_vision(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    component = tmp_path / "LoginForm.tsx"
    component.write_text(SAMPLE_COMPONENT, encoding="utf-8")
    page = _FakePage()
    _install_fake_playwright(monkeypatch, page)
    monkeypatch.chdir(tmp_path)

    def fake_describe(_source: str, _prompt: str) -> str:
        return json.dumps(
            {
                "pass": True,
                "expected_elements_visible": ["Sign in"],
                "missing_elements": [],
                "interaction_outcome": "ok",
                "layout_issues": [],
                "errors_visible": [],
                "confidence": 0.9,
                "reason": "ok",
            }
        )

    monkeypatch.setattr("arka.vision.describe.describe_source", fake_describe)
    payload = json.loads(
        _handle_arka_verify_web_interaction(
            {
                "action": "check",
                "url": "http://127.0.0.1:3000",
                "context": str(component),
                "headless": True,
                "vision": True,
                "vision_backend": "vllm",
            }
        )
    )
    assert payload["ok"] is True
    assert payload["vision"]["enabled"] is True


def test_verify_mcp_headed_requires_allow_browser() -> None:
    with pytest.raises(ValueError, match="allow_browser"):
        _handle_arka_verify_web_interaction(
            {"action": "check", "url": "http://127.0.0.1:3000", "headed": True}
        )


def test_mcp_disabled_by_default() -> None:
    assert "verify_web_interaction" in _mcp_disabled_skill_heads()


def test_main_parse_subcommand(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    from arka.agent.verify_web_interaction import main

    component = tmp_path / "LoginForm.tsx"
    component.write_text(SAMPLE_COMPONENT, encoding="utf-8")
    code = main(["parse", "--context", str(component), "--url", "http://127.0.0.1:3000", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert payload["plan"][0]["action"] == "goto"
