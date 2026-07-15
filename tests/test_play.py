from arka.routing.symbolic import route_play


def test_route_play():
    assert route_play("benchmark chess e2e4 e7e5") == "play chess --moves e2e4 e7e5"


def test_chess_benchmark_requires_optional_dependency():
    from arka.agent.play import chess_benchmark
    try:
        result = chess_benchmark(["e2e4", "e7e5"])
    except RuntimeError as exc:
        assert "python-chess" in str(exc)
    else:
        assert result["legal"] == 2
