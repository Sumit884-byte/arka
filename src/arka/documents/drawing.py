#!/usr/bin/env python3
"""Vision analysis for drawings, blueprints, scanned specs, schedules, and contracts."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".heic",
})
PDF_EXTENSION = ".pdf"

DEFAULT_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
)

SYSTEM_PROMPT = """You are an expert at reading architectural, engineering, and construction documents—including blueprints, floor plans, elevations, sections, MEP schematics, specifications, schedules (door/window/finish/Gantt), and scanned contracts.

Analyze the provided image(s) and extract structured insights beyond basic OCR:
- Dimensions, scales, room names, grid lines, symbols, and legend entries
- Schedules and tables embedded in the drawing (quantities, marks, types)
- Contract clauses, parties, dates, payment terms, and obligations when visible
- Conflicts, missing information, ambiguities, and items needing field verification

Be precise. State uncertainty when symbols or text are unclear. Use bullet points and markdown tables when helpful."""

_KNOWN_CMDS = frozenset({"ask", "parse", "formats", "help"})


def _api_key() -> str:
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _model_list() -> list[str]:
    models: list[str] = []
    env_model = os.environ.get("DRAWING_MODEL", "").strip()
    if env_model:
        models.append(env_model)
    for m in DEFAULT_MODELS:
        if m not in models:
            models.append(m)
    return models


def _max_pages() -> int:
    try:
        return max(1, int(os.environ.get("DRAWING_MAX_PAGES", "8")))
    except ValueError:
        return 8


def _max_edge() -> int:
    try:
        return max(512, int(os.environ.get("DRAWING_MAX_EDGE", "2048")))
    except ValueError:
        return 2048


def _require_pillow():
    try:
        from PIL import Image  # noqa: F401

        return True
    except ImportError:
        raise SystemExit(
            "Pillow is required for drawing analysis.\n"
            "Install: pip install Pillow\n"
            "Or: pip install 'arka-agent[drawings]'"
        ) from None


def _require_pymupdf():
    try:
        import fitz  # noqa: F401

        return True
    except ImportError:
        raise SystemExit(
            "PyMuPDF is required to analyze PDF drawings.\n"
            "Install: pip install pymupdf\n"
            "Or: pip install 'arka-agent[drawings]'\n"
            "Tip: export pages to PNG from CAD if you cannot install pymupdf."
        ) from None


def _parse_page_spec(spec: str | None, page_count: int) -> list[int]:
    if not spec or spec.strip().lower() in {"all", "*"}:
        limit = min(page_count, _max_pages())
        return list(range(limit))
    pages: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            start = max(1, int(a.strip()))
            end = min(page_count, int(b.strip()))
            pages.update(range(start - 1, end))
        else:
            idx = int(chunk.strip())
            if 1 <= idx <= page_count:
                pages.add(idx - 1)
    out = sorted(p for p in pages if 0 <= p < page_count)
    return out[: _max_pages()]


def _resize_png(png_bytes: bytes) -> bytes:
    _require_pillow()
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    max_edge = _max_edge()
    w, h = img.size
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _load_image_file(path: Path) -> list[tuple[bytes, str, str]]:
    data = path.read_bytes()
    png = _resize_png(data) if path.suffix.lower() != ".png" else _resize_png(data)
    return [(png, "image/png", path.name)]


def _pdf_to_images(path: Path, pages: str | None) -> list[tuple[bytes, str, str]]:
    _require_pymupdf()
    import fitz

    doc = fitz.open(path)
    try:
        indices = _parse_page_spec(pages, len(doc))
        if not indices:
            raise SystemExit(f"No valid pages in range for {path.name} ({len(doc)} pages)")
        out: list[tuple[bytes, str, str]] = []
        zoom = float(os.environ.get("DRAWING_PDF_ZOOM", "2.0"))
        matrix = fitz.Matrix(zoom, zoom)
        for i in indices:
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png = _resize_png(pix.tobytes("png"))
            out.append((png, "image/png", f"{path.name} p{i + 1}"))
        return out
    finally:
        doc.close()


def _pdftoppm_fallback(path: Path, pages: str | None) -> list[tuple[bytes, str, str]]:
    if not shutil_which("pdftoppm"):
        return []
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "page"
        cmd = ["pdftoppm", "-png", "-r", os.environ.get("DRAWING_PDF_DPI", "200"), str(path), str(prefix)]
        if pages and pages != "all":
            first = pages.split(",")[0].split("-")[0].strip()
            if first.isdigit():
                cmd = ["pdftoppm", "-png", "-f", first, "-l", first, "-r", "200", str(path), str(prefix)]
        subprocess.run(cmd, check=False, capture_output=True)
        images = sorted(Path(tmp).glob("page*.png"))
        if not images:
            return []
        out = []
        for img in images[: _max_pages()]:
            out.append((_resize_png(img.read_bytes()), "image/png", f"{path.name} {img.stem}"))
        return out


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def load_images(path: Path, *, pages: str | None = None) -> list[tuple[bytes, str, str]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return _load_image_file(path)
    if ext == PDF_EXTENSION:
        try:
            return _pdf_to_images(path, pages)
        except SystemExit:
            raise
        except Exception:
            fallback = _pdftoppm_fallback(path, pages)
            if fallback:
                return fallback
            _require_pymupdf()
    raise SystemExit(
        f"Unsupported file '{path.name}'. Use PDF or image ({', '.join(sorted(IMAGE_EXTENSIONS))})."
    )


def _gemini_analyze(
    images: list[tuple[bytes, str, str]],
    question: str,
    *,
    model: str,
    api_key: str,
) -> str:
    parts: list[dict] = [{"text": question.strip() or "Summarize key insights from this document."}]
    for data, mime, label in images:
        parts.append({"text": f"[{label}]"})
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(model, safe='')}:generateContent?key={urllib.parse.quote(api_key, safe='')}"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise SystemExit(f"Gemini vision error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Network error calling Gemini: {exc}") from exc

    candidates = payload.get("candidates") or []
    if not candidates:
        raise SystemExit(f"No response from Gemini: {json.dumps(payload)[:300]}")
    content = candidates[0].get("content") or {}
    text_parts = [
        p.get("text", "")
        for p in content.get("parts") or []
        if isinstance(p, dict) and p.get("text")
    ]
    answer = "\n".join(text_parts).strip()
    if not answer:
        raise SystemExit("Empty response from vision model.")
    return answer


def analyze_file(
    path: str | Path,
    question: str,
    *,
    pages: str | None = None,
) -> str:
    api_key = _api_key()
    if not api_key:
        raise SystemExit(
            "GEMINI_API_KEY or GOOGLE_API_KEY required for drawing analysis (Gemini vision).\n"
            "Add to ~/.config/arka/.env or ~/.config/fish/.env"
        )
    images = load_images(Path(path), pages=pages)
    last_err = ""
    for model in _model_list():
        try:
            return _gemini_analyze(images, question, model=model, api_key=api_key)
        except SystemExit as exc:
            last_err = str(exc)
            if "404" in last_err or "not found" in last_err.lower():
                continue
            raise
        except Exception as exc:
            last_err = str(exc)
            continue
    raise SystemExit(last_err or "Vision analysis failed for all Gemini models.")


def _extract_path(text: str) -> str | None:
    m = re.search(r'(?P<q>["\']?)(?P<p>(?:~|/|\./|\.\./)[^\s"\']+|[^\s"\']+\.(?:pdf|png|jpe?g|webp|tiff?|bmp|gif))\1', text, re.I)
    if m:
        return m.group("p").strip("'\"")
    m = re.search(
        r"\b([\w./~-]+\.(?:pdf|png|jpe?g|webp|tiff?|bmp|gif))\b",
        text,
        re.I,
    )
    if m:
        return m.group(1)
    return None


def _strip_drawing_words(text: str) -> str:
    t = text.strip()
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:analyze|analyse|review|inspect|read|extract(?:\s+insights)?\s+from|"
        r"interpret|look\s+at|check|study)\s+(?:this\s+|the\s+|my\s+)?",
        "",
        t,
    )
    t = re.sub(
        r"(?i)\b(?:drawing|blueprint|floor\s+plan|site\s+plan|elevation|section|schematic|"
        r"architectural|MEP|as[- ]built|construction\s+drawing|plan\s+set|shop\s+drawing)\b",
        " ",
        t,
    )
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_doc_and_question(text: str) -> tuple[str | None, str]:
    raw = text.strip()
    path = _extract_path(raw)
    if not path:
        return None, _strip_drawing_words(raw) or raw

    rest = raw
    rest = re.sub(re.escape(path), " ", rest, count=1, flags=re.I)
    rest = _strip_drawing_words(rest)
    rest = re.sub(r"(?i)^(?:from|in|on|of)\s+", "", rest).strip()
    if not rest:
        rest = "Summarize key insights, dimensions, schedules, and notable clauses."
    return path, rest


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    low = t.lower()
    drawing_words = re.search(
        r"(?i)\b(drawing|blueprint|floor\s+plan|site\s+plan|elevation|section|schematic|"
        r"architectural|MEP|as[- ]built|plan\s+set|shop\s+drawing|visual\s+spec|"
        r"scanned\s+(?:contract|drawing|plan)|construction\s+drawing)\b",
        t,
    )
    path = _extract_path(t)
    has_image = bool(path and Path(path).expanduser().suffix.lower() in IMAGE_EXTENSIONS | {PDF_EXTENSION})

    if not drawing_words and not has_image:
        return []

    doc, question = parse_doc_and_question(t)
    if not doc:
        return []
    argv = ["ask", doc, question]
    pages_m = re.search(r"(?i)\b(?:pages?|page)\s+([\d,\-]+|\*)\b", t)
    if pages_m:
        argv = ["ask", "--pages", pages_m.group(1), doc, question]
    return argv


def cmd_ask(args: argparse.Namespace) -> int:
    answer = analyze_file(args.file, " ".join(args.question), pages=args.pages)
    print(answer)
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_formats(_args: argparse.Namespace) -> int:
    print("Images:", ", ".join(sorted(IMAGE_EXTENSIONS)))
    print("PDF: rendered to images via pymupdf (or pdftoppm fallback)")
    print("Requires: GEMINI_API_KEY + pip install Pillow pymupdf")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Vision analysis for drawings, blueprints, schedules, and scanned contracts",
    )
    sub = p.add_subparsers(dest="cmd")

    p_ask = sub.add_parser("ask", help="Analyze a drawing PDF or image")
    p_ask.add_argument("--pages", default=None, help="PDF pages: 1, 1-3, 1,3,5 or all")
    p_ask.add_argument("file", help="Path to PDF or image")
    p_ask.add_argument("question", nargs="+", help="What to extract or analyze")
    p_ask.set_defaults(func=cmd_ask)

    p_parse = sub.add_parser("parse", help="Parse natural language → drawing_ask args (internal)")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    sub.add_parser("formats", help="Supported file types").set_defaults(func=cmd_formats)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in _KNOWN_CMDS:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl
        else:
            print("Could not parse drawing request. Try:", file=sys.stderr)
            print('  drawing_ask plan.pdf "extract door schedule and room dimensions"', file=sys.stderr)
            print('  arka analyze floor plan.png list all annotations', file=sys.stderr)
            return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if not func:
        parser.print_help()
        return 0
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
