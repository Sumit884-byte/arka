from arka.agent.blocks import BLOCKS, render
from arka.routing.symbolic import route_offline_extras


def test_block_includes_stack_and_security_notes():
    text = render("payments_stripe")
    assert "Recommended stack" in text
    assert "webhook signatures" in text
    assert "Production readiness gates" in text
    assert "STRIPE_SECRET_KEY" in text


def test_blocks_route():
    assert route_offline_extras("show reusable login blocks") == "blocks show auth_login"
    assert route_offline_extras("list available app blocks") == "blocks list"


def test_catalog_covers_auth_payments_and_backend():
    assert len(BLOCKS) >= 10
    assert {BLOCKS[name]["kind"] for name in BLOCKS} >= {"auth", "payments", "backend"}
    assert route_offline_extras("show password reset block") == "blocks show auth_password_reset"
