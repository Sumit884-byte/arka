#!/usr/bin/env python3
"""Arka future prediction CLI — weather, ISRO rainfall, stocks, satellites, time series."""

from __future__ import annotations

import argparse
import sys

from arka.predict.engine import nl_to_future_argv, run_future


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Future predictions from live data (weather, ISRO/MOSDAC rainfall, stocks, ISS, CSV)"
    )
    sub = p.add_subparsers(dest="cmd")

    pf = sub.add_parser("future", help="Predict future from natural language")
    pf.add_argument("query", nargs="+", help="What to predict")
    pf.add_argument(
        "--domain",
        default="auto",
        choices=["auto", "stock", "weather", "rainfall", "satellite", "timeseries", "kaggle", "general"],
    )
    pf.add_argument("--days", type=int, default=None, help="Forecast horizon (days)")
    pf.add_argument("--chart", action="store_true", help="Save a forecast PNG chart")
    pf.add_argument("-o", "--output", help="Chart output path")
    pf.add_argument("--range", default="1y", help="Stock history range")
    pf.set_defaults(func=cmd_future)

    ps = sub.add_parser("parse", help="Parse NL → predict argv (internal)")
    ps.add_argument("query", nargs="+")
    ps.set_defaults(func=cmd_parse)

    return p


def cmd_future(args: argparse.Namespace) -> int:
    from pathlib import Path

    query = " ".join(args.query)
    out = Path(args.output).expanduser() if args.output else None
    result = run_future(
        query,
        domain=args.domain,
        days=args.days,
        chart=bool(args.chart),
        output=out,
        history_range=args.range,
    )
    print(result.text)
    if result.chart_path:
        print(f"\nSaved prediction chart: {result.chart_path}")
        if result.forecast:
            print(f"  Signal: {result.forecast.signal}")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_future_argv(" ".join(args.query))
    if not argv:
        return 1
    for a in argv:
        print(a.replace("\n", " "))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in {"future", "parse", "-h", "--help"}:
        nl = nl_to_future_argv(" ".join(argv))
        if nl:
            argv = nl
        else:
            argv = ["future", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
