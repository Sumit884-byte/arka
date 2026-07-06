"""OCR helpers for describe_image (layer 1 — exact text + coordinates)."""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OcrBlock:
    text: str
    x_pct: float  # center x, 0–100
    y_pct: float  # center y, 0–100
    w_pct: float = 0.0
    h_pct: float = 0.0
    conf: float = 0.0


@dataclass(frozen=True)
class OcrResult:
    blocks: tuple[OcrBlock, ...]
    plain_text: str
    engine: str
    image_width: int = 0
    image_height: int = 0


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _ocr_enabled() -> bool:
    return _env("DESCRIBE_IMAGE_OCR", "1") not in {"0", "false", "no", "off"}


def _coords_enabled() -> bool:
    return _env("DESCRIBE_IMAGE_OCR_COORDS", "1") not in {"0", "false", "no", "off"}


def _image_suffix(mime: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/tiff": ".tiff",
        "image/bmp": ".bmp",
    }
    return mapping.get(mime.lower(), ".png")


def _clean_token(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _clean_ocr_text(text: str) -> str:
    lines = [_clean_token(ln) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not re.fullmatch(r"[\W_]+", ln)]
    return "\n".join(lines).strip()


def _pct(value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * value / total, 1)


def _block_from_box(
    text: str,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    img_w: float,
    img_h: float,
    conf: float = 0.0,
) -> OcrBlock | None:
    text = _clean_token(text)
    if not text or text.isspace():
        return None
    cx = left + width / 2
    cy = top + height / 2
    return OcrBlock(
        text=text,
        x_pct=_pct(cx, img_w),
        y_pct=_pct(cy, img_h),
        w_pct=_pct(width, img_w),
        h_pct=_pct(height, img_h),
        conf=conf,
    )


def _merge_blocks(blocks: list[OcrBlock]) -> list[OcrBlock]:
    """Join split tokens like '33' + '%' when they are adjacent."""
    if not blocks:
        return []
    merged: list[OcrBlock] = []
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if i + 1 < len(blocks):
            nxt = blocks[i + 1]
            dx = abs(cur.x_pct - nxt.x_pct)
            dy = abs(cur.y_pct - nxt.y_pct)
            if nxt.text in {"%", "°"} and dx < 8 and dy < 4:
                merged.append(
                    OcrBlock(
                        text=f"{cur.text}{nxt.text}",
                        x_pct=cur.x_pct,
                        y_pct=cur.y_pct,
                        w_pct=cur.w_pct + nxt.w_pct,
                        h_pct=max(cur.h_pct, nxt.h_pct),
                        conf=min(cur.conf or 100, nxt.conf or 100),
                    )
                )
                i += 2
                continue
        merged.append(cur)
        i += 1
    return merged


def _blocks_to_plain(blocks: list[OcrBlock]) -> str:
    return _clean_ocr_text("\n".join(b.text for b in blocks))


def _parse_tesseract_tsv(tsv: str) -> tuple[list[OcrBlock], int, int]:
    blocks: list[OcrBlock] = []
    img_w = img_h = 0
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for row in reader:
        try:
            level = int(row.get("level") or 0)
        except ValueError:
            continue
        if level == 1:
            try:
                img_w = int(float(row.get("width") or 0))
                img_h = int(float(row.get("height") or 0))
            except ValueError:
                pass
            continue
        if level != 5:
            continue
        text = row.get("text") or ""
        try:
            conf = float(row.get("conf") or -1)
            left = float(row.get("left") or 0)
            top = float(row.get("top") or 0)
            width = float(row.get("width") or 0)
            height = float(row.get("height") or 0)
        except ValueError:
            continue
        if conf >= 0 and conf < 40:
            continue
        if not img_w or not img_h:
            continue
        block = _block_from_box(text, left, top, width, height, img_w=img_w, img_h=img_h, conf=conf)
        if block:
            blocks.append(block)
    blocks.sort(key=lambda b: (b.y_pct, b.x_pct))
    return _merge_blocks(blocks), img_w, img_h


def _tesseract_blocks(data: bytes, mime: str) -> OcrResult | None:
    tesseract = shutil.which("tesseract") or _env("TESSERACT_CMD")
    if not tesseract:
        return None
    lang = _env("DESCRIBE_IMAGE_OCR_LANG", "eng")
    psm = _env("DESCRIBE_IMAGE_OCR_PSM", "11")
    with tempfile.TemporaryDirectory() as tmp:
        img_path = Path(tmp) / f"image{_image_suffix(mime)}"
        img_path.write_bytes(data)
        if _coords_enabled():
            cmd = [tesseract, str(img_path), "stdout", "-l", lang, "--psm", psm, "tsv"]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
            except (OSError, subprocess.TimeoutExpired):
                proc = None
            if proc and (proc.stdout or "").strip():
                blocks, w, h = _parse_tesseract_tsv(proc.stdout)
                if blocks:
                    return OcrResult(tuple(blocks), _blocks_to_plain(blocks), "tesseract", w, h)
        cmd = [tesseract, str(img_path), "stdout", "-l", lang, "--psm", psm]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = _clean_ocr_text(proc.stdout or "") if proc else ""
        if not text:
            return None
        return OcrResult((), text, "tesseract")


def _pytesseract_blocks(data: bytes, mime: str) -> OcrResult | None:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        lang = _env("DESCRIBE_IMAGE_OCR_LANG", "eng")
        config = f"--psm {_env('DESCRIBE_IMAGE_OCR_PSM', '11')}"
        if _coords_enabled():
            raw = pytesseract.image_to_data(img, lang=lang, config=config, output_type=pytesseract.Output.DICT)
            blocks: list[OcrBlock] = []
            n = len(raw.get("text") or [])
            for i in range(n):
                text = _clean_token(str(raw["text"][i]))
                if not text:
                    continue
                try:
                    conf = float(raw["conf"][i])
                except (TypeError, ValueError):
                    conf = -1
                if conf >= 0 and conf < 40:
                    continue
                block = _block_from_box(
                    text,
                    float(raw["left"][i]),
                    float(raw["top"][i]),
                    float(raw["width"][i]),
                    float(raw["height"][i]),
                    img_w=img.width,
                    img_h=img.height,
                    conf=conf,
                )
                if block:
                    blocks.append(block)
            blocks = _merge_blocks(sorted(blocks, key=lambda b: (b.y_pct, b.x_pct)))
            if blocks:
                return OcrResult(tuple(blocks), _blocks_to_plain(blocks), "pytesseract", img.width, img.height)
        text = pytesseract.image_to_string(img, lang=lang, config=config)
        text = _clean_ocr_text(text)
        return OcrResult((), text, "pytesseract") if text else None
    except Exception:
        return None


def _ocrmac_blocks(data: bytes, mime: str) -> OcrResult | None:
    if sys.platform != "darwin":
        return None
    try:
        from ocrmac import ocrmac
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        annotations = ocrmac.OCR(img).recognize()
        blocks: list[OcrBlock] = []
        for item in annotations:
            text = ""
            bbox = None
            conf = 0.0
            if isinstance(item, (list, tuple)):
                if item:
                    text = str(item[0]).strip()
                if len(item) > 1:
                    try:
                        conf = float(item[1])
                    except (TypeError, ValueError):
                        pass
                if len(item) > 2:
                    bbox = item[2]
            elif isinstance(item, str):
                text = item.strip()
            if not text:
                continue
            if bbox and len(bbox) >= 4:
                # ocrmac bbox often normalized 0–1: [x1, y1, x2, y2]
                x1, y1, x2, y2 = (float(b) for b in bbox[:4])
                if max(x1, x2) <= 1.5 and max(y1, y2) <= 1.5:
                    left, top = x1 * img.width, y1 * img.height
                    width, height = (x2 - x1) * img.width, (y2 - y1) * img.height
                else:
                    left, top, width, height = x1, y1, x2 - x1, y2 - y1
                block = _block_from_box(
                    text, left, top, width, height, img_w=img.width, img_h=img.height, conf=conf
                )
                if block:
                    blocks.append(block)
            else:
                blocks.append(OcrBlock(text=text, x_pct=0.0, y_pct=0.0, conf=conf))
        blocks = _merge_blocks(blocks)
        plain = _blocks_to_plain(blocks)
        if not plain:
            return None
        return OcrResult(tuple(blocks), plain, "ocrmac", img.width, img.height)
    except Exception:
        return None


def extract_blocks(data: bytes, mime: str) -> OcrResult:
    """Return OCR blocks with coordinates when available."""
    if not _ocr_enabled():
        return OcrResult((), "", "disabled")
    engines = []
    if sys.platform == "darwin":
        engines.append(_ocrmac_blocks)
    engines.extend([_tesseract_blocks, _pytesseract_blocks])
    for fn in engines:
        try:
            result = fn(data, mime)
        except Exception:
            result = None
        if result and (result.blocks or result.plain_text):
            return result
    return OcrResult((), "", "none")


def extract_text(data: bytes, mime: str) -> tuple[str, str]:
    """Return (plain text, engine_name)."""
    result = extract_blocks(data, mime)
    return result.plain_text, result.engine


def format_blocks_compact(blocks: tuple[OcrBlock, ...], engine: str = "") -> str:
    if not blocks:
        return ""
    tag = f" ({engine})" if engine else ""
    items = [f'{b.text}@{_compass_short(b.x_pct, b.y_pct)}' for b in blocks if b.text.strip()]
    if not items:
        return ""
    return f"  OCR{tag}: " + " · ".join(items)


def _compass_short(x_pct: float, y_pct: float) -> str:
    dx, dy = x_pct - 50.0, y_pct - 50.0
    v = "↑" if dy < -8 else "↓" if dy > 8 else "·"
    h = "←" if dx < -8 else "→" if dx > 8 else ""
    return f"{v}{h}" if h or v != "·" else "·"


def format_blocks_for_display(blocks: tuple[OcrBlock, ...]) -> str:
    if not blocks:
        return ""
    lines = ["Text map (x%, y% = center of word):"]
    for b in blocks:
        conf = f", conf={b.conf:.0f}" if b.conf else ""
        lines.append(f'  ({b.x_pct:g}, {b.y_pct:g}) "{b.text}"{conf}')
    return "\n".join(lines)


def format_blocks_for_vision(blocks: tuple[OcrBlock, ...]) -> str:
    """Compact coordinate map for the vision model prompt."""
    if not blocks:
        return ""
    parts = [f'({b.x_pct:g},{b.y_pct:g})"{b.text}"' for b in blocks]
    return "OCR coordinate map (x%,y% → text): " + " | ".join(parts)


def spatial_zones(blocks: tuple[OcrBlock, ...]) -> str:
    """Rough top/center/bottom grouping to speed spatial reasoning."""
    if not blocks:
        return ""
    zones: dict[str, list[str]] = {"top": [], "middle": [], "bottom": []}
    for b in blocks:
        if b.y_pct < 33:
            zones["top"].append(b.text)
        elif b.y_pct < 66:
            zones["middle"].append(b.text)
        else:
            zones["bottom"].append(b.text)
    lines = []
    for name, words in zones.items():
        if words:
            lines.append(f"  {name}: {', '.join(words)}")
    return "Spatial zones:\n" + "\n".join(lines) if lines else ""


def ocr_install_hint() -> str:
    if sys.platform == "darwin":
        return (
            "OCR not available. Install one of:\n"
            "  brew install tesseract\n"
            "  pip install ocrmac Pillow"
        )
    return (
        "OCR not available. Install one of:\n"
        "  apt/brew install tesseract\n"
        "  pip install pytesseract Pillow"
    )
