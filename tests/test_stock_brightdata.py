"""Tests for Bright Data stock media fallback."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from arka.media.stock_brightdata import (
    _extract_json,
    _image_rows_from_payload,
    _video_rows_from_payload,
    api_token,
    fallback_enabled,
    is_configured,
    search_brightdata_images,
    search_brightdata_videos,
)
from arka.media.stock_photos import StockPhoto, _search_source, configured_sources
from arka.media.stock_videos import _search_source_videos, configured_video_sources


@pytest.fixture(autouse=True)
def _clear_brightdata_env(monkeypatch):
    for name in (
        "BRIGHTDATA_API_TOKEN",
        "BRIGHT_DATA_API_KEY",
        "BRIGHTDATA_SERP_ZONE",
        "VIDEO_STOCK_FALLBACK",
        "VIDEO_PHOTO_SOURCES",
        "VIDEO_VIDEO_SOURCES",
    ):
        monkeypatch.delenv(name, raising=False)


def test_api_token_reads_aliases(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "bd-test-token")
    assert api_token() == "bd-test-token"
    assert is_configured() is True


def test_fallback_disabled_when_env_none(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "bd-test-token")
    monkeypatch.setenv("VIDEO_STOCK_FALLBACK", "none")
    assert fallback_enabled() is False


def test_fallback_enabled_by_default_with_token(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "bd-test-token")
    assert fallback_enabled() is True


def test_extract_json_from_serp_payload():
    payload = {
        "images": [
            {
                "title": "Mountain lake",
                "original_image": "https://cdn.example.com/lake.jpg",
                "original_width": 1920,
                "original_height": 1080,
            }
        ]
    }
    parsed = _extract_json(json.dumps(payload))
    rows = _image_rows_from_payload(parsed)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://cdn.example.com/lake.jpg"
    assert rows[0]["width"] == 1920


def test_video_rows_from_payload_finds_mp4():
    payload = {
        "organic": [
            {
                "title": "Ocean clip",
                "link": "https://www.pexels.com/video/ocean-waves-123/",
                "description": "Download https://videos.pexels.com/video-files/42/42.mp4 for preview",
            }
        ]
    }
    rows = _video_rows_from_payload(payload)
    assert any("42.mp4" in row["url"] for row in rows)


def test_search_brightdata_images_mocked(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "bd-test-token")
    payload = {
        "images": [
            {"title": "Desk setup", "original_image": "https://images.example.com/desk.jpg"},
        ]
    }

    with patch("arka.media.stock_brightdata._serp_request", return_value=json.dumps(payload)):
        rows = search_brightdata_images("desk setup", count=3)

    assert len(rows) == 1
    assert rows[0]["url"].endswith("desk.jpg")


def test_search_brightdata_videos_mocked(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "bd-test-token")
    payload = {
        "organic": [
            {
                "title": "City timelapse",
                "link": "https://www.pexels.com/video/city-99/",
                "description": "https://videos.pexels.com/video-files/9/9.mp4",
            }
        ]
    }

    with patch("arka.media.stock_brightdata._serp_request", return_value=json.dumps(payload)):
        rows = search_brightdata_videos("city timelapse", count=2)

    assert rows
    assert any(row["url"].endswith(".mp4") for row in rows)


def test_photo_fallback_chain_includes_brightdata(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "bd-test-token")
    assert "brightdata" in configured_sources()


def test_video_fallback_chain_includes_brightdata(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "bd-test-token")
    assert "brightdata" in configured_video_sources()


def test_stock_photos_use_brightdata_when_primary_empty(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "bd-test-token")
    monkeypatch.setenv("VIDEO_PHOTO_SOURCES", "brightdata")

    fake_rows = [{"url": "https://images.example.com/ai.jpg", "title": "AI desk", "width": 1600, "height": 900}]

    with patch("arka.media.stock_photos.search_brightdata_images", return_value=fake_rows):
        photos = _search_source("brightdata", "ai desk", count=1, orientation="landscape")

    assert len(photos) == 1
    assert isinstance(photos[0], StockPhoto)
    assert photos[0].source == "brightdata"


def test_stock_videos_use_brightdata_when_primary_empty(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "bd-test-token")
    monkeypatch.setenv("VIDEO_VIDEO_SOURCES", "brightdata")

    fake_rows = [{"url": "https://videos.example.com/waves.mp4", "title": "Waves", "duration": 12.0}]

    with patch("arka.media.stock_videos.search_brightdata_videos", return_value=fake_rows):
        videos = _search_source_videos("brightdata", "ocean waves", count=1, orientation="landscape")

    assert len(videos) == 1
    assert videos[0].source == "brightdata"
    assert videos[0].url.endswith(".mp4")


def test_download_brightdata_media_validates_size(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "bd-test-token")
    from arka.media.stock_brightdata import download_brightdata_media

    class FakeResp:
        headers = {"Content-Type": "image/jpeg"}

        def read(self):
            return b"tiny"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        with pytest.raises(RuntimeError, match="too small"):
            download_brightdata_media("https://images.example.com/x.jpg", tmp_path / "x.jpg", kind="image")
