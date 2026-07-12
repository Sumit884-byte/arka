#!/usr/bin/env python3
"""Render QR codes in the terminal (offline, cross-platform)."""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
import shutil
import subprocess
import sys


def _render_qrencode(text: str) -> bool:
    exe = shutil.which("qrencode")
    if not exe:
        return False
    try:
        subprocess.run([exe, "-t", "ansiutf8", text], check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _render_python(text: str) -> bool:
    try:
        import qrcode
    except ImportError:
        return False
    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    return True



def ascii_payload(text: str) -> dict[str, object]:
    """Structured QR ASCII art for MCP / automation clients."""
    payload = (text or "").strip()
    if not payload:
        raise ValueError("text is required")
    try:
        import qrcode
    except ImportError as exc:
        raise RuntimeError(
            "qrcode package missing. Install with: pip install qrcode"
        ) from exc
    code = qrcode.QRCode(border=1)
    code.add_data(payload)
    code.make(fit=True)
    buf = io.StringIO()
    with redirect_stdout(buf):
        code.print_ascii(invert=True)
    matrix = code.get_matrix()
    return {
        "text": payload,
        "ascii": buf.getvalue().rstrip("\n"),
        "version": code.version,
        "modules": len(matrix),
        "engine": "qrcode",
    }


def render_terminal(text: str) -> int:
    text = text.strip()
    if not text:
        print("Usage: arka_qr <text-or-url>", file=sys.stderr)
        return 1
    if _render_qrencode(text) or _render_python(text):
        return 0
    print(
        "Failed to generate QR code. Install the Python package (pip install qrcode) "
        "or system qrencode (macOS: brew install qrencode; Linux: sudo apt install qrencode).",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a QR code in the terminal")
    parser.add_argument("text", nargs="+", help="Text or URL to encode")
    args = parser.parse_args(argv)
    return render_terminal(" ".join(args.text))


if __name__ == "__main__":
    raise SystemExit(main())
