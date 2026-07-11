#!/usr/bin/env python3
"""Comprehensive PDF toolkit — merge, split, compress, convert, OCR, and more."""

from __future__ import annotations

import argparse
import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

PDF_EXTS = frozenset({".pdf"})
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
OFFICE_EXTS = frozenset({".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".odp", ".ods", ".rtf", ".txt", ".md", ".html", ".htm"})

_KNOWN_CMDS = frozenset({
    "merge", "split", "compress", "edit", "sign", "convert",
    "images-to-pdf", "pdf-to-images", "extract-images",
    "protect", "unlock", "rotate", "remove-pages", "extract-pages",
    "rearrange", "webpage-to-pdf", "ocr", "watermark", "page-numbers",
    "overlay", "compare", "web-optimize", "redact", "create",
    "parse", "check",
})

CLI_NATIVE_CMDS = (
    "merge", "split", "compress", "edit", "sign", "convert",
    "images-to-pdf", "pdf-to-images", "extract-images",
    "protect", "unlock", "rotate", "remove-pages", "extract-pages",
    "rearrange", "webpage-to-pdf", "ocr", "watermark", "page-numbers",
    "overlay", "compare", "web-optimize", "redact", "create",
)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _default_output_dir() -> Path:
    raw = os.environ.get("PDF_TOOLS_OUTPUT_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.cwd()


def _output_path(input_path: Path | None, suffix: str, explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    base = input_path.stem if input_path else "output"
    return _default_output_dir() / f"{base}{suffix}"


def _require_pypdf():
    try:
        from pypdf import PdfReader, PdfWriter  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "pypdf is required for PDF tools.\n"
            "Install: pip install pypdf  or  pip install 'arka-agent[pdf-tools]'"
        ) from exc


def _require_pillow():
    try:
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required for image PDF operations.\n"
            "Install: pip install Pillow  or  pip install 'arka-agent[pdf-tools]'"
        ) from exc


def _require_reportlab():
    try:
        from reportlab.pdfgen import canvas  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "reportlab is required for create/watermark/page-numbers.\n"
            "Install: pip install reportlab  or  pip install 'arka-agent[pdf-tools]'"
        ) from exc


def _require_pymupdf():
    try:
        import fitz  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "pymupdf is required for this operation.\n"
            "Install: pip install pymupdf  or  pip install 'arka-agent[drawings]'"
        ) from exc


def _parse_page_ranges(spec: str, page_count: int) -> list[int]:
    """Parse '1,3-5,8' into 0-based page indices."""
    spec = (spec or "").strip()
    if not spec or spec.lower() in {"all", "*"}:
        return list(range(page_count))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a else 1
            end = int(b) if b else page_count
            for p in range(start, end + 1):
                if 1 <= p <= page_count:
                    pages.append(p - 1)
        else:
            p = int(part)
            if 1 <= p <= page_count:
                pages.append(p - 1)
    return sorted(set(pages))


def _collect_pdfs(paths: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            files.extend(sorted(p.glob("*.pdf")))
        elif p.is_file():
            files.append(p)
        else:
            raise SystemExit(f"Not found: {p}")
    if not files:
        raise SystemExit("No PDF files found.")
    return files


def merge_pdfs(inputs: Sequence[Path], output: Path) -> Path:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for path in inputs:
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def split_pdf(input_path: Path, output_dir: Path, *, pages_per_file: int = 1) -> list[Path]:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    total = len(reader.pages)
    if pages_per_file < 1:
        pages_per_file = 1
    for start in range(0, total, pages_per_file):
        writer = PdfWriter()
        for idx in range(start, min(start + pages_per_file, total)):
            writer.add_page(reader.pages[idx])
        out = output_dir / f"{input_path.stem}_part{start // pages_per_file + 1:03d}.pdf"
        with out.open("wb") as fh:
            writer.write(fh)
        saved.append(out)
    return saved


def compress_pdf(input_path: Path, output: Path, *, quality: int = 60) -> Path:
    """Compress PDF — tries pymupdf rewrite, falls back to pypdf stream compression."""
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fitz

        doc = fitz.open(str(input_path))
        doc.save(str(output), garbage=4, deflate=True, clean=True)
        doc.close()
        return output
    except ImportError:
        pass
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)
    with output.open("wb") as fh:
        writer.write(fh)
    _ = quality  # reserved for future image recompression
    return output


