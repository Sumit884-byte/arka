"""Symbolic-rule games for benchmarking local model accuracy."""
from __future__ import annotations

import argparse
import itertools
import json
import random
import re


def chess_benchmark(moves: list[str]) -> dict[str, object]:
    try:
        import chess
    except ImportError as exc:
        raise RuntimeError("chess benchmark requires python-chess: pip install python-chess") from exc
    board = chess.Board()
    legal = 0
    errors = []
    for move in moves:
        try:
            parsed = chess.Move.from_uci(move)
            if parsed not in board.legal_moves:
                errors.append({"move": move, "error": "illegal move", "fen": board.fen()})
                continue
            board.push(parsed)
            legal += 1
        except ValueError:
            errors.append({"move": move, "error": "invalid UCI move", "fen": board.fen()})
    return {"game": "chess", "moves": len(moves), "legal": legal, "accuracy": legal / len(moves) if moves else 0.0, "errors": errors, "fen": board.fen(), "outcome": board.outcome().result() if board.outcome() else None}


def battle_simulation(
    agents: list[str], *, steps: int = 300, seed: int = 0, physics: str = "realistic", controllers: dict[str, str] | None = None
) -> dict[str, object]:
    """Run a deterministic, dependency-free arena battle for model policies.

    Agents are currently baseline policies (aggressive/defensive/random), which
    makes this useful even offline.  A model adapter can replace ``action``
    later without changing the rules or scoring contract.
    """
    if not agents:
        raise ValueError("at least two agents are required")
    if len(agents) < 2:
        raise ValueError("a battle needs at least two agents")
    if steps < 1 or steps > 10000:
        raise ValueError("steps must be between 1 and 10000")
    rng = random.Random(seed)
    state = [{"name": name, "x": float(i * 20), "v": 0.0, "health": 100.0} for i, name in enumerate(agents)]
    for _ in range(steps):
        alive = [car for car in state if car["health"] > 0]
        if len(alive) <= 1:
            break
        for car in alive:
            target = min((other for other in alive if other is not car), key=lambda other: abs(other["x"] - car["x"]))
            direction = 1 if target["x"] > car["x"] else -1
            policy = car["name"].lower()
            throttle = 1.0 if "aggressive" in policy else 0.65 if "defensive" in policy else rng.uniform(0.4, 1.0)
            acceleration = direction * throttle * (2.2 if physics == "realistic" else 3.0)
            car["v"] = max(-12.0, min(12.0, car["v"] * 0.94 + acceleration))
            car["x"] += car["v"] * 0.1
            if abs(car["x"] - target["x"]) < 2.5 and abs(car["v"] - target["v"]) > 4:
                target["health"] -= min(18.0, abs(car["v"] - target["v"]) * 1.4)
    alive = [car for car in state if car["health"] > 0]
    winner = max(alive, key=lambda car: car["health"]) if alive else max(state, key=lambda car: car["health"])
    for car in state:
        car["x"] = round(car["x"], 3)
        car["v"] = round(car["v"], 3)
        car["health"] = round(max(0.0, car["health"]), 3)
    return {"game": "car_battle", "physics": physics, "steps": steps, "seed": seed, "winner": winner["name"], "controllers": controllers or {}, "agents": state}


def parse_battle_request(text: str) -> dict[str, object]:
    """Extract a safe battle configuration from natural language."""
    steps_match = re.search(r"\b(?:for|within)\s+(\d+)\s+(?:steps|turns|ticks)\b", text, re.I)
    assignments = re.findall(r"\b([a-z][a-z0-9 -]{1,30}?)\s+with\s+([a-z][a-z0-9._-]{1,30}?)(?=\s+(?:vs|versus|and)\b|[,;]|$)", text, re.I)
    controllers = {}
    for vehicle, model in assignments:
        clean_vehicle = re.sub(r"(?i)^(?:battle|fight)\s+", "", vehicle).strip()
        clean_vehicle = re.sub(r"(?i)^(?:vs|versus|and)\s+", "", clean_vehicle).strip()
        controllers[clean_vehicle] = model.strip()
    count_match = re.search(r"\b(\d+)\s+(?:ai\s+)?(?:cars?|agents?|vehicles?)\b", text, re.I)
    if assignments:
        names = list(controllers)
        return {"agents": names, "controllers": controllers, "steps": int(steps_match.group(1)) if steps_match else 300, "physics": "realistic" if re.search(r"realistic|physics", text, re.I) else "arcade"}
    count = max(2, min(8, int(count_match.group(1)))) if count_match else 2
    names = ["aggressive" if i == 0 else "defensive" if i == 1 else f"agent-{i + 1}" for i in range(count)]
    return {"agents": names, "controllers": {}, "steps": int(steps_match.group(1)) if steps_match else 300, "physics": "realistic" if re.search(r"realistic|physics", text, re.I) else "arcade"}


