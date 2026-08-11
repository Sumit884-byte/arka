#!/usr/bin/env python3
"""OCR over local images and scanned PDFs — MCP arka_ocr and dispatch arka_ocr."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from pathlib import Path
from typing import Any

from arka.integrations.mcp_local_files import LOCAL_FILE_TOOL_NOTICE, require_local_path

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
_PDF_SUFFIXES = frozenset({".pdf"})


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _block_dict(block: Any) -> dict[str, Any]:
    return {
        "text": block.text,
        "x_pct": block.x_pct,
        "y_pct": block.y_pct,
        "w_pct": block.w_pct,
        "h_pct": block.h_pct,
        "conf": block.conf,
    }


def extract_image_payload(
    path: str | Path,
    *,
    with_blocks: bool = True,
    with_zones: bool = False,
) -> dict[str, Any]:
    """Extract OCR text (and optional blocks) from a local image file."""
    image = require_local_path(str(path), kind="file", label="path")
    if image.suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError(
            f"unsupported image format {image.suffix!r}; "
            f"supported: {', '.join(sorted(_IMAGE_SUFFIXES))} — {LOCAL_FILE_TOOL_NOTICE}"
        )
    from arka.vision.ocr import extract_blocks, ocr_install_hint, spatial_zones

    data = image.read_bytes()
    result = extract_blocks(data, _guess_mime(image))
    payload: dict[str, Any] = {
        "path": str(image),
        "engine": result.engine,
        "plain_text": result.plain_text,
        "image_width": result.image_width,
        "image_height": result.image_height,
        "local_files_required": True,
        "agent_rules": {
            "incremental_verify": (
                "Demo on one local file first; if it succeeds, try a second; only then report verified. "
                "Do not wait for full batch logs."
            ),
        },
    }
    if not result.plain_text and result.engine in {"none", "disabled"}:
        payload["hint"] = ocr_install_hint()
    if with_blocks:
        payload["blocks"] = [_block_dict(block) for block in result.blocks]
    if with_zones and result.blocks:
        payload["spatial_zones"] = spatial_zones(result.blocks)
    return payload


def pdf_ocr_payload(
    path: str | Path,
    *,
    output: str | Path | None = None,
    language: str = "eng",
) -> dict[str, Any]:
    """OCR a scanned PDF into a searchable PDF on the local filesystem."""
    source = require_local_path(str(path), kind="file", label="path")
    if source.suffix.lower() not in _PDF_SUFFIXES:
        raise ValueError(f"pdf_ocr requires a .pdf file, got {source.suffix!r} — {LOCAL_FILE_TOOL_NOTICE}")
    from arka.pdf.tools import ocr_pdf

    out = Path(output).expanduser() if output else source.with_name(f"{source.stem}_ocr.pdf")
    out = out.resolve()
    ocr_pdf(source, out, language=language or "eng")
    return {
        "input": str(source),
        "output": str(out),
        "language": language or "eng",
        "local_files_required": True,
        "agent_rules": {
            "incremental_verify": (
                "Demo on one local file first; if it succeeds, try a second; only then report verified. "
                "Do not wait for full batch logs."
            ),
        },
    }


def ocr_payload(
    path: str | Path,
    *,
    mode: str = "auto",
    output: str | Path | None = None,
    language: str = "eng",
    with_blocks: bool = True,
    with_zones: bool = False,
) -> dict[str, Any]:
    """Route OCR by file type: images -> text/blocks, PDFs -> searchable PDF."""
    resolved = require_local_path(str(path), kind="file", label="path")
    ext = resolved.suffix.lower()
    action = (mode or "auto").strip().lower()
    if action == "auto":
        action = "pdf" if ext in _PDF_SUFFIXES else "extract"
    if action in {"extract", "image", "text"}:
        return extract_image_payload(
            resolved,
            with_blocks=with_blocks,
            with_zones=with_zones,
        )
    if action in {"pdf", "searchable"}:
        return pdf_ocr_payload(resolved, output=output, language=language)
    raise ValueError("mode must be auto, extract, or pdf")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arka_ocr", description="OCR local images and scanned PDFs")
    sub = parser.add_subparsers(dest="cmd")

    extract = sub.add_parser("extract", help="Extract text from a local image")
    extract.add_argument("path")
    extract.add_argument("--no-blocks", action="store_true")
    extract.add_argument("--zones", action="store_true")

    pdf = sub.add_parser("pdf", help="Make a scanned PDF searchable")
    pdf.add_argument("path")
    pdf.add_argument("-o", "--output")
    pdf.add_argument("--language", default="eng")

    auto = sub.add_parser("auto", help="Auto-detect image vs PDF OCR")
    auto.add_argument("path")
    auto.add_argument("-o", "--output")
    auto.add_argument("--language", default="eng")
    auto.add_argument("--no-blocks", action="store_true")
    auto.add_argument("--zones", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "extract":
            payload = extract_image_payload(
                args.path,
                with_blocks=not args.no_blocks,
                with_zones=args.zones,
            )
        elif args.cmd == "pdf":
            payload = pdf_ocr_payload(args.path, output=args.output, language=args.language)
        elif args.cmd == "auto":
            path = require_local_path(args.path, kind="file", label="path")
            ext = path.suffix.lower()
            if ext in _PDF_SUFFIXES:
                payload = pdf_ocr_payload(path, output=args.output, language=args.language)
            else:
                payload = extract_image_payload(
                    path,
                    with_blocks=not args.no_blocks,
                    with_zones=args.zones,
                )
        else:
            parser.print_help()
            return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
