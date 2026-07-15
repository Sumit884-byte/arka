"""Reproducible bounded optimization inspired by island/evolutionary methods."""
from __future__ import annotations
import argparse
import ast
import json
import random

def objective(expr: str, x: float) -> float:
    tree = ast.parse(expr, mode="eval")
    if any(isinstance(n, (ast.Call, ast.Attribute, ast.Import, ast.Subscript)) for n in ast.walk(tree)):
        raise ValueError("objective must be a simple arithmetic expression using x")
    return float(eval(compile(tree, "<objective>", "eval"), {"__builtins__": {}}, {"x": x}))

def optimize(expr: str, low: float, high: float, *, iterations: int = 100, seed: int = 0) -> dict:
    if low >= high or not 1 <= iterations <= 10000:
        raise ValueError("invalid bounds or iteration count")
    rng = random.Random(seed)
    population = [rng.uniform(low, high) for _ in range(12)]
    for _ in range(iterations):
        population.sort(key=lambda v: objective(expr, v))
        for i in range(6, 12):
            candidate = min(high, max(low, population[i - 6] + rng.uniform(-1, 1) * (high - low) / (2 + _)))
            if objective(expr, candidate) < objective(expr, population[i]):
                population[i] = candidate
    best = min(population, key=lambda v: objective(expr, v))
    return {"x": best, "value": objective(expr, best), "seed": seed, "iterations": iterations}

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Optimize a bounded scalar objective")
    p.add_argument("expression", help="arithmetic expression using x, e.g. (x-3)**2")
    p.add_argument("--bounds", default="-10,10")
    p.add_argument("--iterations", type=int, default=100)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        low, high = (float(v) for v in args.bounds.split(",", 1))
        result = optimize(args.expression, low, high, iterations=args.iterations, seed=args.seed)
    except (ValueError, SyntaxError) as exc:
        p.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"Best x: {result['x']}\nObjective: {result['value']}")
    return 0
