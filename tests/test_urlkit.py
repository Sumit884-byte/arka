"""Tests for offline urlkit helpers."""

from __future__ import annotations

import pytest

from arka.core.urlkit import normalize_payload, parse_payload, repair_links, slugify_payload


def test_parse_payload_basic():
    payload = parse_payload("https://Example.com:443/path?q=1#frag")
    assert payload["host"] == "example.com"
    assert payload["query"]["q"] == "1"
    assert payload["fragment"] == "frag"


def test_normalize_payload_drops_default_port_and_fragment():
    payload = normalize_payload("HTTPS://Example.COM:443/docs/?b=2&a=1#x")
    assert payload["url"].startswith("https://example.com/docs")
    assert "a=1" in payload["url"] and "b=2" in payload["url"]
    assert "#" not in payload["url"]


def test_slugify_payload():
    payload = slugify_payload("Hello, Arka World!")
    assert payload["slug"] == "hello-arka-world"


def test_slugify_requires_text():
    with pytest.raises(ValueError):
        slugify_payload("  ")


def test_repair_links_removes_broken_markdown_links():
    payload = repair_links("See [good](https://example.com/a) and [bad](htp://oops) now.")
    assert payload["kept"] == ["https://example.com/a"]
    assert "bad" in payload["text"]
    assert "htp://oops" in payload["removed"][0]
