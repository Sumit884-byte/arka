"""Auditable, reproducible math scripts for research calculations."""
from __future__ import annotations
import argparse
import ast
import math
from pathlib import Path

SAFE = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
SAFE.update({"abs": abs, "round": round, "pow": pow, "sum": sum, "min": min, "max": max})

def evaluate(expression: str) -> object:
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expression, ast.Constant, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.Call, ast.Name, ast.Load, ast.Tuple, ast.List)):
            raise ValueError("only safe numeric expressions are allowed")
        if isinstance(node, ast.Name) and node.id not in SAFE:
            raise ValueError(f"unknown or unsafe name: {node.id}")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in SAFE):
            raise ValueError("unsafe function call")
    return eval(compile(tree, "<research-math>", "eval"), {"__builtins__": {}}, SAFE)

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run and save a reproducible safe math script")
    p.add_argument("expression")
    p.add_argument("--output", default="research_math.py")
    args = p.parse_args(argv)
    try:
        result = evaluate(args.expression)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError) as exc:
        p.error(str(exc))
    script = Path(args.output).expanduser()
    script.write_text(f"import math\nprint({args.expression!r})\nprint({args.expression})\n", encoding="utf-8")
    print(f"Result: {result}\nScript: {script}")
    return 0
