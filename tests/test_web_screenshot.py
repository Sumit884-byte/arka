from arka.agent.web_screenshot import VIEWPORTS, review
from arka.routing.symbolic import route_web_screenshot


def test_viewport_presets():
    assert VIEWPORTS["pc"] == (1440, 900)
    assert VIEWPORTS["tablet"] == (834, 1112)
    assert VIEWPORTS["mobile"] == (390, 844)


def test_route_web_screenshot():
    assert route_web_screenshot("capture screenshots of https://example.com on mobile") == "web_screenshot https://example.com --viewport mobile"


def test_temporary_output_is_unique_and_under_tempdir():
    from pathlib import Path
    from arka.agent.web_screenshot import temporary_output

    first, second = temporary_output(), temporary_output()
    assert first != second
    assert Path(first).is_dir() and Path(second).is_dir()


def test_review_prompts(tmp_path):
    (tmp_path / "website-pc.png").write_bytes(b"png")
    prompts = review(str(tmp_path))
    assert prompts and "missing responsive" in prompts[0]


def test_review_preserves_good_viewports(tmp_path):
    for mode in ("pc", "tablet", "mobile"):
        (tmp_path / f"website-{mode}.png").write_bytes(b"png")
    prompts = review(str(tmp_path))
    assert any("preserving modes" in prompt for prompt in prompts)
    assert "button order" in prompts[0]


def test_capture_rejects_unbounded_settle_time():
    from arka.agent.web_screenshot import capture

    try:
        capture("http://localhost:5174", settle_seconds=61)
    except ValueError as exc:
        assert "between 0 and 60" in str(exc)
    else:
        raise AssertionError("expected settle validation before browser startup")
