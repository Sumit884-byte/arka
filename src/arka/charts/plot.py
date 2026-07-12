#!/usr/bin/env python3
"""Draw stock line charts and bar graphs; save PNG and optionally open."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

RANGE_ALIASES = {
    "1d": "1d",
    "1day": "1d",
    "day": "1d",
    "today": "1d",
    "5d": "5d",
    "5days": "5d",
    "week": "5d",
    "1w": "5d",
    "1wk": "5d",
    "1mo": "1mo",
    "1month": "1mo",
    "month": "1mo",
    "30d": "1mo",
    "3mo": "3mo",
    "3months": "3mo",
    "3month": "3mo",
    "90d": "3mo",
    "6mo": "6mo",
    "6months": "6mo",
    "180d": "6mo",
    "1y": "1y",
    "1year": "1y",
    "year": "1y",
    "12mo": "1y",
    "2y": "2y",
    "5y": "5y",
    "ytd": "ytd",
    "max": "max",
}

COMPANY_TICKERS = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "meta": "META",
    "facebook": "META",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "netflix": "NFLX",
    "reliance": "RELIANCE.NS",
    "tcs": "TCS.NS",
    "infosys": "INFY.NS",
    "hdfc": "HDFCBANK.NS",
    "samsung": "005930.KS",
    "xiaomi": "1810.HK",
}

# Palette aligned with https://github.com/Sumit884-byte/charts (recharts demo)
PIE_COLORS = ["#0088FE", "#00C49F", "#FFBB28", "#FF8042", "#8884d8", "#82ca9d"]
BAR_COLOR = "#2563eb"
BAR_EDGE = "#1e3a8a"
SCATTER_COLOR = "#F97316"
SCATTER_EDGE = "#ea580c"
HIST_COLOR = "#7c3aed"
HIST_EDGE = "#5b21b6"
PARETO_BAR = "#2563eb"
PARETO_LINE = "#dc2626"


@dataclass
class PriceSeries:
    label: str
    dates: list[datetime]
    values: list[float]
    currency: str = ""


def _require_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: F401

        return plt
    except ImportError as exc:
        raise SystemExit(
            "matplotlib is required for charts.\n"
            "Install: pip install matplotlib\n"
            "Or: pip install 'arka-agent[charts]'"
        ) from exc


def default_output(slug: str) -> Path:
    clean = re.sub(r"[^a-z0-9]+", "-", slug.lower())[:48].strip("-") or "chart"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = os.environ.get("CHART_OUTPUT_DIR", "").strip() or os.environ.get(
        "IMAGE_OUTPUT_DIR", ""
    ).strip()
    if env_dir:
        out_dir = Path(env_dir).expanduser()
    else:
        out_dir = Path.home() / "Pictures" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{clean}-{ts}.png"


def open_image(path: Path) -> None:
    if os.environ.get("OPEN_CHART", os.environ.get("OPEN_IMAGE", "1")) in ("0", "false"):
        return
    try:
        if sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform.startswith("linux"):
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError:
        pass


def parse_range(text: str) -> str:
    t = text.lower()
    m = re.search(r"(?:last|past|over)\s+(\d+)\s*(day|days|week|weeks|month|months|year|years)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if "day" in unit:
            return "5d" if n <= 7 else "1mo"
        if "week" in unit:
            return "5d" if n <= 2 else "1mo"
        if "month" in unit:
            if n <= 1:
                return "1mo"
            if n <= 3:
                return "3mo"
            if n <= 6:
                return "6mo"
            return "1y"
        if "year" in unit:
            return "1y" if n <= 1 else "2y"
    for token in re.findall(r"[a-z0-9]+", t):
        if token in RANGE_ALIASES:
            return RANGE_ALIASES[token]
    return "3mo"


def extract_tickers(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(sym: str) -> None:
        sym = sym.strip().upper()
        if not sym or sym in seen:
            return
        seen.add(sym)
        found.append(sym)

    for m in re.finditer(r"\$([A-Za-z][A-Za-z0-9.-]{0,11})", text):
        add(m.group(1))
    for m in re.finditer(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?(?:-[A-Z])?)\b", text):
        tok = m.group(1)
        if tok in {"AI", "US", "UK", "IPO", "ETF", "GDP", "CEO", "API", "PNG", "PDF"}:
            continue
        add(tok)
    lower = text.lower()
    for name, sym in COMPANY_TICKERS.items():
        if re.search(rf"\b{re.escape(name)}\b", lower):
            add(sym)
    return found


def parse_bar_pairs(text: str) -> tuple[list[str], list[float], str]:
    labels: list[str] = []
    values: list[float] = []
    if not text.strip():
        return labels, values, ""

    data_m = re.search(r'--data\s+["\']?([^"\']+)["\']?', text, re.I)
    if data_m:
        chunk = data_m.group(1)
        for part in chunk.split(","):
            if ":" not in part:
                continue
            label, raw = part.split(":", 1)
            try:
                labels.append(label.strip())
                values.append(float(raw.strip().replace(",", "")))
            except ValueError:
                continue
        title = re.sub(r"--data\s+[^\s]+", "", text, flags=re.I).strip()
        title = re.sub(r"(?i)^(bar|chart|graph|plot)\s+", "", title).strip()
        return labels, values, title[:80]

    cleaned = re.sub(
        r"(?i)\b(chart|graph|plot|bar|bars|compare|comparison|sales|sold|units|phones|mobile|smartphones|million|units?)\b",
        " ",
        text,
    )
    for m in re.finditer(
        r"([A-Za-z][A-Za-z0-9.&\s-]{0,24}?)\s*[:=]\s*(\d+(?:\.\d+)?)",
        cleaned,
    ):
        labels.append(m.group(1).strip().title())
        values.append(float(m.group(2)))
    if labels:
        title = re.sub(r"\s+", " ", cleaned).strip()[:80]
        return labels, values, title

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.&-]*|\d+(?:\.\d+)?", cleaned)
    i = 0
    while i < len(tokens) - 1:
        if re.fullmatch(r"\d+(?:\.\d+)?", tokens[i + 1]):
            labels.append(tokens[i].strip().title())
            values.append(float(tokens[i + 1]))
            i += 2
        else:
            i += 1
    title = re.sub(r"\s+", " ", text).strip()[:80]
    return labels, values, title


def parse_scatter_pairs(text: str) -> tuple[list[float], list[float], str, str, str]:
    xs: list[float] = []
    ys: list[float] = []
    if not text.strip():
        return xs, ys, "", "", ""

    xlabel = ""
    ylabel = ""
    label_src = re.sub(r"(?i)^\s*(scatter|plot|chart|graph|correlation)\s+", "", text).strip()
    vs_m = re.search(
        r"(?i)([a-z][a-z0-9\s-]{0,24}?)\s+(?:vs\.?|versus|against)\s+([a-z][a-z0-9\s-]{0,24}?)(?:\s|$|[,.:])",
        label_src,
    )
    if vs_m:
        xlabel = vs_m.group(1).strip().title()
        ylabel = vs_m.group(2).strip().title()

    data_m = re.search(r'--data\s+["\']?([^"\']+)["\']?', text, re.I)
    if data_m:
        for part in data_m.group(1).split(","):
            if ":" not in part:
                continue
            raw_x, raw_y = part.split(":", 1)
            try:
                xs.append(float(raw_x.strip().replace(",", "")))
                ys.append(float(raw_y.strip().replace(",", "")))
            except ValueError:
                continue
        title = re.sub(r"--data\s+[^\s]+", "", text, flags=re.I).strip()
        title = re.sub(r"(?i)^(scatter|plot|chart|graph)\s+", "", title).strip()
        return xs, ys, title[:80], xlabel, ylabel

    cleaned = re.sub(
        r"(?i)\b(scatter|plot|chart|graph|correlation|correlate|points?|data)\b",
        " ",
        text,
    )
    for m in re.finditer(
        r"(\d+(?:\.\d+)?)\s*[:=]\s*(\d+(?:\.\d+)?)",
        cleaned,
    ):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))
    if xs:
        title = re.sub(r"\s+", " ", cleaned).strip()[:80]
        return xs, ys, title, xlabel, ylabel

    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", cleaned)]
    i = 0
    while i < len(nums) - 1:
        xs.append(nums[i])
        ys.append(nums[i + 1])
        i += 2
    title = re.sub(r"\s+", " ", text).strip()[:80]
    return xs, ys, title, xlabel, ylabel


def parse_labeled_pairs(text: str) -> tuple[list[str], list[float]]:
    labels: list[str] = []
    values: list[float] = []
    for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9-]{0,16})\s*:\s*(\d+(?:\.\d+)?)\b", text):
        labels.append(m.group(1).strip().title())
        values.append(float(m.group(2)))
    return labels, values


def _chart_title(text: str, *, drop: tuple[str, ...] = ()) -> str:
    title = text
    for pattern in drop:
        title = re.sub(pattern, " ", title, flags=re.I)
    title = re.sub(r"\b[A-Za-z][A-Za-z0-9-]{0,16}\s*:\s*\d+(?:\.\d+)?\b", " ", title)
    title = re.sub(r"\d+(?:\.\d+)?(?:\s+\d+(?:\.\d+)?)*\s*$", " ", title)
    title = re.sub(r"\s+", " ", title).strip()[:80]
    return title


def unwrap_shell_quotes(text: str) -> str:
    """Strip nested fish/shell quoting wrappers from NL chart prompts."""
    t = (text or "").strip()
    if not t:
        return ""
    # Fish nested: ''"'make …'"''
    nested = re.fullmatch(r"''\"'\"'(.*)'\"'\"''", t, flags=re.DOTALL)
    if nested:
        return nested.group(1).strip()
    # Repeated peel of matching single/double quotes
    for _ in range(4):
        if len(t) >= 2 and t[0] == t[-1] and t[0] in {"'", '"'}:
            t = t[1:-1].strip()
            continue
        break
    return t


def nl_to_argv(text: str) -> list[str]:
    t = unwrap_shell_quotes(text.strip())
    if not t:
        return []

    try:
        from arka.routing.file_size import is_file_size_query

        if is_file_size_query(t):
            return []
    except ImportError:
        pass

    chart_words = r"(?i)\b(chart|graph|plot|visuali[sz]e|diagram)\b"
    stock_words = r"(?i)\b(stock|stocks|share|shares|price|prices|market|ticker|equity)\b"
    bar_words = r"(?i)\b(bar|bars|column|sales|sold|units|phones|mobiles|devices)\b"
    pie_words = r"(?i)\b(pie|donut|doughnut|breakdown|proportion|percentage|percent|traffic\s+sources?|market\s+share)\b"
    scatter_words = r"(?i)\b(scatter|correlation|correlate|xy\s+plot|x-y)\b"
    histogram_words = r"(?i)\b(histogram|frequency|freq|bin|bins)\b"
    pareto_words = r"(?i)\b(pareto|80/20|80-20|eighty.twenty)\b"
    compare_words = r"(?i)\b(compare|comparison|versus|vs\.?|against)\b"

    if re.search(pareto_words, t):
        labels, values = parse_labeled_pairs(t)
        if len(labels) >= 2:
            data = ",".join(
                f"{lbl}:{int(val) if val == int(val) else val:g}" for lbl, val in zip(labels, values)
            )
            title = _chart_title(t, drop=(pareto_words, r"\bchart\b", r"\bgraph\b", r"\bplot\b", r"\bdefects?\b"))
            argv = ["pareto", "--data", data]
            if title:
                argv.extend(["--title", title.title()])
            return argv

    if re.search(histogram_words, t):
        labels, values = parse_labeled_pairs(t)
        if len(labels) >= 2:
            data = ",".join(
                f"{lbl}:{int(val) if val == int(val) else val:g}" for lbl, val in zip(labels, values)
            )
            title = _chart_title(t, drop=(histogram_words, r"\bchart\b", r"\bgraph\b", r"\bplot\b"))
            argv = ["histogram", "--data", data, "--binned"]
            if title:
                argv.extend(["--title", title.title()])
            return argv
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", t)]
        if len(nums) >= 5:
            data = ",".join(f"{n:g}" for n in nums)
            title = _chart_title(t, drop=(histogram_words, r"\bchart\b", r"\bgraph\b", r"\bplot\b", r"\bof\b", r"\bfor\b"))
            argv = ["histogram", "--data", data]
            if title:
                argv.extend(["--title", title.title()])
            return argv

    labels, values, bar_title = parse_bar_pairs(t)
    if len(labels) >= 2:
        data = ",".join(
            f"{lbl}:{int(val) if val == int(val) else val:g}" for lbl, val in zip(labels, values)
        )
        if re.search(pie_words, t) or (
            re.search(r"(?i)\bdistribution\b", t) and not re.search(histogram_words, t)
        ):
            argv = ["pie", "--data", data]
            if bar_title:
                argv.extend(["--title", bar_title])
            return argv

    tickers = extract_tickers(t)
    wants_stock_line = bool(
        tickers
        and (
            re.search(chart_words, t)
            or re.search(r"(?i)\b(show me|draw|make|create)\b.*\b(chart|graph)\b", t)
            or re.search(stock_words, t)
            or (len(tickers) >= 2 and re.search(compare_words, t))
        )
    )
    if wants_stock_line:
        rng = parse_range(t)
        argv = ["line", *tickers, "--range", rng]
        title = (
            f"{tickers[0]} ({rng})"
            if len(tickers) == 1
            else f"{' vs '.join(tickers)} ({rng})"
        )
        argv.extend(["--title", title])
        return argv

    # Scatter: numeric x:y pairs (e.g. ad spend vs revenue)
    if re.search(scatter_words, t) or (
        re.search(compare_words, t)
        and len(re.findall(r"\d+(?:\.\d+)?", t)) >= 4
        and not tickers
    ):
        xs, ys, title, xlabel, ylabel = parse_scatter_pairs(t)
        if len(xs) >= 3:
            data = ",".join(f"{x:g}:{y:g}" for x, y in zip(xs, ys))
            argv = ["scatter", "--data", data]
            if title:
                argv.extend(["--title", title])
            if xlabel:
                argv.extend(["--xlabel", xlabel])
            if ylabel:
                argv.extend(["--ylabel", ylabel])
            return argv

    if len(labels) >= 2 and (
        re.search(bar_words, t)
        or (re.search(r"\d", t) and len(re.findall(r"[A-Za-z][A-Za-z0-9.&-]{1,20}", t)) >= 2)
    ):
        data = ",".join(
            f"{lbl}:{int(val) if val == int(val) else val:g}" for lbl, val in zip(labels, values)
        )
        argv = ["bar", "--data", data]
        if bar_title:
            argv.extend(["--title", bar_title])
        return argv

    return []


def fetch_yahoo_series(symbol: str, range_: str = "3mo") -> PriceSeries | None:
    encoded = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?interval=1d&range={urllib.parse.quote(range_, safe='')}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "arka-chart/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        return None

    result = payload.get("chart", {}).get("result") or []
    if not result:
        return None
    block = result[0]
    meta = block.get("meta", {})
    stamps = block.get("timestamp") or []
    closes = block.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    dates: list[datetime] = []
    values: list[float] = []
    for ts, close in zip(stamps, closes):
        if close is None:
            continue
        dates.append(datetime.fromtimestamp(int(ts), tz=timezone.utc))
        values.append(float(close))
    if len(values) < 2:
        return None
    label = str(meta.get("symbol") or symbol).upper()
    currency = str(meta.get("currency") or "")
    return PriceSeries(label=label, dates=dates, values=values, currency=currency)


def plot_line(
    series_list: list[PriceSeries],
    *,
    title: str,
    output: Path,
) -> Path:
    plt = _require_matplotlib()
    import matplotlib.dates as mdates

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for series in series_list:
        ax.plot(series.dates, series.values, label=series.label, linewidth=2)
    ax.set_title(title or "Stock prices")
    ax.set_xlabel("Date")
    ylabel = "Price"
    currencies = {s.currency for s in series_list if s.currency}
    if len(currencies) == 1:
        ylabel += f" ({next(iter(currencies))})"
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.autofmt_xdate()
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output


def plot_bar(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    ylabel: str,
    output: Path,
) -> Path:
    plt = _require_matplotlib()

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.2), 5.5))
    bars = ax.bar(labels, values, color=BAR_COLOR, edgecolor=BAR_EDGE)
    ax.set_title(title or "Comparison")
    ax.set_ylabel(ylabel or "Value")
    ax.grid(axis="y", alpha=0.3)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{val:g}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    _write_chart_sidecar(
        output,
        {
            "type": "bar",
            "title": title or "Comparison",
            "labels": labels,
            "values": values,
            "ylabel": ylabel or "Value",
            "colors": {lbl: BAR_COLOR for lbl in labels},
            "source": "arka-chart",
        },
    )
    return output


def plot_pie(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    output: Path,
) -> Path:
    plt = _require_matplotlib()

    colors = [PIE_COLORS[i % len(PIE_COLORS)] for i in range(len(labels))]
    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels,
        autopct="%1.0f%%",
        colors=colors,
        startangle=90,
        pctdistance=0.85,
        textprops={"fontsize": 10},
    )
    for autotext in autotexts:
        autotext.set_color("white")
        autotext.set_fontweight("bold")
    ax.set_title(title or "Distribution")
    ax.axis("equal")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    _write_chart_sidecar(
        output,
        {
            "type": "pie",
            "title": title or "Distribution",
            "labels": labels,
            "values": values,
            "percentages": _percentages(labels, values),
            "colors": {lbl: PIE_COLORS[i % len(PIE_COLORS)] for i, lbl in enumerate(labels)},
            "source": "arka-chart",
        },
    )
    return output


def _percentages(labels: list[str], values: list[float]) -> dict[str, int]:
    total = sum(values) or 1.0
    return {lbl: round(100 * val / total) for lbl, val in zip(labels, values)}


def _write_chart_sidecar(output: Path, payload: dict) -> None:
    sidecar = output.with_suffix(".json")
    sidecar.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def plot_scatter(
    xs: list[float],
    ys: list[float],
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    output: Path,
) -> Path:
    plt = _require_matplotlib()

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(xs, ys, color=SCATTER_COLOR, s=80, edgecolors=SCATTER_EDGE, linewidths=0.8)
    ax.set_title(title or "Scatter plot")
    ax.set_xlabel(xlabel or "X")
    ax.set_ylabel(ylabel or "Y")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    points = [{"x": x, "y": y} for x, y in zip(xs, ys)]
    _write_chart_sidecar(
        output,
        {
            "type": "scatter",
            "title": title or "Scatter plot",
            "xlabel": xlabel or "X",
            "ylabel": ylabel or "Y",
            "points": points,
            "color": SCATTER_COLOR,
            "source": "arka-chart",
        },
    )
    return output


def plot_histogram(
    *,
    raw_values: list[float] | None = None,
    bin_labels: list[str] | None = None,
    counts: list[float] | None = None,
    title: str,
    xlabel: str,
    bins: int | None,
    output: Path,
) -> Path:
    plt = _require_matplotlib()

    if bin_labels and counts:
        fig, ax = plt.subplots(figsize=(max(6, len(bin_labels) * 1.2), 5.5))
        ax.bar(bin_labels, counts, color=HIST_COLOR, edgecolor=HIST_EDGE)
        ax.set_ylabel("Count")
        sidecar_bins = [{"label": lbl, "count": cnt} for lbl, cnt in zip(bin_labels, counts)]
        total = sum(counts)
        peak_i = max(range(len(counts)), key=lambda i: counts[i])
    else:
        values = raw_values or []
        fig, ax = plt.subplots(figsize=(8, 5.5))
        n, edges, _patches = ax.hist(
            values,
            bins=bins or "auto",
            color=HIST_COLOR,
            edgecolor=HIST_EDGE,
        )
        counts_list = [float(c) for c in n]
        edge_list = [float(e) for e in edges]
        bin_labels = [f"{edge_list[i]:g}–{edge_list[i + 1]:g}" for i in range(len(counts_list))]
        sidecar_bins = [
            {"start": edge_list[i], "end": edge_list[i + 1], "count": counts_list[i]}
            for i in range(len(counts_list))
        ]
        total = sum(counts_list)
        peak_i = max(range(len(counts_list)), key=lambda i: counts_list[i]) if counts_list else 0
        counts = counts_list

    ax.set_title(title or "Histogram")
    ax.set_xlabel(xlabel or "Value")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    _write_chart_sidecar(
        output,
        {
            "type": "histogram",
            "title": title or "Histogram",
            "xlabel": xlabel or "Value",
            "bins": sidecar_bins,
            "total": total,
            "peak_bin": bin_labels[peak_i] if bin_labels else "",
            "peak_count": counts[peak_i] if counts else 0,
            "source": "arka-chart",
        },
    )
    return output


def plot_pareto(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    output: Path,
) -> Path:
    plt = _require_matplotlib()

    pairs = sorted(zip(labels, values), key=lambda row: row[1], reverse=True)
    sorted_labels = [p[0] for p in pairs]
    sorted_values = [p[1] for p in pairs]
    total = sum(sorted_values) or 1.0
    cumulative: list[float] = []
    running = 0.0
    for val in sorted_values:
        running += val
        cumulative.append(round(100 * running / total, 1))

    fig, ax1 = plt.subplots(figsize=(max(7, len(sorted_labels) * 1.3), 5.5))
    ax1.bar(sorted_labels, sorted_values, color=PARETO_BAR, edgecolor=BAR_EDGE)
    ax1.set_ylabel("Count")
    ax1.set_title(title or "Pareto chart")
    ax1.grid(axis="y", alpha=0.3)
    for bar, val in zip(ax1.patches, sorted_values):
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{val:g}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    ax2 = ax1.twinx()
    ax2.plot(sorted_labels, cumulative, color=PARETO_LINE, marker="o", linewidth=2)
    ax2.set_ylabel("Cumulative %")
    ax2.set_ylim(0, 105)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    _write_chart_sidecar(
        output,
        {
            "type": "pareto",
            "title": title or "Pareto chart",
            "labels": sorted_labels,
            "values": sorted_values,
            "cumulative_pct": {lbl: pct for lbl, pct in zip(sorted_labels, cumulative)},
            "source": "arka-chart",
        },
    )
    return output


_SUFFIX_MULTIPLIERS: dict[str, float] = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mil": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "trillion": 1e12,
}


def parse_numeric_value(raw: str | float | int) -> float:
    """Parse chart numbers like 4.7, $4.7T, 45%, 1,200B into floats."""
    if isinstance(raw, bool):
        raise ValueError(f"invalid numeric value: {raw!r}")
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        raise ValueError("empty numeric value")
    text = text.replace(",", "").replace(" ", "")
    text = re.sub(r"^[\$€£₹]", "", text)
    if text.endswith("%"):
        return float(text[:-1] or "0")
    match = re.match(r"^([+-]?\d+(?:\.\d+)?)([a-zA-Z]+)?$", text)
    if not match:
        cleaned = re.sub(r"[^\d.+-]", "", text)
        if not cleaned:
            raise ValueError(f"could not parse numeric value: {raw!r}")
        return float(cleaned)
    num = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    if not suffix or suffix in {"usd", "pct", "percent", "points"}:
        return num
    multiplier = _SUFFIX_MULTIPLIERS.get(suffix)
    if multiplier is None and suffix:
        multiplier = _SUFFIX_MULTIPLIERS.get(suffix[0])
    if multiplier is None:
        raise ValueError(f"unknown numeric suffix in {raw!r}")
    return num * multiplier


def parse_data_arg(raw: str) -> tuple[list[str], list[float]]:
    labels: list[str] = []
    values: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        label, val = part.split(":", 1)
        labels.append(label.strip())
        values.append(parse_numeric_value(val.strip()))
    if len(labels) < 2:
        raise SystemExit("Need at least two label:value pairs in --data (e.g. Apple:230,Samsung:210)")
    return labels, values


def parse_xy_data(raw: str) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        raw_x, raw_y = part.split(":", 1)
        xs.append(parse_numeric_value(raw_x.strip()))
        ys.append(parse_numeric_value(raw_y.strip()))
    if len(xs) < 3:
        raise SystemExit("Need at least three x:y pairs in --data (e.g. 100:200,120:190,170:280)")
    return xs, ys


def parse_histogram_data(raw: str, *, binned: bool) -> tuple[list[float] | None, list[str] | None, list[float] | None]:
    if binned or ":" in raw:
        labels, values = parse_data_arg(raw)
        return None, labels, values
    values: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(float(part.replace(",", "")))
    if len(values) < 5:
        raise SystemExit("Need at least five numeric values (e.g. 12,15,18,22,25) or binned label:count pairs")
    return values, None, None


def cmd_histogram(args: argparse.Namespace) -> int:
    raw, bin_labels, counts = parse_histogram_data(args.data, binned=getattr(args, "binned", False))
    title = args.title or "Histogram"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40] or "histogram"
    out = Path(args.output).expanduser() if args.output else default_output(slug)
    saved = plot_histogram(
        raw_values=raw,
        bin_labels=bin_labels,
        counts=counts,
        title=title,
        xlabel=args.xlabel,
        bins=args.bins,
        output=out,
    )
    print(f"Saved chart: {saved}")
    open_image(saved)
    return 0


def cmd_pareto(args: argparse.Namespace) -> int:
    labels, values = parse_data_arg(args.data)
    title = args.title or "Pareto chart"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40] or "pareto-chart"
    out = Path(args.output).expanduser() if args.output else default_output(slug)
    saved = plot_pareto(labels, values, title=title, output=out)
    print(f"Saved chart: {saved}")
    open_image(saved)
    return 0


def cmd_line(args: argparse.Namespace) -> int:
    tickers = [t.upper() for t in args.tickers]
    if not tickers:
        print("Usage: chart line TICKER [TICKER...] [--range 3mo]", file=sys.stderr)
        return 1
    series_list: list[PriceSeries] = []
    for sym in tickers:
        row = fetch_yahoo_series(sym, args.range)
        if row is None:
            print(f"No price data for {sym}. Check ticker symbol.", file=sys.stderr)
            return 1
        series_list.append(row)
    title = args.title or (
        f"{series_list[0].label} ({args.range})"
        if len(series_list) == 1
        else f"{' vs '.join(s.label for s in series_list)} ({args.range})"
    )
    slug = "-".join(s.label.lower() for s in series_list)
    out = Path(args.output).expanduser() if args.output else default_output(slug)
    saved = plot_line(series_list, title=title, output=out)
    print(f"Saved chart: {saved}")
    open_image(saved)
    return 0


def cmd_bar(args: argparse.Namespace) -> int:
    labels, values = parse_data_arg(args.data)
    title = args.title or "Comparison"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40] or "bar-chart"
    out = Path(args.output).expanduser() if args.output else default_output(slug)
    saved = plot_bar(labels, values, title=title, ylabel=args.ylabel, output=out)
    print(f"Saved chart: {saved}")
    open_image(saved)
    return 0


def cmd_pie(args: argparse.Namespace) -> int:
    labels, values = parse_data_arg(args.data)
    title = args.title or "Distribution"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40] or "pie-chart"
    out = Path(args.output).expanduser() if args.output else default_output(slug)
    saved = plot_pie(labels, values, title=title, output=out)
    print(f"Saved chart: {saved}")
    open_image(saved)
    return 0


def cmd_scatter(args: argparse.Namespace) -> int:
    xs, ys = parse_xy_data(args.data)
    title = args.title or "Scatter plot"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40] or "scatter-chart"
    out = Path(args.output).expanduser() if args.output else default_output(slug)
    saved = plot_scatter(
        xs,
        ys,
        title=title,
        xlabel=args.xlabel,
        ylabel=args.ylabel,
        output=out,
    )
    print(f"Saved chart: {saved}")
    open_image(saved)
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Draw line, bar, pie, and scatter charts")
    sub = p.add_subparsers(dest="cmd")

    p_line = sub.add_parser("line", help="Line chart from Yahoo Finance tickers")
    p_line.add_argument("tickers", nargs="+", help="Ticker symbols (e.g. AAPL TSLA RELIANCE.NS)")
    p_line.add_argument("--range", default="3mo", help="Yahoo range: 1mo, 3mo, 6mo, 1y, …")
    p_line.add_argument("-o", "--output", help="Output PNG path")
    p_line.add_argument("--title", default="", help="Chart title")
    p_line.set_defaults(func=cmd_line)

    p_bar = sub.add_parser("bar", help="Bar chart from label:value pairs")
    p_bar.add_argument(
        "--data",
        required=True,
        help='Comma-separated pairs, e.g. "Apple:230,Samsung:210,Xiaomi:140"',
    )
    p_bar.add_argument("-o", "--output", help="Output PNG path")
    p_bar.add_argument("--title", default="", help="Chart title")
    p_bar.add_argument("--ylabel", default="Units", help="Y-axis label")
    p_bar.set_defaults(func=cmd_bar)

    p_pie = sub.add_parser("pie", help="Pie chart from label:value pairs")
    p_pie.add_argument(
        "--data",
        required=True,
        help='Comma-separated pairs, e.g. "Organic:400,Direct:300,Referral:300,Social:200"',
    )
    p_pie.add_argument("-o", "--output", help="Output PNG path")
    p_pie.add_argument("--title", default="", help="Chart title")
    p_pie.set_defaults(func=cmd_pie)

    p_scatter = sub.add_parser("scatter", help="Scatter plot from x:y numeric pairs")
    p_scatter.add_argument(
        "--data",
        required=True,
        help='Comma-separated x:y pairs, e.g. "100:200,120:190,170:280"',
    )
    p_scatter.add_argument("-o", "--output", help="Output PNG path")
    p_scatter.add_argument("--title", default="", help="Chart title")
    p_scatter.add_argument("--xlabel", default="", help="X-axis label")
    p_scatter.add_argument("--ylabel", default="", help="Y-axis label")
    p_scatter.set_defaults(func=cmd_scatter)

    p_hist = sub.add_parser("histogram", help="Histogram from numeric values or binned label:count pairs")
    p_hist.add_argument(
        "--data",
        required=True,
        help='Raw values "12,15,18,..." or binned "0-10:5,10-20:12"',
    )
    p_hist.add_argument("--binned", action="store_true", help="Treat --data as label:count pairs")
    p_hist.add_argument("--bins", type=int, default=None, help="Number of bins for raw values")
    p_hist.add_argument("-o", "--output", help="Output PNG path")
    p_hist.add_argument("--title", default="", help="Chart title")
    p_hist.add_argument("--xlabel", default="", help="X-axis label")
    p_hist.set_defaults(func=cmd_histogram)

    p_pareto = sub.add_parser("pareto", help="Pareto chart from label:value pairs")
    p_pareto.add_argument(
        "--data",
        required=True,
        help='Comma-separated pairs, e.g. "Scratches:45,Dents:28,Cracks:15"',
    )
    p_pareto.add_argument("-o", "--output", help="Output PNG path")
    p_pareto.add_argument("--title", default="", help="Chart title")
    p_pareto.set_defaults(func=cmd_pareto)

    p_parse = sub.add_parser("parse", help="Parse natural language → chart args (internal)")
    p_parse.add_argument("text", nargs="+", help="Natural language request")
    p_parse.set_defaults(func=cmd_parse)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in {"line", "bar", "pie", "scatter", "histogram", "pareto", "parse", "-h", "--help"}:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl
        else:
            print("Could not parse chart request. Try:", file=sys.stderr)
            print("  chart line AAPL MSFT --range 3mo", file=sys.stderr)
            print('  chart bar --data "Apple:230,Samsung:210" --title "Phone sales"', file=sys.stderr)
            print('  chart pie --data "Organic:400,Direct:300,Referral:300"', file=sys.stderr)
            print('  chart scatter --data "100:200,120:190,170:280" --xlabel "Spend" --ylabel "Revenue"', file=sys.stderr)
            print('  chart histogram --data "12,15,18,22,25,28,30,35,38,42"', file=sys.stderr)
            print('  chart pareto --data "Scratches:45,Dents:28,Cracks:15"', file=sys.stderr)
            return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
