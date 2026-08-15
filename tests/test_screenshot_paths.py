from __future__ import annotations

from datetime import datetime
from pathlib import Path

from arka.core.screenshot_paths import (
    docs_screenshot_context,
    latest_screenshot,
    list_screenshots,
    parse_screenshot_timestamp,
    resolve_screenshot_output,
    screenshot_path,
    screenshot_timestamp,
    slugify_prefix,
)


def test_screenshot_timestamp_format():
    when = datetime(2026, 8, 14, 22, 15, 30)
    assert screenshot_timestamp(when) == "20260814-221530"


def test_slugify_prefix():
    assert slugify_prefix("Verify Step!") == "verify-step"
    assert slugify_prefix("") == "screenshot"


def test_screenshot_path_pattern(tmp_path):
    when = datetime(2026, 8, 14, 22, 15, 30)
    path = screenshot_path("verify", tmp_path, when=when)
    assert path.parent == tmp_path
    assert path.name == "verify-20260814-221530.png"
    assert parse_screenshot_timestamp(path) == when


def test_screenshot_path_avoids_same_second_collision(tmp_path):
    when = datetime(2026, 8, 14, 22, 15, 30)
    first = screenshot_path("verify", tmp_path, when=when)
    first.write_bytes(b"1")
    second = screenshot_path("verify", tmp_path, when=when)
    assert second.name == "verify-20260814-221530-02.png"


def test_resolve_screenshot_output_directory_and_file(tmp_path):
    out_dir = tmp_path / "shots"
    path = resolve_screenshot_output(str(out_dir), prefix="browser-check")
    assert path.parent == out_dir
    assert path.name.startswith("browser-check-")

    explicit = resolve_screenshot_output(str(tmp_path / "demo.png"), prefix="ignored")
    assert explicit.parent == tmp_path
    assert explicit.name.startswith("demo-")


def test_latest_screenshot_sorts_by_timestamp_suffix(tmp_path):
    older = tmp_path / "verify-20260814-120000.png"
    newer = tmp_path / "verify-20260814-130000.png"
    legacy = tmp_path / "verify.png"
    for path in (older, newer, legacy):
        path.write_bytes(b"x")
    assert latest_screenshot(tmp_path, prefix="verify") == newer
    assert latest_screenshot(tmp_path) == newer


def test_list_screenshots_prefix_filter(tmp_path):
    (tmp_path / "website-pc-20260814-100000.png").write_bytes(b"x")
    (tmp_path / "website-mobile-20260814-110000.png").write_bytes(b"x")
    (tmp_path / "other-20260814-120000.png").write_bytes(b"x")
    mobile = list_screenshots(tmp_path, prefix="website-mobile")
    assert len(mobile) == 1
    assert mobile[0].name.startswith("website-mobile-")


def test_docs_screenshot_context(tmp_path, monkeypatch):
    monkeypatch.setenv("ARKA_SCREENSHOT_DIR", str(tmp_path))
    (tmp_path / "browser-check-20260814-221530.png").write_bytes(b"x")
    text = docs_screenshot_context(limit=3)
    assert "browser-check-20260814-221530.png" in text
    assert "Primary image" in text
