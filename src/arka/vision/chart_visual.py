"""Structured chart visual analysis — colors + OCR positions without vision LLM."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arka.vision.ocr import OcrBlock

# Must match arka.charts.plot color constants
PIE_PALETTE = ["#0088FE", "#00C49F", "#FFBB28", "#FF8042", "#8884d8", "#82ca9d"]
BAR_COLOR = "#2563EB"
SCATTER_COLOR = "#F97316"
HIST_COLOR = "#7C3AED"
PARETO_BAR = "#2563EB"
PARETO_LINE = "#DC2626"

HEX_COLOR_NAMES: dict[str, str] = {
    "#0088FE": "Blue",
    "#00C49F": "Teal",
    "#FFBB28": "Gold",
    "#FF8042": "Orange",
    "#8884D8": "Purple",
    "#82CA9D": "Mint",
    "#2563EB": "Blue",
    "#F97316": "Orange",
    "#7C3AED": "Purple",
    "#DC2626": "Red",
}

COLOR_MARKERS: dict[str, str] = {
    "Blue": "●",
    "Teal": "◆",
    "Gold": "▲",
    "Orange": "■",
    "Purple": "◆",
    "Mint": "●",
    "Green": "●",
    "Red": "■",
}


def enrich_payload(payload: dict) -> dict:
    chart_type = payload.get("type")
    if chart_type == "pie":
        return enrich_pie_payload(payload)
    return payload


def enrich_pie_payload(payload: dict) -> dict:
    if payload.get("type") != "pie":
        return payload
    labels = payload.get("labels") or []
    if not labels:
        return payload
    out = dict(payload)
    if not out.get("colors"):
        out["colors"] = {
            lbl: PIE_PALETTE[i % len(PIE_PALETTE)] for i, lbl in enumerate(labels)
        }
    return out


def _color_name(hex_color: str) -> str:
    key = (hex_color or "").upper()
    if key in HEX_COLOR_NAMES:
        return HEX_COLOR_NAMES[key]
    if key.startswith("#") and len(key) >= 7:
        r, g, b = int(key[1:3], 16), int(key[3:5], 16), int(key[5:7], 16)
        if b > r and b > g:
            return "Blue"
        if g > r and g > b:
            return "Green"
        if r > g and r > b:
            return "Red"
        if r > 200 and g > 200:
            return "Gold"
        if r > 200 and g > 100:
            return "Orange"
    return hex_color or "—"


def _compass(x_pct: float, y_pct: float) -> str:
    dx, dy = x_pct - 50.0, y_pct - 50.0
    if abs(dx) < 6 and abs(dy) < 6:
        return "center"
    parts: list[str] = []
    if dy < -8:
        parts.append("top")
    elif dy > 8:
        parts.append("bottom")
    if dx < -8:
        parts.append("left")
    elif dx > 8:
        parts.append("right")
    if not parts:
        return "center"
    return "-".join(parts)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _find_label_block(blocks: tuple[OcrBlock, ...], label: str) -> OcrBlock | None:
    want = _norm(label)
    best: OcrBlock | None = None
    best_score = 0
    for b in blocks:
        if "%" in b.text:
            continue
        got = _norm(b.text)
        if got == want:
            return b
        if want in got or got in want:
            score = min(len(want), len(got))
            if score > best_score:
                best, best_score = b, score
    return best


def _find_pct_block(
    blocks: tuple[OcrBlock, ...],
    pct: int | float | None,
    *,
    near: OcrBlock | None,
    used: set[int],
) -> OcrBlock | None:
    if pct is None:
        return None
    target = f"{int(pct)}%"
    best_i: int | None = None
    best_dist = 1e9
    for i, b in enumerate(blocks):
        if i in used:
            continue
        if b.text.replace(" ", "") != target:
            continue
        if near is None:
            used.add(i)
            return b
        dist = (b.x_pct - near.x_pct) ** 2 + (b.y_pct - near.y_pct) ** 2
        if dist < best_dist:
            best_dist, best_i = dist, i
    if best_i is not None and best_dist < 2500:
        used.add(best_i)
        return blocks[best_i]
    return None


def _box_title(title: str, subtitle: str) -> list[str]:
    w = max(len(title), len(subtitle), 34)
    rule = "  " + "─" * w
    return [
        f"  {title}",
        rule,
        f"  {subtitle}",
        "",
    ]


def render_pie_visual(payload: dict, blocks: tuple[OcrBlock, ...]) -> str:
    """Pretty terminal-friendly chart description."""
    payload = enrich_pie_payload(payload)
    title = payload.get("title") or "Chart"
    labels: list[str] = payload.get("labels") or []
    values: list[float] = payload.get("values") or []
    percentages: dict = payload.get("percentages") or {}
    colors: dict = payload.get("colors") or {}

    if not labels:
        return f"{title} (empty chart)"

    max_name = max(len(lbl) for lbl in labels)
    lines = _box_title(title, f"Pie chart · {len(labels)} segments")
    lines.append("")

    for lbl, val in zip(labels, values):
        pct = percentages.get(lbl, 0)
        cname = _color_name(str(colors.get(lbl, "")))
        marker = COLOR_MARKERS.get(cname, "●")
        lines.append(
            f"    {marker} {lbl:<{max_name}}   {int(pct):>3}%   {val:>4g}   · {cname}"
        )

    order = " → ".join(labels)
    lines.extend(
        [
            "",
            f"  Segments (clockwise from top): {order}",
        ]
    )
    return "\n".join(lines)


def render_bar_visual(payload: dict, blocks: tuple[OcrBlock, ...]) -> str:
    _ = blocks
    title = payload.get("title") or "Chart"
    labels: list[str] = payload.get("labels") or []
    values: list[float] = payload.get("values") or []
    ylabel = payload.get("ylabel") or "Value"
    if not labels:
        return f"{title} (empty chart)"

    max_name = max(len(lbl) for lbl in labels)
    peak_i = max(range(len(values)), key=lambda i: values[i])
    low_i = min(range(len(values)), key=lambda i: values[i])
    cname = _color_name(BAR_COLOR)

    lines = _box_title(title, f"Bar chart · {len(labels)} categories · Y: {ylabel}")
    lines.append("")
    for lbl, val in zip(labels, values):
        lines.append(f"    █ {lbl:<{max_name}}   {val:>6g}   · {cname}")
    lines.extend(
        [
            "",
            f"  Highest: {labels[peak_i]} ({values[peak_i]:g}) · "
            f"Lowest: {labels[low_i]} ({values[low_i]:g})",
        ]
    )
    return "\n".join(lines)


def render_scatter_visual(payload: dict, blocks: tuple[OcrBlock, ...]) -> str:
    _ = blocks
    title = payload.get("title") or "Scatter plot"
    points: list[dict] = payload.get("points") or []
    xlabel = payload.get("xlabel") or "X"
    ylabel = payload.get("ylabel") or "Y"
    if len(points) < 2:
        return f"{title} (empty chart)"

    xs = [float(p["x"]) for p in points]
    ys = [float(p["y"]) for p in points]
    cname = _color_name(str(payload.get("color") or SCATTER_COLOR))
    point_str = "  ".join(f"({p['x']:g}, {p['y']:g})" for p in points[:8])
    if len(points) > 8:
        point_str += f"  … +{len(points) - 8} more"

    lines = _box_title(title, f"Scatter plot · {len(points)} points")
    lines.extend(
        [
            f"  X: {xlabel} · Y: {ylabel} · Color: {cname}",
            "",
            f"    {point_str}",
            "",
            f"  Range X: {min(xs):g}–{max(xs):g} · Range Y: {min(ys):g}–{max(ys):g}",
        ]
    )
    return "\n".join(lines)


def render_histogram_visual(payload: dict, blocks: tuple[OcrBlock, ...]) -> str:
    _ = blocks
    title = payload.get("title") or "Histogram"
    xlabel = payload.get("xlabel") or "Value"
    bins: list[dict] = payload.get("bins") or []
    if not bins:
        return f"{title} (empty chart)"

    labels: list[str] = []
    counts: list[float] = []
    for row in bins:
        if "label" in row:
            labels.append(str(row["label"]))
        else:
            labels.append(f"{row.get('start', '?')}–{row.get('end', '?')}")
        counts.append(float(row.get("count", 0)))

    max_label = max(len(lbl) for lbl in labels)
    total = float(payload.get("total") or sum(counts))
    peak_bin = payload.get("peak_bin") or labels[max(range(len(counts)), key=lambda i: counts[i])]
    peak_count = payload.get("peak_count") or max(counts)
    cname = _color_name(HIST_COLOR)

    lines = _box_title(title, f"Histogram · {len(bins)} bins · X: {xlabel}")
    lines.append("")
    for lbl, cnt in zip(labels, counts):
        lines.append(f"    ▌ {lbl:<{max_label}}   {int(cnt):>4g}   · {cname}")
    lines.extend(
        [
            "",
            f"  Total: {total:g} · Peak bin: {peak_bin} ({peak_count:g})",
        ]
    )
    return "\n".join(lines)


def render_pareto_visual(payload: dict, blocks: tuple[OcrBlock, ...]) -> str:
    _ = blocks
    title = payload.get("title") or "Pareto chart"
    labels: list[str] = payload.get("labels") or []
    values: list[float] = payload.get("values") or []
    cumulative: dict = payload.get("cumulative_pct") or {}
    if not labels:
        return f"{title} (empty chart)"

    max_name = max(len(lbl) for lbl in labels)
    bar_color = _color_name(PARETO_BAR)
    line_color = _color_name(PARETO_LINE)

    lines = _box_title(title, f"Pareto chart · {len(labels)} categories")
    lines.append("")
    for lbl, val in zip(labels, values):
        cum = cumulative.get(lbl, 0)
        lines.append(
            f"    █ {lbl:<{max_name}}   {val:>4g}   · {int(cum):>3}% cum · {bar_color}"
        )
    top2 = float(cumulative.get(labels[0], 0))
    if len(labels) >= 2:
        top2 = float(cumulative.get(labels[1], top2))
    lines.extend(
        [
            "",
            f"  Cumulative line: {line_color} · Top 2 reach {top2:g}%",
        ]
    )
    return "\n".join(lines)


def render_structured_visual(payload: dict, blocks: tuple[OcrBlock, ...]) -> str:
    chart_type = payload.get("type")
    if chart_type == "pie":
        return render_pie_visual(payload, blocks)
    if chart_type == "bar":
        return render_bar_visual(payload, blocks)
    if chart_type == "scatter":
        return render_scatter_visual(payload, blocks)
    if chart_type == "histogram":
        return render_histogram_visual(payload, blocks)
    if chart_type == "pareto":
        return render_pareto_visual(payload, blocks)
    return payload.get("title") or "Chart"


def can_render_structured(payload: dict | None) -> bool:
    if not payload:
        return False
    chart_type = payload.get("type")
    if chart_type == "pie":
        return bool(payload.get("labels"))
    if chart_type == "bar":
        return bool(payload.get("labels") and payload.get("values"))
    if chart_type == "scatter":
        return len(payload.get("points") or []) >= 2
    if chart_type == "histogram":
        return bool(payload.get("bins"))
    if chart_type == "pareto":
        return bool(payload.get("labels") and payload.get("values"))
    return False
