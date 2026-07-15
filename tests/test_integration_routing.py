from arka.routing.symbolic import route_offline_extras
from arka.agent.integration_setup import ALIASES, PROVIDERS


def test_routes_natural_language_integration_setup():
    assert route_offline_extras("set up Serper integration") == "integration setup serper"
    assert route_offline_extras("show available integrations") == "integration list"
    assert route_offline_extras("connect to Stripe") == "integration setup stripe"
    assert route_offline_extras("configure Notion") == "integration setup notion"
    assert route_offline_extras("connect to PostHog") == "integration setup posthog"


def test_every_registered_provider_has_a_nl_route():
    for provider in PROVIDERS:
        assert route_offline_extras(f"connect to {provider}") == f"integration setup {provider}"


def test_every_provider_alias_has_a_nl_route():
    for alias, provider in ALIASES.items():
        assert route_offline_extras(f"connect to {alias}") == f"integration setup {alias}"
