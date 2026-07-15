from arka.routing.symbolic import route_ideate


def test_ideate_route():
    assert route_ideate("ideate on trending open-source AI tools") == "ideate 'on trending open-source AI tools'"
