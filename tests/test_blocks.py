from arka.agent.blocks import BLOCKS, create_block, infer_block_name, render
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
    assert route_offline_extras("show crypto wallet block") == "blocks show web3_wallet"
    assert route_offline_extras("create a crypto wallet page and save it as a block").startswith("blocks create ")


def test_create_crypto_wallet_page_block(tmp_path):
    prompt = "create a crypto wallet page and save it as a block"
    assert infer_block_name(prompt) == "web3_wallet"
    target = create_block(prompt, out=str(tmp_path / "wallet.md"))
    text = target.read_text()
    assert "Arka block: web3_wallet" in text
    assert "Source prompt" in text
    assert "chain-id checks" in text


def test_catalog_covers_auth_payments_and_backend():
    assert len(BLOCKS) >= 10
    assert {BLOCKS[name]["kind"] for name in BLOCKS} >= {"auth", "payments", "backend"}
    assert route_offline_extras("show password reset block") == "blocks show auth_password_reset"