def compete_permutations(groups: dict[str, list[str]], *, steps: int = 300, seed: int = 0, physics: str = "realistic") -> dict[str, object]:
    """Run every unique group matchup, useful for societies, teams, or hybrids."""
    if len(groups) < 2:
        raise ValueError("at least two groups are required")
    names = list(groups)
    matches = []
    for index, (left, right) in enumerate(itertools.combinations(names, 2)):
        roster = groups[left] + groups[right]
        result = battle_simulation(roster, steps=steps, seed=seed + index, physics=physics)
        matches.append({"left": left, "right": right, "winner": result["winner"], "agents": result["agents"]})
    wins = {name: 0 for name in names}
    for match in matches:
        for name, roster in groups.items():
            if match["winner"] in roster:
                wins[name] += 1
    return {"game": "agent_tournament", "groups": groups, "matches": matches, "wins": wins, "ranking": sorted(wins, key=wins.get, reverse=True), "physics": physics, "steps": steps}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka play")
    sub = parser.add_subparsers(dest="game", required=True)
    p = sub.add_parser("chess", help="Validate a local model's UCI chess moves")
    p.add_argument("--moves", nargs="+", required=True, help="UCI moves, e.g. e2e4 e7e5")
    p.add_argument("--json", action="store_true")
    b = sub.add_parser("battle", help="Run a generalized deterministic agent battle")
    b.add_argument("description", nargs="*", help="natural-language battle description")
    b.add_argument("--agents", nargs="+", default=None)
    b.add_argument("--models", nargs="+", metavar="VEHICLE=MODEL", default=None, help="assign a model/controller to each vehicle")
    b.add_argument("--steps", type=int, default=None)
    b.add_argument("--physics", choices=("realistic", "arcade"), default=None)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--json", action="store_true")
    t = sub.add_parser("tournament", help="Run all pairwise society/team permutations")
    t.add_argument("--group", action="append", required=True, metavar="NAME=AGENT,AGENT")
    t.add_argument("--steps", type=int, default=300)
    t.add_argument("--physics", choices=("realistic", "arcade"), default="realistic")
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.game == "chess":
            result = chess_benchmark(args.moves)
        elif args.game == "tournament":
            groups = {item.split("=", 1)[0]: [a for a in item.split("=", 1)[1].split(",") if a] for item in args.group if "=" in item}
            result = compete_permutations(groups, steps=args.steps, seed=args.seed, physics=args.physics)
        else:
            parsed = parse_battle_request(" ".join(args.description))
            controllers = dict(parsed["controllers"])
            controllers.update(dict(item.split("=", 1) for item in (args.models or []) if "=" in item))
            result = battle_simulation(args.agents or parsed["agents"], steps=args.steps or parsed["steps"], physics=args.physics or parsed["physics"], seed=args.seed, controllers=controllers)
    except RuntimeError as exc:
        print(exc)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.game == "chess":
        print(f"Chess accuracy: {result['accuracy']:.1%} ({result['legal']}/{result['moves']} legal moves)\nFEN: {result['fen']}")
    elif args.game == "tournament":
        print("Ranking: " + " > ".join(result["ranking"]))
    else:
        print(f"Winner: {result['winner']} ({result['steps']} steps, {result['physics']} physics)")
    return 0 if args.game in ("battle", "tournament") or not result["errors"] else 1
