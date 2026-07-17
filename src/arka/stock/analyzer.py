"""Generalized, source-grounded OHLCV analyzer for Arka."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def analyze(path: Path) -> dict:
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    close_key = next((key for key in rows[0] if key.lower() in {"close", "adj close", "price"}), "") if rows else ""
    values = [float(row[close_key]) for row in rows if row.get(close_key)] if close_key else []
    change = ((values[-1] / values[0]) - 1) if len(values) > 1 and values[0] else None
    return {"source": str(path), "rows": len(rows), "close_column": close_key or None, "latest_close": values[-1] if values else None, "return": change, "trend": "up" if change is not None and change > 0 else "down" if change is not None and change < 0 else "unknown", "disclaimer": "Descriptive analysis only; not financial advice."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka stock-analyze")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = analyze(args.csv.expanduser())
    print(json.dumps(result, indent=2) if args.json else "\n".join(f"{key}\t{value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
