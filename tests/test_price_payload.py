"""Tests for price_sources MCP payload helpers."""

from __future__ import annotations

from arka.agent.price_sources import parse_price_payload, sources_payload


def test_sources_payload_india_default():
    payload = sources_payload(region="india")
    assert payload["region"] == "india"
    assert payload["count"] >= 3
    ids = {s["id"] for s in payload["sources"]}
    assert "amazon_in" in ids


def test_sources_payload_apple_product():
    payload = sources_payload(region="india", product="iPhone 16 Pro")
    assert payload["category"] == "apple"
    assert any(s["id"].startswith("apple") for s in payload["sources"])


def test_parse_price_payload():
    payload = parse_price_payload("MacBook Air M3 price in India")
    assert payload["region"] == "india"
    assert "macbook" in payload["product"].lower()
