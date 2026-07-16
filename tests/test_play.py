from arka.routing.symbolic import route_play


def test_route_play():
    assert route_play("benchmark chess e2e4 e7e5") == "play chess --moves e2e4 e7e5"


def test_route_natural_language_car_battle():
    assert route_play("make two AI cars with realistic physics battle") == "play battle make two AI cars with realistic physics battle"


def test_car_battle_is_deterministic():
    from arka.agent.play import battle_simulation

    first = battle_simulation(["aggressive", "defensive"], steps=40, seed=7)
    second = battle_simulation(["aggressive", "defensive"], steps=40, seed=7)
    assert first == second
    assert first["game"] == "car_battle"


def test_battle_parses_model_assignments():
    from arka.agent.play import parse_battle_request

    parsed = parse_battle_request("battle cyber truck with gemini vs ferrari with chatgpt")
    assert parsed["agents"] == ["cyber truck", "ferrari"]
    assert parsed["controllers"] == {"cyber truck": "gemini", "ferrari": "chatgpt"}


def test_groups_compete_pairwise():
    from arka.agent.play import compete_permutations

    result = compete_permutations({"society": ["aggressive"], "team": ["defensive"]}, steps=10)
    assert result["game"] == "agent_tournament"
    assert len(result["matches"]) == 1
    assert set(result["ranking"]) == {"society", "team"}


def test_chess_benchmark_requires_optional_dependency():
    from arka.agent.play import chess_benchmark
    try:
        result = chess_benchmark(["e2e4", "e7e5"])
    except RuntimeError as exc:
        assert "python-chess" in str(exc)
    else:
        assert result["legal"] == 2


def test_route_play_tournament():
    assert route_play("let agent societies compete in a battle") == (
        "play tournament --group society=agent-1,agent-2 --group team=agent-3,agent-4"
    )


def test_parse_battle_request_agent_count_and_steps():
    from arka.agent.play import parse_battle_request

    parsed = parse_battle_request("make 4 ai cars battle with realistic physics for 50 steps")
    assert parsed["agents"] == ["aggressive", "defensive", "agent-3", "agent-4"]
    assert parsed["steps"] == 50
    assert parsed["physics"] == "realistic"
