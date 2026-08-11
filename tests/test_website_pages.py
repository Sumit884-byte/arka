"""Tests for website_pages IA bias and routing."""

from arka.core.website_pages import (
    compact_rule,
    context_for,
    is_website_goal,
    read_guide,
    should_include,
    status,
    wants_page_plan,
)
from arka.routing.symbolic import route_website_pages


def test_compact_rule_enabled():
    assert "sitemap" in compact_rule().lower()


def test_is_website_goal():
    assert is_website_goal("build a marketing website for my app")
    assert is_website_goal("how should I divide this content into pages")
    assert is_website_goal("plan the sitemap for a docs site")
    assert not is_website_goal("what is 2+2")


def test_wants_page_plan():
    assert wants_page_plan("organize my landing page content into pages")
    assert wants_page_plan("create a website for my startup")
    assert not wants_page_plan("fix the navbar color")


def test_should_include_auto_mode():
    assert should_include("build a multi-page website") is True
    assert should_include("random question") is False


def test_read_guide_has_golden_rule():
    guide = read_guide(max_chars=8000)
    assert "Golden rule" in guide or "primary job" in guide.lower()


def test_context_for_website_goal():
    ctx = context_for("plan sitemap for SaaS docs site")
    assert "sitemap" in ctx.lower() or "Website pages guide" in ctx


def test_status_has_guide():
    st = status()
    assert st["enabled"] is True
    assert st["guide_path"]


def test_route_website_pages():
    hit = route_website_pages("organize this content into website pages")
    assert hit is not None
    assert hit.startswith("website_pages plan")


def test_route_website_pages_skips_unrelated():
    assert route_website_pages("what is the weather") is None
