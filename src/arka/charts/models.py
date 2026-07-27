"""Charts for AI / LLM model characteristics (benchmark scores, latency, size)."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_MODEL_CHART = re.compile(
    r"(?i)"
    r"(?:chart|graph|plot|visuali[sz]e|show)\s+.*\b(?:ai|llm|model)s?\b.*\b(?:characteristic|comparison|benchmark|performance|capabilit)"
    r"|\b(?:ai|llm|model)s?\b.*\b(?:characteristic|comparison|benchmark|performance)\b.*\b(?:chart|graph|plot|scatter|points?)\b"
    r"|\bmodel\s+(?:latency|score|benchmark)\b.*\b(?:chart|graph|plot|scatter|vs)\b"
    r"|\bbenchmark\s+(?:results?|rankings?)\b.*\b(?:chart|graph|plot)\b"
    r"|\bscatter\b.*\b(?:model|llm|latency|score)\b"
)


@dataclass
class ModelPoint:
    label: str
    score: float
    latency_ms: float
    success_rate: float
    size_b: float | None = None


def wants_model_chart(text: str) -> bool:
    return bool(_MODEL_CHART.search(text or ""))


def _short_label(name: str, *, max_len: int = 22) -> str:
    s = name.replace("orchestrator:", "orch:").replace("/", "\n")
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _ollama_param_size(model: str) -> float:
    match = re.search(r":(\d+(?:\.\d+)?)b\b", model.lower())
    return float(match.group(1)) if match else 7.0


def benchmark_points(profile: str | None = None) -> list[ModelPoint]:
    from arka.llm.benchmarks import load_results

    data = load_results()
    suites = data.get("suites") or {}
    points: list[ModelPoint] = []
    seen: set[str] = set()
    for suite_data in suites.values():
        rankings = suite_data.get("rankings") or {}
        profiles = [profile] if profile else sorted(rankings.keys())
        for prof in profiles:
            for row in rankings.get(prof) or []:
                label = str(row.get("candidate") or f"{row.get('provider')}/{row.get('model')}")
                key = label.lower()
                if key in seen:
                    continue
                seen.add(key)
                points.append(
                    ModelPoint(
                        label=label,
                        score=float(row.get("score") or 0),
                        latency_ms=float(row.get("latency_ms") or 0),
                        success_rate=float(row.get("success_rate") or 0),
                    )
                )
    return points


def local_ollama_points(limit: int = 12) -> list[ModelPoint]:
    from arka.llm.model_advisor import probe_hardware, strongest_runnable_local_models

    snap = probe_hardware()
    models = strongest_runnable_local_models(snap, limit=limit)
    return [
        ModelPoint(
            label=m,
            score=0.0,
            latency_ms=0.0,
            success_rate=1.0,
            size_b=_ollama_param_size(m),
        )
        for m in models
    ]


def choose_chart_kind(text: str, points: list[ModelPoint]) -> str:
    low = (text or "").lower()
    if re.search(r"(?i)\bscatter\b|\bdata\s+points?\b|\blatency\s+vs\s+score\b", low):
        return "scatter"
    if re.search(r"(?i)\bsize\b|\bparameter|\bparams\b|\bbillion\b", low):
        return "size_bar"
    has_scores = any(p.score > 0 for p in points)
    if has_scores and any(p.latency_ms > 0 for p in points):
        return "scatter"
    if has_scores:
        return "score_bar"
    return "size_bar"


def plot_model_characteristics(
    points: list[ModelPoint],
    *,
    kind: str,
    title: str,
    output: Path,
    source: str = "",
) -> Path:
    from arka.charts.plot import (
        _apply_chart_chrome,
        _require_matplotlib,
        plot_bar,
        plot_scatter,
    )

    if not points:
        raise RuntimeError("No model data to chart")

    if kind == "scatter":
        scored = [p for p in points if p.score > 0 and p.latency_ms > 0]
        if len(scored) < 2:
            raise RuntimeError(
                "Need benchmark results for a latency-vs-score scatter. Run: arka benchmark run"
            )
        xs = [p.latency_ms for p in scored]
        ys = [p.score for p in scored]
        plt = _require_matplotlib()
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.scatter(xs, ys, s=90, color="#2563eb", edgecolors="#1e3a8a", linewidths=0.8)
        for p in scored:
            ax.annotate(
                _short_label(p.label, max_len=18),
                (p.latency_ms, p.score),
                textcoords="offset points",
                xytext=(4, 4),
                fontsize=8,
                alpha=0.85,
            )
        ax.set_xlabel("Latency (ms)")
        ax.set_ylabel("Benchmark score")
        ax.grid(True, alpha=0.3)
        _apply_chart_chrome(fig, ax, title=title, source=source or "Arka benchmarks")
        fig.tight_layout()
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=150)
        plt.close(fig)
        return output

    if kind == "size_bar":
        sized = [p for p in points if p.size_b is not None]
        if not sized:
            raise RuntimeError("No local Ollama models found for size chart")
        labels = [_short_label(p.label) for p in sized]
        values = [float(p.size_b or 0) for p in sized]
        return plot_bar(
            labels,
            values,
            title=title or "Local model size (parameter scale, B)",
            ylabel="Params (B)",
            output=output,
            source=source or "Ollama + hardware probe",
        )

    scored = [p for p in points if p.score > 0]
    if not scored:
        raise RuntimeError(
            "No benchmark scores found. Run: arka benchmark run — or ask for local model size chart"
        )
    labels = [_short_label(p.label) for p in scored]
    values = [p.score for p in scored]
    return plot_bar(
        labels,
        values,
        title=title or "Model benchmark scores",
        ylabel="Score",
        output=output,
        source=source or "Arka benchmarks",
    )


def build_model_chart(
    text: str = "",
    *,
    profile: str | None = None,
    kind: str = "auto",
    output: Path | None = None,
) -> Path:
    from arka.charts.plot import default_output, open_image

    bench = benchmark_points(profile)
    points = bench if bench else local_ollama_points()
    if not bench:
        for p in points:
            p.score = 0.0

    chart_kind = kind if kind != "auto" else choose_chart_kind(text, bench or points)
    title = "AI model characteristics"
    if profile:
        title += f" — {profile}"
    if chart_kind == "scatter":
        title = "Model latency vs benchmark score"
    elif chart_kind == "size_bar":
        title = "Local Ollama models by parameter scale"

    slug = re.sub(r"[^a-z0-9]+", "-", chart_kind + "-models").strip("-")
    out = output.expanduser() if output else default_output(slug)
    saved = plot_model_characteristics(
        points,
        kind=chart_kind,
        title=title,
        output=out,
        source="benchmark-results.json" if bench else "Ollama",
    )
    return saved


def nl_to_model_chart_argv(text: str) -> list[str] | None:
    if not wants_model_chart(text):
        return None
    argv = ["models"]
    m = re.search(r"(?i)\b(?:profile|task)\s+(chat|route|agent|summarize|research|pdf|predictions)\b", text)
    if m:
        argv.extend(["--profile", m.group(1).lower()])
    if re.search(r"(?i)\bscatter\b|\blatency\s+vs\s+score\b|\bdata\s+points?\b", text):
        argv.extend(["--type", "scatter"])
    elif re.search(r"(?i)\bsize\b|\bparameter|\bparams\b", text):
        argv.extend(["--type", "size_bar"])
    elif re.search(r"(?i)\bbar\b|\bscores?\b", text):
        argv.extend(["--type", "score_bar"])
    return argv


def cmd_models(args: argparse.Namespace) -> int:
    from arka.charts.plot import open_image

    text = getattr(args, "text", "") or ""
    try:
        saved = build_model_chart(
            text,
            profile=args.profile or None,
            kind=args.type or "auto",
            output=Path(args.output).expanduser() if args.output else None,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        print("Try: arka benchmark run   then   arka chart models --type scatter", file=sys.stderr)
        return 1
    print(f"Saved model chart: {saved}")
    open_image(saved)
    return 0


def add_models_subparser(sub) -> None:
    p = sub.add_parser("models", help="Chart AI model characteristics (benchmark or local Ollama)")
    p.add_argument("--profile", default="", help="Benchmark task profile (chat, agent, route, …)")
    p.add_argument(
        "--type",
        default="auto",
        choices=["auto", "scatter", "score_bar", "size_bar"],
        help="Chart type: scatter latency vs score, bar scores, or local size",
    )
    p.add_argument("-o", "--output", help="Output PNG path")
    p.add_argument("text", nargs="*", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_models)
