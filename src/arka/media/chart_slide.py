"""Render chart or slide PNGs at video resolution for compose_video scenes."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arka.media.compose_video import Scene, VideoConfig


ACCENT = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#79c0ff"]
FOOTER_Y = 0.055
FOOTER_FONTSIZE = 10
DPI = 160
BASE_MARGINS = {"left": 0.12, "right": 0.96, "top": 0.88, "bottom": 0.20}


def scene_has_chart_visual(scene: Scene) -> bool:
    return bool(scene.chart or scene.chart_path.strip() or scene.slide_image.strip())


def _require_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError as exc:
        raise SystemExit(
            "Chart scenes require matplotlib.\nInstall: pip install 'arka-agent[charts]'  or  pip install matplotlib"
        ) from exc


def _hex_to_ffmpeg(color: str) -> str:
    c = color.lstrip("#")
    if len(c) != 6:
        return "0x0f172a"
    return f"0x{c}"


def _parse_chart_data(chart: dict[str, Any]) -> tuple[list[str], list[float]]:
    from arka.charts.plot import parse_data_arg, parse_numeric_value

    raw = chart.get("data")
    if isinstance(raw, dict):
        labels = [str(x) for x in raw.get("labels") or raw.get("categories") or []]
        values = [parse_numeric_value(x) for x in raw.get("values") or []]
        if len(labels) >= 2 and len(labels) == len(values):
            return labels, values
        raise ValueError("chart.data object needs matching labels and values (min 2)")
    if isinstance(raw, str) and raw.strip():
        return parse_data_arg(raw)
    raise ValueError("chart.data must be a 'Label:1,Label:2' string or {labels, values}")


def _apply_chart_theme(cfg: VideoConfig) -> None:
    plt = _require_matplotlib()
    plt.rcParams.update(
        {
            "figure.facecolor": cfg.bg_color,
            "axes.facecolor": "#161b22",
            "axes.edgecolor": "#30363d",
            "axes.labelcolor": cfg.text_color,
            "text.color": cfg.text_color,
            "xtick.color": "#8b949e",
            "ytick.color": "#8b949e",
            "grid.color": "#21262d",
            "font.family": "sans-serif",
            "font.size": 13,
        }
    )


def _margins(chart_type: str, labels: list[str] | None = None) -> dict[str, float]:
    margins = dict(BASE_MARGINS)
    if chart_type in {"barh", "horizontal"} and labels:
        longest = max(len(label) for label in labels)
        margins["left"] = max(0.26, min(0.42, 0.14 + longest * 0.011))
    if chart_type in {"bar", "grouped_bar", "grouped", "line"}:
        margins["bottom"] = max(margins["bottom"], 0.22)
        if labels:
            longest = max(len(label) for label in labels)
            if longest > 10:
                margins["bottom"] = max(margins["bottom"], 0.24)
    return margins


def _new_chart_figure(cfg: VideoConfig, chart_type: str, labels: list[str] | None = None):
    plt = _require_matplotlib()
    fig_w = cfg.width / DPI
    fig_h = cfg.height / DPI
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=DPI)
    fig.patch.set_facecolor(cfg.bg_color)
    ax.set_facecolor("#161b22")
    fig.subplots_adjust(**_margins(chart_type, labels))
    return fig, ax


def _add_footer(fig, source: str) -> None:
    if source.strip():
        fig.text(0.5, FOOTER_Y, source.strip(), ha="center", fontsize=FOOTER_FONTSIZE, color="#8b949e")


def _save_figure(fig, path: Path) -> Path:
    plt = _require_matplotlib()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def _value_label(val: float, ylabel: str) -> str:
    lower = ylabel.lower()
    if "percent" in lower or ylabel.strip().endswith("%"):
        return f"{val:g}%"
    if val <= 100 and "billion" not in lower and "trillion" not in lower and "usd" not in lower:
        return f"{val:g}"
    abs_val = abs(val)
    if abs_val >= 1e12:
        scaled = val / 1e12
        return f"${scaled:.1f}T" if abs(scaled - round(scaled)) > 0.05 else f"${scaled:,.0f}T"
    if abs_val >= 1e9:
        scaled = val / 1e9
        return f"${scaled:.1f}B" if abs(scaled - round(scaled)) > 0.05 else f"${scaled:,.0f}B"
    if abs_val >= 1e6:
        scaled = val / 1e6
        return f"${scaled:.1f}M" if abs(scaled - round(scaled)) > 0.05 else f"${scaled:,.0f}M"
    if abs_val >= 1e3:
        scaled = val / 1e3
        return f"${scaled:.1f}K" if abs(scaled - round(scaled)) > 0.05 else f"${scaled:,.0f}K"
    if "billion" in lower or "usd" in lower:
        return f"${val:,.0f}"
    return f"{val:g}"


def _render_inline_chart(chart: dict[str, Any], output: Path, cfg: VideoConfig) -> Path:
    _apply_chart_theme(cfg)
    chart_type = str(chart.get("type") or "bar").strip().lower()
    title = str(chart.get("title") or "").strip()
    source = str(chart.get("source") or chart.get("footer") or "").strip()
    ylabel = str(chart.get("ylabel") or chart.get("y_label") or "").strip()

    if chart_type in {"grouped_bar", "grouped"}:
        return _render_grouped_bar(chart, output, cfg)

    labels, values = _parse_chart_data(chart)
    fig, ax = _new_chart_figure(cfg, chart_type, labels)

    if chart_type in {"barh", "horizontal"}:
        pairs = sorted(zip(labels, values), key=lambda item: item[1])
        labels = [p[0] for p in pairs]
        values = [p[1] for p in pairs]
        bars = ax.barh(labels, values, color=ACCENT[: len(labels)], height=0.65)
        ax.set_xlim(0, max(values) * 1.08)
        ax.set_xlabel(ylabel or "Value", labelpad=10)
        ax.tick_params(axis="y", labelsize=11)
        for bar, val in zip(bars, values):
            ax.text(
                bar.get_width() * 0.98,
                bar.get_y() + bar.get_height() / 2,
                _value_label(val, ylabel),
                va="center",
                ha="right",
                fontsize=12,
                color="white",
                fontweight="bold",
            )
        ax.grid(axis="x", alpha=0.25)
    elif chart_type == "pie":
        ax.pie(
            values,
            labels=labels,
            autopct="%1.1f%%",
            colors=ACCENT[: len(labels)],
            startangle=90,
            textprops={"color": cfg.text_color, "fontsize": 12},
            pctdistance=0.75,
            labeldistance=1.08,
        )
    elif chart_type == "line":
        ax.plot(range(len(values)), values, marker="o", linewidth=3, color=ACCENT[0], markersize=10)
        ax.fill_between(range(len(values)), values, alpha=0.12, color=ACCENT[0])
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=12)
        ax.set_ylabel(ylabel or "Value", labelpad=10)
        for idx, val in enumerate(values):
            ax.annotate(_value_label(val, ylabel), (idx, val), textcoords="offset points", xytext=(0, 12), ha="center")
        ax.grid(alpha=0.25)
    else:
        bars = ax.bar(labels, values, color=ACCENT[1], width=0.62)
        ax.set_ylabel(ylabel or "Value", labelpad=10)
        ax.tick_params(axis="x", labelsize=11)
        for bar, val in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                val + max(values) * 0.02,
                _value_label(val, ylabel),
                ha="center",
                fontsize=11,
                fontweight="bold",
            )
        ax.grid(axis="y", alpha=0.25)

    if title:
        ax.set_title(title, fontsize=20, fontweight="bold", pad=16)
    _add_footer(fig, source)
    return _save_figure(fig, output)


def _render_grouped_bar(chart: dict[str, Any], output: Path, cfg: VideoConfig) -> Path:
    categories = [str(x) for x in chart.get("categories") or chart.get("labels") or []]
    series = chart.get("series") or {}
    if not categories or not isinstance(series, dict) or len(series) < 2:
        raise ValueError("grouped_bar chart needs categories and series: {2023: [...], 2026: [...]}")

    series_names = list(series.keys())
    width = 0.34
    x = range(len(categories))
    fig, ax = _new_chart_figure(cfg, "grouped_bar", categories)
    ylabel = str(chart.get("ylabel") or chart.get("y_label") or "Value").strip()
    peak = max(max(float(v) for v in series[name]) for name in series_names)

    for idx, name in enumerate(series_names):
        offset = (idx - (len(series_names) - 1) / 2) * width
        vals = [float(v) for v in series[name]]
        if len(vals) != len(categories):
            raise ValueError(f"series '{name}' length must match categories")
        bars = ax.bar([i + offset for i in x], vals, width, label=str(name), color=ACCENT[idx % len(ACCENT)])
        for bar, val in zip(bars, vals):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                val + peak * 0.03,
                _value_label(val, ylabel),
                ha="center",
                fontsize=10,
                fontweight="bold",
            )

    ax.set_xticks(list(x))
    ax.set_xticklabels(categories, fontsize=12)
    title = str(chart.get("title") or "").strip()
    if title:
        ax.set_title(title, fontsize=20, fontweight="bold", pad=16)
    ax.set_ylabel(ylabel, labelpad=10)
    ax.set_ylim(0, peak * 1.18)
    ax.legend(loc="upper right", fontsize=12)
    ax.grid(axis="y", alpha=0.25)
    _add_footer(fig, str(chart.get("source") or chart.get("footer") or ""))
    return _save_figure(fig, output)


def _fit_image_to_frame(src: Path, output: Path, cfg: VideoConfig) -> Path:
    from PIL import Image

    if not src.is_file():
        raise FileNotFoundError(f"Slide image not found: {src}")
    img = Image.open(src).convert("RGB")
    canvas = Image.new("RGB", (cfg.width, cfg.height), _hex_rgb(cfg.bg_color))
    scale = min(cfg.width / img.width, cfg.height / img.height)
    new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    resized = img.resize(new_size, Image.Resampling.LANCZOS)
    x = (cfg.width - new_size[0]) // 2
    y = (cfg.height - new_size[1]) // 2
    canvas.paste(resized, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)
    return output


def _hex_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) != 6:
        return (15, 23, 42)
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _slide_font_family(style: str) -> str:
    if style == "academic":
        return "serif"
    return "sans-serif"


def _draw_slide_footer(ax, *, palette, slide_index: int, total: int, style: str) -> None:
    if total <= 1:
        return
    ax.text(
        0.96,
        0.04,
        f"{slide_index + 1} / {total}",
        ha="right",
        va="bottom",
        fontsize=10,
        color=palette.muted,
        transform=ax.transAxes,
        fontfamily=_slide_font_family(style),
    )


def _draw_accent_bar(ax, *, palette, y: float, width: float = 0.12, height: float = 0.006) -> None:
    from matplotlib.patches import Rectangle

    ax.add_patch(
        Rectangle(
            (0.5 - width / 2, y),
            width,
            height,
            transform=ax.transAxes,
            facecolor=palette.accent,
            edgecolor="none",
            clip_on=False,
        )
    )


def render_title_slide(
    scene: Scene,
    output: Path,
    cfg: VideoConfig,
    *,
    style: str = "executive",
    theme: str | None = None,
    slide_kind: str = "content",
    topic: str = "",
    slide_index: int = 0,
    total_slides: int = 1,
) -> Path:
    """Render a styled presentation slide (title, section, or content layout)."""
    from arka.media.compose_video import prepare_slide_body, prepare_slide_title
    from arka.media.slide_design import infer_slide_kind, slide_palette, slide_typography

    plt = _require_matplotlib()
    from matplotlib.patches import Rectangle

    _apply_chart_theme(cfg)
    palette = slide_palette(style, theme or "")
    typo = slide_typography(style)
    font_family = _slide_font_family(style)

    kind = slide_kind or infer_slide_kind(scene, index=slide_index, total=total_slides)
    fig, ax = plt.subplots(figsize=(cfg.width / DPI, cfg.height / DPI), dpi=DPI)
    fig.patch.set_facecolor(palette.bg)
    ax.set_facecolor(palette.bg)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    mx = typo.margin_x
    title_lines = prepare_slide_title(scene.title)
    title_text = "\n".join(title_lines) if title_lines else (scene.title or topic or "Presentation")
    body_lines = prepare_slide_body(scene.body or "")
    captions = [str(c).strip() for c in (scene.captions or []) if str(c).strip()][: typo.max_bullets]

    if kind == "title":
        ax.text(
            mx,
            0.62,
            title_text,
            ha="left",
            va="center",
            fontsize=typo.title_size + 8,
            color=palette.text,
            fontweight="bold",
            linespacing=typo.line_spacing,
            transform=ax.transAxes,
            fontfamily=font_family,
        )
        _draw_accent_bar(ax, palette=palette, y=0.54, width=0.14)
        subtitle = "\n".join(body_lines) if body_lines else (topic or "").strip()
        if subtitle and subtitle.lower() != title_text.lower():
            ax.text(
                mx,
                0.46,
                subtitle,
                ha="left",
                va="top",
                fontsize=typo.subtitle_size,
                color=palette.muted,
                linespacing=typo.line_spacing,
                transform=ax.transAxes,
                fontfamily=font_family,
            )
        logo_w, logo_h = 0.10, 0.08
        ax.add_patch(
            Rectangle(
                (0.96 - logo_w, 0.88 - logo_h),
                logo_w,
                logo_h,
                transform=ax.transAxes,
                facecolor=palette.surface,
                edgecolor=palette.muted,
                linewidth=0.8,
                linestyle="--",
                clip_on=False,
            )
        )
        ax.text(
            0.96 - logo_w / 2,
            0.88 - logo_h / 2,
            "LOGO",
            ha="center",
            va="center",
            fontsize=8,
            color=palette.muted,
            transform=ax.transAxes,
            fontfamily=font_family,
        )
    elif kind == "section":
        ax.add_patch(
            Rectangle(
                (0, 0.42),
                1,
                0.16,
                transform=ax.transAxes,
                facecolor=palette.surface,
                edgecolor="none",
                clip_on=False,
            )
        )
        section_title = title_text
        if section_title.lower().startswith("section:"):
            section_title = section_title.split(":", 1)[1].strip() or section_title
        ax.text(
            0.5,
            0.50,
            section_title,
            ha="center",
            va="center",
            fontsize=typo.section_size,
            color=palette.accent,
            fontweight="bold",
            transform=ax.transAxes,
            fontfamily=font_family,
        )
        if body_lines:
            ax.text(
                0.5,
                0.38,
                "\n".join(body_lines),
                ha="center",
                va="top",
                fontsize=typo.subtitle_size,
                color=palette.muted,
                transform=ax.transAxes,
                fontfamily=font_family,
            )
    else:
        y = 0.88
        ax.text(
            mx,
            y,
            title_text,
            ha="left",
            va="top",
            fontsize=typo.title_size,
            color=palette.text,
            fontweight="bold",
            linespacing=typo.line_spacing,
            transform=ax.transAxes,
            fontfamily=font_family,
        )
        _draw_accent_bar(ax, palette=palette, y=y - 0.07, width=0.08)
        y -= 0.12
        if body_lines:
            ax.text(
                mx,
                y,
                "\n".join(body_lines),
                ha="left",
                va="top",
                fontsize=typo.subtitle_size,
                color=palette.muted,
                linespacing=typo.line_spacing,
                transform=ax.transAxes,
                fontfamily=font_family,
            )
            y -= 0.08 * len(body_lines)
        if captions:
            bullet_y = max(0.22, y - 0.04)
            for cap in captions:
                ax.text(
                    mx + 0.02,
                    bullet_y,
                    f"•  {cap}",
                    ha="left",
                    va="top",
                    fontsize=typo.bullet_size,
                    color=palette.bullet,
                    linespacing=typo.line_spacing,
                    transform=ax.transAxes,
                    fontfamily=font_family,
                )
                bullet_y -= 0.07

    _draw_slide_footer(ax, palette=palette, slide_index=slide_index, total=total_slides, style=style)
    return _save_figure(fig, output)


def render_scene_visual(
    scene: Scene,
    work_dir: Path,
    cfg: VideoConfig,
    *,
    index: int,
    style: str = "executive",
    theme: str | None = None,
    topic: str = "",
    total_slides: int = 1,
) -> Path:
    """Build a full-frame PNG for one scene (chart spec, chart file, or slide image)."""
    out = work_dir / f"slide-{index:02d}.png"

    slide_path = scene.slide_image.strip()
    if slide_path:
        return _fit_image_to_frame(Path(slide_path).expanduser(), out, cfg)

    chart_path = scene.chart_path.strip()
    if chart_path:
        return _fit_image_to_frame(Path(chart_path).expanduser(), out, cfg)

    if scene.chart:
        return _render_inline_chart(scene.chart, out, cfg)

    return render_title_slide(
        scene,
        out,
        cfg,
        style=style,
        theme=theme,
        slide_kind=getattr(scene, "slide_kind", "") or "",
        topic=topic,
        slide_index=index,
        total_slides=total_slides,
    )


def static_scene_clip_filter(cfg: VideoConfig) -> str:
    pad = _hex_to_ffmpeg(cfg.bg_color)
    return (
        f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=decrease,"
        f"pad={cfg.width}:{cfg.height}:(ow-iw)/2:(oh-ih)/2:color={pad}"
    )
