#!/usr/bin/env python3
"""Bridge Arka to the stock_analysis project at ~/Projects/python/products/stock_analysis."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

try:
    from arka.paths import arka_home, entry_script, load_env_file, stock_project_dir

    load_env_file()
except ImportError:
    arka_home = lambda: Path(__file__).resolve().parent  # noqa: E731
    stock_project_dir = lambda: Path(  # noqa: E731
        os.environ.get("STOCK_PROJECT", Path.home() / "Projects/python/products/stock_analysis")
    ).expanduser()

STOCK_PROJECT = stock_project_dir()
WORKER = entry_script("arka_stock_context_worker.py")


def stock_python() -> Path:
    for rel in (".venv/bin/python3", "venv/bin/python3"):
        candidate = STOCK_PROJECT / rel
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def _run_stock(args: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    py = stock_python()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(STOCK_PROJECT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [str(py), *args],
        cwd=str(STOCK_PROJECT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def gather_context(tickers: list[str] | None = None, *, include_ml: bool = True) -> str:
    if not STOCK_PROJECT.is_dir() or not WORKER.is_file():
        return ""
    cmd = [str(WORKER)]
    if not include_ml:
        cmd.append("--no-ml")
    if tickers:
        cmd.extend(t.upper() for t in tickers)
    try:
        proc = _run_stock(cmd, timeout=240 if include_ml else 120)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        if proc.stderr.strip():
            return proc.stderr.strip()[:2000]
    except Exception:
        pass
    return ""


def run_script(script: str, script_args: list[str], *, timeout: int = 120) -> int:
    path = STOCK_PROJECT / script
    if not STOCK_PROJECT.is_dir():
        from arka.stock.ui import stock_project_missing
        stock_project_missing(str(STOCK_PROJECT))
        return 1
    if not path.is_file():
        from arka.stock.ui import note
        from arka.stock.ui import banner
        banner("Stock script missing", icon="⚠️")
        note(f"Expected: {path}")
        note("Clone stock_analysis and set ARKA_STOCK_PROJECT in .env")
        return 1
    py = stock_python()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(STOCK_PROJECT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            [str(py), str(path), *script_args],
            cwd=str(STOCK_PROJECT),
            timeout=timeout,
            env=env,
        )
        return proc.returncode
    except subprocess.TimeoutExpired:
        print("Timed out.", file=sys.stderr)
        return 1


def cmd_prices(tickers: list[str]) -> int:
    args = ["--prices-only"]
    if tickers:
        args.extend(["--tickers", *tickers])
    return run_script("get_free_data.py", args)


def cmd_news() -> int:
    return run_script("get_free_data.py", ["--news-only"])


def cmd_policy(ticker: str) -> int:
    return run_script("policy_impact_scanner.py", [ticker.upper()])


def cmd_strategy(ticker: str, period: str) -> int:
    return run_script("ai_trading_strategy.py", [ticker.upper(), "--period", period])


def cmd_volatility(tickers: str, period: str, interval: str) -> int:
    return run_script(
        "volatility_calculator.py",
        [tickers.upper(), period, interval],
        timeout=300,
    )


def cmd_dashboard() -> int:
    py = stock_python()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(STOCK_PROJECT) + os.pathsep + env.get("PYTHONPATH", "")
    print("Starting Stock Intelligence Hub (Streamlit)…")
    print("Open http://localhost:8501 in your browser.")
    try:
        return subprocess.run(
            [str(py), "-m", "streamlit", "run", "dashboard.py", "--server.headless", "true"],
            cwd=str(STOCK_PROJECT),
            env=env,
        ).returncode
    except FileNotFoundError:
        print("streamlit not installed in stock_analysis venv.", file=sys.stderr)
        return 1


def cmd_context(tickers: list[str], *, no_ml: bool) -> int:
    text = gather_context(tickers or None, include_ml=not no_ml)
    if text:
        print(text)
        return 0
    print("Could not gather stock context — check stock_analysis project and venv.", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka ↔ stock_analysis bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prices", help="Live price table (get_free_data.py)")
    p.add_argument("tickers", nargs="*", help="Ticker symbols (default watchlist)")

    sub.add_parser("news", help="Market news dashboard")

    p = sub.add_parser("policy", help="Policy impact scanner for a ticker")
    p.add_argument("ticker")

    p = sub.add_parser("strategy", help="AI trading strategy backtest")
    p.add_argument("ticker")
    p.add_argument("--period", default="5y")

    p = sub.add_parser("volatility", help="Volatility calculator")
    p.add_argument("tickers", help="Comma-separated tickers")
    p.add_argument("--period", default="1y")
    p.add_argument("--interval", default="1d")

    sub.add_parser("dashboard", help="Streamlit Stock Intelligence Hub")

    p = sub.add_parser("context", help="Plain-text context for predictions")
    p.add_argument("tickers", nargs="*")
    p.add_argument("--no-ml", action="store_true", help="Skip ML signals (faster)")

    p = sub.add_parser("path", help="Print project directory")
    args = parser.parse_args()

    if args.cmd == "prices":
        return cmd_prices(args.tickers)
    if args.cmd == "news":
        return cmd_news()
    if args.cmd == "policy":
        return cmd_policy(args.ticker)
    if args.cmd == "strategy":
        return cmd_strategy(args.ticker, args.period)
    if args.cmd == "volatility":
        return cmd_volatility(args.tickers, args.period, args.interval)
    if args.cmd == "dashboard":
        return cmd_dashboard()
    if args.cmd == "context":
        return cmd_context(args.tickers, no_ml=args.no_ml)
    if args.cmd == "path":
        print(STOCK_PROJECT)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
