"""Symbolic-rule games for benchmarking local model accuracy."""
from __future__ import annotations

import argparse
import json


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka play")
    sub = parser.add_subparsers(dest="game", required=True)
    p = sub.add_parser("chess", help="Validate a local model's UCI chess moves")
    p.add_argument("--moves", nargs="+", required=True, help="UCI moves, e.g. e2e4 e7e5")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = chess_benchmark(args.moves)
    except RuntimeError as exc:
        print(exc)
        return 2
    print(json.dumps(result, indent=2) if args.json else f"Chess accuracy: {result['accuracy']:.1%} ({result['legal']}/{result['moves']} legal moves)\nFEN: {result['fen']}")
    return 0 if not result["errors"] else 1