def edit_pdf(
    input_path: Path,
    output: Path,
    *,
    text: str,
    page: int = 1,
    x: float = 72,
    y: float = 72,
    font_size: int = 12,
) -> Path:
    """Add visible text overlay to a PDF page."""
    _require_pypdf()
    _require_reportlab()
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas as rl_canvas

    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    for idx, pg in enumerate(reader.pages):
        if idx == page - 1:
            media = pg.mediabox
            pw, ph = float(media.width), float(media.height)
            buf = io.BytesIO()
            c = rl_canvas.Canvas(buf, pagesize=(pw, ph))
            c.setFont("Helvetica", font_size)
            c.drawString(x, y, text)
            c.save()
            buf.seek(0)
            from pypdf import PdfReader as OverlayReader

            overlay = OverlayReader(buf)
            pg.merge_page(overlay.pages[0])
        writer.add_page(pg)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def sign_pdf(
    input_path: Path,
    output: Path,
    *,
    signature_image: Path,
    page: int = -1,
    x: float = 72,
    y: float = 72,
    width: float = 150,
    height: float = 50,
) -> Path:
    """Overlay a signature image on a PDF page (visual, not cryptographic)."""
    _require_pypdf()
    _require_pillow()
    from PIL import Image
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas as rl_canvas

    reader = PdfReader(str(input_path))
    page_idx = page if page > 0 else len(reader.pages)
    page_idx = min(max(page_idx, 1), len(reader.pages)) - 1

    img = Image.open(signature_image).convert("RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    media = reader.pages[page_idx].mediabox
    pw, ph = float(media.width), float(media.height)

    overlay_buf = io.BytesIO()
    c = rl_canvas.Canvas(overlay_buf, pagesize=(pw, ph))
    c.drawImage(signature_image, x, y, width=width, height=height, mask="auto")
    c.save()
    overlay_buf.seek(0)

    from pypdf import PdfReader as OverlayReader

    overlay = OverlayReader(overlay_buf)
    writer = PdfWriter()
    for idx, pg in enumerate(reader.pages):
        if idx == page_idx:
            pg.merge_page(overlay.pages[0])
        writer.add_page(pg)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def _soffice_convert(input_path: Path, target_ext: str, output_dir: Path) -> Path:
    soffice = _which("soffice") or _which("libreoffice")
    if not soffice:
        raise SystemExit(
            "Office → PDF requires LibreOffice (soffice).\n"
            "Install: brew install --cask libreoffice  or  sudo apt install libreoffice"
        )
    proc = subprocess.run(
        [soffice, "--headless", "--convert-to", target_ext, "--outdir", str(output_dir), str(input_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"LibreOffice conversion failed: {(proc.stderr or proc.stdout).strip()}")
    out = output_dir / f"{input_path.stem}.{target_ext}"
    if not out.is_file():
        raise SystemExit(f"Expected output not found: {out}")
    return out


def convert_to_pdf(input_path: Path, output: Path) -> Path:
    ext = input_path.suffix.lower()
    if ext == ".pdf":
        shutil.copy2(input_path, output)
        return output
    if ext in OFFICE_EXTS or ext in {".txt", ".md", ".html", ".htm", ".rtf"}:
        with tempfile.TemporaryDirectory() as tmp:
            out = _soffice_convert(input_path, "pdf", Path(tmp))
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(out, output)
        return output
    raise SystemExit(f"Unsupported input format for PDF conversion: {ext}")


def convert_from_pdf(input_path: Path, output: Path, *, target: str) -> Path:
    target = target.lstrip(".").lower()
    if target in {"png", "jpg", "jpeg", "webp"}:
        images = pdf_to_images(input_path, output.parent, fmt=target)
        return images[0] if len(images) == 1 else output
    with tempfile.TemporaryDirectory() as tmp:
        out = _soffice_convert(input_path, target, Path(tmp))
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, output)
        return output


def images_to_pdf(images: Sequence[Path], output: Path) -> Path:
    _require_pillow()
    from PIL import Image

    pil_images: list[Image.Image] = []
    for path in images:
        img = Image.open(path)
        if img.mode in {"RGBA", "P"}:
            img = img.convert("RGB")
        pil_images.append(img)
    if not pil_images:
        raise SystemExit("No images provided.")
    output.parent.mkdir(parents=True, exist_ok=True)
    first, *rest = pil_images
    first.save(output, save_all=True, append_images=rest, resolution=150.0)
    return output


def pdf_to_images(
    input_path: Path,
    output_dir: Path,
    *,
    fmt: str = "png",
    dpi: int = 150,
) -> list[Path]:
    fmt = fmt.lower().lstrip(".")
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        import fitz

        doc = fitz.open(str(input_path))
        saved: list[Path] = []
        for idx in range(len(doc)):
            page = doc.load_page(idx)
            pix = page.get_pixmap(dpi=dpi)
            out = output_dir / f"{input_path.stem}_page{idx + 1:03d}.{fmt}"
            pix.save(str(out))
            saved.append(out)
        doc.close()
        return saved
    except ImportError:
        pass
    if _which("pdftoppm"):
        prefix = output_dir / input_path.stem
        proc = subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png" if fmt == "png" else "-jpeg", str(input_path), str(prefix)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(f"pdftoppm failed: {proc.stderr.strip()}")
        return sorted(output_dir.glob(f"{input_path.stem}*.{fmt}"))
    raise SystemExit(
        "PDF → images requires pymupdf or poppler (pdftoppm).\n"
        "Install: pip install pymupdf  or  brew install poppler"
    )


def extract_pdf_images(input_path: Path, output_dir: Path) -> list[Path]:
    _require_pymupdf()
    import fitz

    doc = fitz.open(str(input_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for page_idx in range(len(doc)):
        for img_idx, img in enumerate(doc.get_page_images(page_idx)):
            xref = img[0]
            base = doc.extract_image(xref)
            ext = base.get("ext", "png")
            out = output_dir / f"{input_path.stem}_p{page_idx + 1:03d}_img{img_idx + 1:03d}.{ext}"
            out.write_bytes(base["image"])
            saved.append(out)
    doc.close()
    return saved


def protect_pdf(input_path: Path, output: Path, *, password: str) -> Path:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(password)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def unlock_pdf(input_path: Path, output: Path, *, password: str) -> Path:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    if reader.is_encrypted:
        if not reader.decrypt(password):
            raise SystemExit("Incorrect password or cannot decrypt PDF.")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def rotate_pdf(input_path: Path, output: Path, *, degrees: int, pages: str = "all") -> Path:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    indices = set(_parse_page_ranges(pages, len(reader.pages)))
    writer = PdfWriter()
    for idx, page in enumerate(reader.pages):
        if idx in indices:
            page.rotate(degrees)
        writer.add_page(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def remove_pages(input_path: Path, output: Path, *, pages: str) -> Path:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    remove = set(_parse_page_ranges(pages, len(reader.pages)))
    writer = PdfWriter()
    for idx, page in enumerate(reader.pages):
        if idx not in remove:
            writer.add_page(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def extract_pages(input_path: Path, output: Path, *, pages: str) -> Path:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    keep = _parse_page_ranges(pages, len(reader.pages))
    writer = PdfWriter()
    for idx in keep:
        writer.add_page(reader.pages[idx])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def rearrange_pages(input_path: Path, output: Path, *, order: str) -> Path:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    indices = _parse_page_ranges(order, len(reader.pages))
    writer = PdfWriter()
    for idx in indices:
        writer.add_page(reader.pages[idx])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def webpage_to_pdf(url: str, output: Path, *, wait_ms: int = 2000) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if _which("wkhtmltopdf"):
        proc = subprocess.run(
            ["wkhtmltopdf", url, str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and output.is_file():
            return output
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(wait_ms)
            page.pdf(path=str(output), format="A4", print_background=True)
            browser.close()
        return output
    except ImportError:
        pass
    try:
        import weasyprint

        weasyprint.HTML(url=url).write_pdf(str(output))
        return output
    except ImportError:
        pass
    raise SystemExit(
        "Webpage → PDF requires one of: playwright, weasyprint, or wkhtmltopdf.\n"
        "Install: pip install playwright && playwright install chromium\n"
        "     or: pip install weasyprint\n"
        "     or: brew install wkhtmltopdf"
    )


def ocr_pdf(input_path: Path, output: Path, *, language: str = "eng") -> Path:
    ocrmypdf = _which("ocrmypdf")
    if ocrmypdf:
        output.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [ocrmypdf, "--language", language, "--skip-text", str(input_path), str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return output
        raise SystemExit(f"ocrmypdf failed: {proc.stderr.strip()}")
    try:
        import ocrmypdf as _ocr

        output.parent.mkdir(parents=True, exist_ok=True)
        _ocr.ocr(str(input_path), str(output), language=language, skip_text=True)
        return output
    except ImportError:
        pass
    raise SystemExit(
        "PDF OCR requires ocrmypdf.\n"
        "Install: pip install ocrmypdf  (also needs tesseract: brew install tesseract)"
    )


def add_watermark(
    input_path: Path,
    output: Path,
    *,
    text: str,
    opacity: float = 0.3,
    angle: int = 45,
) -> Path:
    _require_pypdf()
    _require_reportlab()
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas as rl_canvas

    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    for pg in reader.pages:
        media = pg.mediabox
        pw, ph = float(media.width), float(media.height)
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=(pw, ph))
        c.setFillAlpha(opacity)
        c.setFont("Helvetica-Bold", 48)
        c.saveState()
        c.translate(pw / 2, ph / 2)
        c.rotate(angle)
        c.drawCentredString(0, 0, text)
        c.restoreState()
        c.save()
        buf.seek(0)
        from pypdf import PdfReader as OverlayReader

        overlay = OverlayReader(buf)
        pg.merge_page(overlay.pages[0])
        writer.add_page(pg)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def add_page_numbers(input_path: Path, output: Path, *, position: str = "bottom-center") -> Path:
    _require_pypdf()
    _require_reportlab()
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas as rl_canvas

    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    total = len(reader.pages)
    for num, pg in enumerate(reader.pages, start=1):
        media = pg.mediabox
        pw, ph = float(media.width), float(media.height)
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=(pw, ph))
        c.setFont("Helvetica", 10)
        label = f"{num} / {total}"
        if position == "bottom-right":
            c.drawRightString(pw - 36, 24, label)
        elif position == "top-center":
            c.drawCentredString(pw / 2, ph - 24, label)
        else:
            c.drawCentredString(pw / 2, 24, label)
        c.save()
        buf.seek(0)
        from pypdf import PdfReader as OverlayReader

        overlay = OverlayReader(buf)
        pg.merge_page(overlay.pages[0])
        writer.add_page(pg)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def overlay_pdfs(base_path: Path, overlay_path: Path, output: Path) -> Path:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    base = PdfReader(str(base_path))
    over = PdfReader(str(overlay_path))
    writer = PdfWriter()
    for idx, page in enumerate(base.pages):
        if idx < len(over.pages):
            page.merge_page(over.pages[idx])
        writer.add_page(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output


def compare_pdfs(path_a: Path, path_b: Path) -> dict:
    _require_pypdf()
    from pypdf import PdfReader

    a = PdfReader(str(path_a))
    b = PdfReader(str(path_b))
    result = {
        "pages_a": len(a.pages),
        "pages_b": len(b.pages),
        "text_diff_pages": [],
        "identical_text": True,
    }
    max_pages = max(len(a.pages), len(b.pages))
    for idx in range(max_pages):
        text_a = a.pages[idx].extract_text() if idx < len(a.pages) else ""
        text_b = b.pages[idx].extract_text() if idx < len(b.pages) else ""
        if (text_a or "").strip() != (text_b or "").strip():
            result["identical_text"] = False
            result["text_diff_pages"].append(idx + 1)
    return result


def web_optimize_pdf(input_path: Path, output: Path) -> Path:
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)
    try:
        writer.add_metadata({"/Linearized": "true"})
    except Exception:
        pass
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    try:
        import fitz

        doc = fitz.open(str(output))
        tmp = output.with_suffix(".opt.pdf")
        doc.save(str(tmp), garbage=4, deflate=True, clean=True)
        doc.close()
        shutil.move(str(tmp), str(output))
    except ImportError:
        pass
    return output


def redact_pdf(
    input_path: Path,
    output: Path,
    *,
    text: str | None = None,
    rect: str | None = None,
    page: int = 1,
) -> Path:
    _require_pymupdf()
    import fitz

    doc = fitz.open(str(input_path))
    page_idx = min(max(page, 1), len(doc)) - 1
    pg = doc.load_page(page_idx)
    if text:
        hits = pg.search_for(text)
        for rect_obj in hits:
            pg.add_redact_annot(rect_obj, fill=(0, 0, 0))
    elif rect:
        parts = [float(x) for x in rect.split(",")]
        if len(parts) != 4:
            raise SystemExit("Rect must be x0,y0,x1,y1")
        pg.add_redact_annot(fitz.Rect(*parts), fill=(0, 0, 0))
    else:
        raise SystemExit("Provide --text or --rect for redaction.")
    pg.apply_redactions()
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output))
    doc.close()
    return output


def create_pdf(
    output: Path,
    *,
    text: str | None = None,
    html: str | None = None,
    html_file: Path | None = None,
    pages: int = 1,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if html_file:
        html = html_file.read_text(encoding="utf-8")
    if html:
        try:
            import weasyprint

            weasyprint.HTML(string=html).write_pdf(str(output))
            return output
        except ImportError:
            pass
        _require_reportlab()
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import Paragraph, SimpleDocTemplate
        from reportlab.lib.styles import getSampleStyleSheet

        doc = SimpleDocTemplate(str(output), pagesize=letter)
        styles = getSampleStyleSheet()
        story = [Paragraph(html.replace("\n", "<br/>"), styles["Normal"])]
        doc.build(story)
        return output
    _require_reportlab()
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as rl_canvas

    c = rl_canvas.Canvas(str(output), pagesize=letter)
    w, h = letter
    for i in range(max(1, pages)):
        if text:
            c.setFont("Helvetica", 12)
            c.drawString(72, h - 72, text)
        c.showPage()
    c.save()
    return output


# ---------------------------------------------------------------------------
# Natural language routing
# ---------------------------------------------------------------------------

def _extract_pdf_paths(text: str) -> list[str]:
    return re.findall(r"\S+\.pdf\b", text, flags=re.I)


def nl_to_argv(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    low = t.lower()

    if low in {"check", "pdf tools check", "pdf check"}:
        return ["check"]

    if re.search(r"(?i)\bmerge\b.*\bpdf", t) or re.search(r"(?i)\bcombine\b.*\bpdf", t):
        pdfs = _extract_pdf_paths(t)
        if len(pdfs) >= 2:
            return ["merge", *pdfs]
        return ["merge"]

    if re.search(r"(?i)\bsplit\b.*\bpdf", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        return ["split", m.group(1)] if m else ["split"]

    if re.search(r"(?i)\bcompress\b.*\bpdf|\bpdf\b.*\bcompress", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        return ["compress", m.group(1)] if m else ["compress"]

    if re.search(r"(?i)\bpdf\b.*\bto\b.*\bimages?\b|\bimages?\b.*\bfrom\b.*\bpdf", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        return ["pdf-to-images", m.group(1)] if m else ["pdf-to-images"]

    if re.search(r"(?i)\bimages?\b.*\bto\b.*\bpdf", t):
        imgs = re.findall(r"\S+\.(?:png|jpe?g|webp|gif|bmp|tiff?)\b", t, flags=re.I)
        return ["images-to-pdf", *imgs] if imgs else ["images-to-pdf"]

    if re.search(r"(?i)\bunlock\b.*\bpdf|\bdecrypt\b.*\bpdf|\bremove\b.*\bpassword\b.*\bpdf", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        pw = re.search(r"(?i)password\s+['\"]?(\S+)['\"]?", t)
        argv = ["unlock", m.group(1)] if m else ["unlock"]
        if pw:
            argv.extend(["--password", pw.group(1)])
        return argv

    if re.search(r"(?i)\bprotect\b.*\bpdf|\bencrypt\b.*\bpdf", t) or (
        re.search(r"(?i)\bpdf\b.*\bpassword\b", t) and not re.search(r"(?i)\bunlock\b|\bdecrypt\b|\bremove\b", t)
    ):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        pw = re.search(r"(?i)password\s+['\"]?(\S+)['\"]?", t)
        argv = ["protect", m.group(1)] if m else ["protect"]
        if pw:
            argv.extend(["--password", pw.group(1)])
        return argv

    if re.search(r"(?i)\brotate\b.*\bpdf", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        deg = re.search(r"(?i)(\d+)\s*degrees?", t)
        argv = ["rotate", m.group(1)] if m else ["rotate"]
        if deg:
            argv.extend(["--degrees", deg.group(1)])
        return argv

    if re.search(r"(?i)\bocr\b.*\bpdf|\bpdf\b.*\bocr\b|\bsearchable\b.*\bpdf", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        return ["ocr", m.group(1)] if m else ["ocr"]

    if re.search(r"(?i)\bwatermark\b.*\bpdf", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        wm = re.search(r'(?i)watermark\s+["\']?([^"\']+)["\']?', t)
        argv = ["watermark", m.group(1)] if m else ["watermark"]
        if wm:
            argv.extend(["--text", wm.group(1).strip()])
        return argv

    if re.search(r"(?i)\bpage\s*numbers?\b.*\bpdf|\bnumber\b.*\bpages?\b.*\bpdf", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        return ["page-numbers", m.group(1)] if m else ["page-numbers"]

    if re.search(r"(?i)\bwebpage\b.*\bpdf|\burl\b.*\bpdf|\bwebsite\b.*\bpdf", t):
        url = re.search(r"(https?://\S+)", t)
        return ["webpage-to-pdf", url.group(1)] if url else ["webpage-to-pdf"]

    if re.search(r"(?i)\bcompare\b.*\bpdf", t):
        pdfs = _extract_pdf_paths(t)
        return ["compare", *pdfs[:2]] if len(pdfs) >= 2 else ["compare"]

    if re.search(r"(?i)\bcreate\b.*\bpdf|\bblank\b.*\bpdf", t):
        txt = re.search(r'(?i)text\s+["\']?([^"\']+)["\']?', t)
        argv = ["create"]
        if txt:
            argv.extend(["--text", txt.group(1).strip()])
        return argv

    if re.search(r"(?i)\bredact\b.*\bpdf", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        txt = re.search(r'(?i)text\s+["\']?([^"\']+)["\']?', t)
        argv = ["redact", m.group(1)] if m else ["redact"]
        if txt:
            argv.extend(["--text", txt.group(1).strip()])
        return argv

    if re.search(r"(?i)\bsign\b.*\bpdf", t):
        m = re.search(r"(?i)(\S+\.pdf)", t)
        sig = re.search(r"(?i)(\S+\.(?:png|jpe?g))\b", t)
        argv = ["sign", m.group(1)] if m else ["sign"]
        if sig:
            argv.extend(["--image", sig.group(1)])
        return argv

    # Direct command passthrough
    parts = shlex.split(t)
    if parts and parts[0].lower() in _KNOWN_CMDS:
        return parts

    return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Comprehensive PDF toolkit (merge, split, compress, OCR, …).",
    )
    sub = p.add_subparsers(dest="cmd")

    def add_out(sp, default_suffix: str):
        sp.add_argument("-o", "--output", help="Output file or directory")

    p_merge = sub.add_parser("merge", help="Merge multiple PDFs")
    p_merge.add_argument("inputs", nargs="+", help="PDF files or directories")
    add_out(p_merge, "_merged.pdf")
    p_merge.set_defaults(func=cmd_merge)

    p_split = sub.add_parser("split", help="Split PDF into parts")
    p_split.add_argument("input")
    add_out(p_split, "_parts")
    p_split.add_argument("--pages-per-file", type=int, default=1)
    p_split.set_defaults(func=cmd_split)

    p_compress = sub.add_parser("compress", help="Compress PDF")
    p_compress.add_argument("input")
    add_out(p_compress, "_compressed.pdf")
    p_compress.set_defaults(func=cmd_compress)

    p_edit = sub.add_parser("edit", help="Add text overlay to a PDF")
    p_edit.add_argument("input", help="Input PDF")
    add_out(p_edit, "_edited.pdf")
    p_edit.add_argument("--text", required=True, help="Text to stamp on the page")
    p_edit.add_argument("--page", type=int, default=1)
    p_edit.add_argument("--x", type=float, default=72)
    p_edit.add_argument("--y", type=float, default=72)
    p_edit.set_defaults(func=cmd_edit)

    p_sign = sub.add_parser("sign", help="Overlay signature image on a PDF")
    p_sign.add_argument("input", help="Input PDF")
    add_out(p_sign, "_signed.pdf")
    p_sign.add_argument("--image", required=True, help="Signature PNG/JPG")
    p_sign.add_argument("--page", type=int, default=-1, help="Page number (-1 = last)")
    p_sign.set_defaults(func=cmd_sign)

    p_convert = sub.add_parser("convert", help="Convert office/doc ↔ PDF")
    p_convert.add_argument("input")
    add_out(p_convert, ".pdf")
    p_convert.add_argument("--to", help="Target format (pdf, docx, png, …)")
    p_convert.set_defaults(func=cmd_convert)

    p_img2pdf = sub.add_parser("images-to-pdf", help="Combine images into PDF")
    p_img2pdf.add_argument("images", nargs="+")
    add_out(p_img2pdf, ".pdf")
    p_img2pdf.set_defaults(func=cmd_images_to_pdf)

    p_pdf2img = sub.add_parser("pdf-to-images", help="Render PDF pages to images")
    p_pdf2img.add_argument("input")
    add_out(p_pdf2img, "_images")
    p_pdf2img.add_argument("--format", default="png")
    p_pdf2img.add_argument("--dpi", type=int, default=150)
    p_pdf2img.set_defaults(func=cmd_pdf_to_images)

    p_extimg = sub.add_parser("extract-images", help="Extract embedded images")
    p_extimg.add_argument("input")
    add_out(p_extimg, "_images")
    p_extimg.set_defaults(func=cmd_extract_images)

    p_protect = sub.add_parser("protect", help="Password-protect PDF")
    p_protect.add_argument("input")
    add_out(p_protect, "_protected.pdf")
    p_protect.add_argument("--password", required=True)
    p_protect.set_defaults(func=cmd_protect)

    p_unlock = sub.add_parser("unlock", help="Remove PDF password")
    p_unlock.add_argument("input")
    add_out(p_unlock, "_unlocked.pdf")
    p_unlock.add_argument("--password", required=True)
    p_unlock.set_defaults(func=cmd_unlock)

    p_rotate = sub.add_parser("rotate", help="Rotate PDF pages")
    p_rotate.add_argument("input")
    add_out(p_rotate, "_rotated.pdf")
    p_rotate.add_argument("--degrees", type=int, default=90)
    p_rotate.add_argument("--pages", default="all")
    p_rotate.set_defaults(func=cmd_rotate)

    p_remove = sub.add_parser("remove-pages", help="Remove pages from PDF")
    p_remove.add_argument("input")
    add_out(p_remove, "_trimmed.pdf")
    p_remove.add_argument("--pages", required=True, help="e.g. 2,5-7")
    p_remove.set_defaults(func=cmd_remove_pages)

    p_extract = sub.add_parser("extract-pages", help="Extract specific pages")
    p_extract.add_argument("input")
    add_out(p_extract, "_extracted.pdf")
    p_extract.add_argument("--pages", required=True)
    p_extract.set_defaults(func=cmd_extract_pages)

    p_rearrange = sub.add_parser("rearrange", help="Reorder PDF pages")
    p_rearrange.add_argument("input", help="Input PDF")
    add_out(p_rearrange, "_rearranged.pdf")
    p_rearrange.add_argument("--order", required=True, help="e.g. 3,1,2")
    p_rearrange.set_defaults(func=cmd_rearrange)

    p_web = sub.add_parser("webpage-to-pdf", help="Convert URL to PDF")
    p_web.add_argument("url")
    add_out(p_web, ".pdf")
    p_web.set_defaults(func=cmd_webpage_to_pdf)

    p_ocr = sub.add_parser("ocr", help="OCR scanned PDF (searchable)")
    p_ocr.add_argument("input")
    add_out(p_ocr, "_ocr.pdf")
    p_ocr.add_argument("--language", default="eng")
    p_ocr.set_defaults(func=cmd_ocr)

    p_wm = sub.add_parser("watermark", help="Add text watermark")
    p_wm.add_argument("input")
    add_out(p_wm, "_watermarked.pdf")
    p_wm.add_argument("--text", required=True)
    p_wm.set_defaults(func=cmd_watermark)

    p_num = sub.add_parser("page-numbers", help="Add page numbers")
    p_num.add_argument("input")
    add_out(p_num, "_numbered.pdf")
    p_num.add_argument("--position", default="bottom-center")
    p_num.set_defaults(func=cmd_page_numbers)

    p_overlay = sub.add_parser("overlay", help="Overlay one PDF on another")
    p_overlay.add_argument("base")
    p_overlay.add_argument("overlay")
    add_out(p_overlay, "_overlay.pdf")
    p_overlay.set_defaults(func=cmd_overlay)

    p_compare = sub.add_parser("compare", help="Compare two PDFs (text content)")
    p_compare.add_argument("pdf_a", help="First PDF")
    p_compare.add_argument("pdf_b", help="Second PDF")
    p_compare.set_defaults(func=cmd_compare)

    p_webopt = sub.add_parser("web-optimize", help="Optimize PDF for web")
    p_webopt.add_argument("input")
    add_out(p_webopt, "_web.pdf")
    p_webopt.set_defaults(func=cmd_web_optimize)

    p_redact = sub.add_parser("redact", help="Redact text or region")
    p_redact.add_argument("input", help="Input PDF")
    add_out(p_redact, "_redacted.pdf")
    p_redact.add_argument("--text")
    p_redact.add_argument("--rect", help="x0,y0,x1,y1")
    p_redact.add_argument("--page", type=int, default=1)
    p_redact.set_defaults(func=cmd_redact)

    p_create = sub.add_parser("create", help="Create blank or text/html PDF")
    add_out(p_create, ".pdf")
    p_create.add_argument("--text")
    p_create.add_argument("--html")
    p_create.add_argument("--html-file")
    p_create.add_argument("--pages", type=int, default=1)
    p_create.set_defaults(func=cmd_create)

    p_parse = sub.add_parser("parse", help="Parse natural language → argv")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Report available PDF backends")
    p_check.set_defaults(func=cmd_check)

    return p


def cmd_merge(args: argparse.Namespace) -> int:
    inputs = _collect_pdfs(args.inputs)
    out = _output_path(inputs[0], "_merged.pdf", args.output)
    saved = merge_pdfs(inputs, out)
    print(f"Saved: {saved}")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out_dir = Path(args.output).expanduser() if args.output else inp.parent / f"{inp.stem}_parts"
    saved = split_pdf(inp, out_dir, pages_per_file=args.pages_per_file)
    for p in saved:
        print(f"Saved: {p}")
    return 0


def cmd_compress(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_compressed.pdf", args.output)
    saved = compress_pdf(inp, out)
    print(f"Saved: {saved}")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_edited.pdf", args.output)
    saved = edit_pdf(inp, out, text=args.text, page=args.page, x=args.x, y=args.y)
    print(f"Saved: {saved}")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_signed.pdf", args.output)
    saved = sign_pdf(inp, out, signature_image=Path(args.image).expanduser(), page=args.page)
    print(f"Saved: {saved}")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    target = (args.to or "pdf").lower().lstrip(".")
    if target == "pdf":
        out = _output_path(inp, ".pdf", args.output)
        saved = convert_to_pdf(inp, out)
    else:
        out = _output_path(inp, f".{target}", args.output)
        saved = convert_from_pdf(inp, out, target=target)
    print(f"Saved: {saved}")
    return 0


def cmd_images_to_pdf(args: argparse.Namespace) -> int:
    images = [Path(p).expanduser() for p in args.images]
    out = _output_path(images[0], ".pdf", args.output)
    saved = images_to_pdf(images, out)
    print(f"Saved: {saved}")
    return 0


def cmd_pdf_to_images(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out_dir = Path(args.output).expanduser() if args.output else inp.parent / f"{inp.stem}_images"
    saved = pdf_to_images(inp, out_dir, fmt=args.format, dpi=args.dpi)
    for p in saved:
        print(f"Saved: {p}")
    return 0


def cmd_extract_images(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out_dir = Path(args.output).expanduser() if args.output else inp.parent / f"{inp.stem}_images"
    saved = extract_pdf_images(inp, out_dir)
    for p in saved:
        print(f"Saved: {p}")
    return 0


def cmd_protect(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_protected.pdf", args.output)
    saved = protect_pdf(inp, out, password=args.password)
    print(f"Saved: {saved}")
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_unlocked.pdf", args.output)
    saved = unlock_pdf(inp, out, password=args.password)
    print(f"Saved: {saved}")
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_rotated.pdf", args.output)
    saved = rotate_pdf(inp, out, degrees=args.degrees, pages=args.pages)
    print(f"Saved: {saved}")
    return 0


def cmd_remove_pages(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_trimmed.pdf", args.output)
    saved = remove_pages(inp, out, pages=args.pages)
    print(f"Saved: {saved}")
    return 0


def cmd_extract_pages(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_extracted.pdf", args.output)
    saved = extract_pages(inp, out, pages=args.pages)
    print(f"Saved: {saved}")
    return 0


def cmd_rearrange(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_rearranged.pdf", args.output)
    saved = rearrange_pages(inp, out, order=args.order)
    print(f"Saved: {saved}")
    return 0


def cmd_webpage_to_pdf(args: argparse.Namespace) -> int:
    out = _output_path(None, ".pdf", args.output) if args.output else _default_output_dir() / "webpage.pdf"
    saved = webpage_to_pdf(args.url, out)
    print(f"Saved: {saved}")
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_ocr.pdf", args.output)
    saved = ocr_pdf(inp, out, language=args.language)
    print(f"Saved: {saved}")
    return 0


def cmd_watermark(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_watermarked.pdf", args.output)
    saved = add_watermark(inp, out, text=args.text)
    print(f"Saved: {saved}")
    return 0


def cmd_page_numbers(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_numbered.pdf", args.output)
    saved = add_page_numbers(inp, out, position=args.position)
    print(f"Saved: {saved}")
    return 0


def cmd_overlay(args: argparse.Namespace) -> int:
    base = Path(args.base).expanduser()
    over = Path(args.overlay).expanduser()
    out = _output_path(base, "_overlay.pdf", args.output)
    saved = overlay_pdfs(base, over, out)
    print(f"Saved: {saved}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    result = compare_pdfs(Path(args.pdf_a).expanduser(), Path(args.pdf_b).expanduser())
    print(f"Pages: {result['pages_a']} vs {result['pages_b']}")
    if result["identical_text"]:
        print("Text content: identical")
    else:
        print(f"Text differs on pages: {result['text_diff_pages']}")
    return 0


def cmd_web_optimize(args: argparse.Namespace) -> int:
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_web.pdf", args.output)
    saved = web_optimize_pdf(inp, out)
    print(f"Saved: {saved}")
    return 0


def cmd_redact(args: argparse.Namespace) -> int:
    if not args.text and not args.rect:
        raise SystemExit("redact requires --text or --rect")
    inp = Path(args.input).expanduser()
    out = _output_path(inp, "_redacted.pdf", args.output)
    saved = redact_pdf(inp, out, text=args.text, rect=args.rect, page=args.page)
    print(f"Saved: {saved}")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    out = _output_path(None, ".pdf", args.output) if args.output else _default_output_dir() / "created.pdf"
    html_file = Path(args.html_file).expanduser() if args.html_file else None
    saved = create_pdf(out, text=args.text, html=args.html, html_file=html_file, pages=args.pages)
    print(f"Saved: {saved}")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    ok = True
    print("Operations:")
    for cmd in CLI_NATIVE_CMDS:
        print(f"  • {cmd}")
    print("\nBackends:")
    try:
        _require_pypdf()
        print("✓ pypdf (merge, split, protect, rotate, …)")
    except SystemExit:
        print("✗ pypdf — pip install pypdf", file=sys.stderr)
        ok = False
    try:
        _require_pillow()
        print("✓ Pillow (images-to-pdf)")
    except SystemExit:
        print("  Pillow optional — pip install Pillow")
    try:
        _require_reportlab()
        print("✓ reportlab (create, watermark, page-numbers)")
    except SystemExit:
        print("  reportlab optional — pip install reportlab")
    try:
        import fitz  # noqa: F401

        print("✓ pymupdf (pdf-to-images, redact, compress)")
    except ImportError:
        print("  pymupdf optional — pip install pymupdf")
    if _which("soffice") or _which("libreoffice"):
        print("✓ LibreOffice (office ↔ PDF)")
    else:
        print("  LibreOffice optional — office/doc conversion")
    if _which("ocrmypdf"):
        print("✓ ocrmypdf CLI (OCR)")
    else:
        try:
            import ocrmypdf  # noqa: F401

            print("✓ ocrmypdf (OCR)")
        except ImportError:
            print("  ocrmypdf optional — pip install ocrmypdf (+ tesseract)")
    if _which("pdftoppm"):
        print("✓ pdftoppm (pdf-to-images fallback)")
    else:
        print("  pdftoppm optional — brew install poppler")
    if _which("wkhtmltopdf"):
        print("✓ wkhtmltopdf (webpage-to-pdf)")
    else:
        print("  wkhtmltopdf optional — brew install wkhtmltopdf")
    try:
        import playwright  # noqa: F401

        print("✓ playwright (webpage-to-pdf)")
    except ImportError:
        print("  playwright optional — pip install playwright")
    try:
        import weasyprint  # noqa: F401

        print("✓ weasyprint (html/create, webpage-to-pdf)")
    except ImportError:
        print("  weasyprint optional — pip install weasyprint")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    from arka.env import load_env

    load_env()
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in _KNOWN_CMDS and argv[0] not in {"-h", "--help"}:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl
        elif Path(argv[0]).suffix.lower() == ".pdf":
            argv = ["compress", argv[0], *argv[1:]]
        else:
            build_parser().print_help()
            return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
