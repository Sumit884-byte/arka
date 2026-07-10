#!/usr/bin/env python3
"""Render text or images as ASCII art in the terminal."""

from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_FONT = "standard"
ASCII_CHARS = "@%#*+=-:. "
_IMAGE_EXT = r"(?:jpg|jpeg|png|gif|webp|bmp|tiff|tif)"

# Minimal 5-row block font (A–Z, 0–9, space) when figlet/pyfiglet unavailable.
_BLOCK_FONT: dict[str, list[str]] = {
    " ": ["     ", "     ", "     ", "     ", "     "],
    "0": [" ### ", "#   #", "#  ##", "# # #", " ### "],
    "1": ["  #  ", " ##  ", "  #  ", "  #  ", " ### "],
    "2": [" ### ", "#   #", "   # ", "  #  ", "#####"],
    "3": [" ### ", "    #", " ### ", "    #", " ### "],
    "4": [" #  #", "#  # ", "#####", "   # ", "   # "],
    "5": ["#####", "#    ", "#### ", "    #", "#### "],
    "6": [" ### ", "#    ", "#### ", "#   #", " ### "],
    "7": ["#####", "   # ", "  #  ", " #   ", " #   "],
    "8": [" ### ", "#   #", " ### ", "#   #", " ### "],
    "9": [" ### ", "#   #", " ####", "    #", " ### "],
    "A": [" ### ", "#   #", "#####", "#   #", "#   #"],
    "B": ["#### ", "#   #", "#### ", "#   #", "#### "],
    "C": [" ### ", "#   #", "#    ", "#   #", " ### "],
    "D": ["#### ", "#   #", "#   #", "#   #", "#### "],
    "E": ["#####", "#    ", "#### ", "#    ", "#####"],
    "F": ["#####", "#    ", "#### ", "#    ", "#    "],
    "G": [" ### ", "#    ", "#  ##", "#   #", " ### "],
    "H": ["#   #", "#   #", "#####", "#   #", "#   #"],
    "I": [" ### ", "  #  ", "  #  ", "  #  ", " ### "],
    "J": ["  ###", "   # ", "   # ", "#  # ", " ##  "],
    "K": ["#   #", "#  # ", "###  ", "#  # ", "#   #"],
    "L": ["#    ", "#    ", "#    ", "#    ", "#####"],
    "M": ["#   #", "## ##", "# # #", "#   #", "#   #"],
    "N": ["#   #", "##  #", "# # #", "#  ##", "#   #"],
    "O": [" ### ", "#   #", "#   #", "#   #", " ### "],
    "P": ["#### ", "#   #", "#### ", "#    ", "#    "],
    "Q": [" ### ", "#   #", "#   #", "#  ##", " ### "],
    "R": ["#### ", "#   #", "#### ", "#  # ", "#   #"],
    "S": [" ####", "#    ", " ### ", "    #", "#### "],
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  "],
    "U": ["#   #", "#   #", "#   #", "#   #", " ### "],
    "V": ["#   #", "#   #", "#   #", " # # ", "  #  "],
    "W": ["#   #", "#   #", "# # #", "## ##", "#   #"],
    "X": ["#   #", " # # ", "  #  ", " # # ", "#   #"],
    "Y": ["#   #", " # # ", "  #  ", "  #  ", "  #  "],
    "Z": ["#####", "   # ", "  #  ", " #   ", "#####"],
}


def _is_ascii_art_request(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.search(rf"(?i)\b(?:from|of)\s+.+\.{_IMAGE_EXT}\b", t):
        return True
    if re.search(rf"(?i)\b.+\.{_IMAGE_EXT}\s+(?:to|into)\s+ascii", t):
        return True
    return bool(
        re.search(
            r"(?i)(?:^|\b)(?:make|create|show|print|render|draw)\s+(?:an?\s+)?ascii\s+(?:art|banner|text)\b",
            t,
        )
        or re.search(r"(?i)(?:^|\b)ascii\s+(?:art|banner)\b", t)
        or re.search(r"(?i)(?:^|\b)figlet\b", t)
        or re.match(r"(?i)^ascii\s+\S", t)
    )


def _extract_text_prompt(text: str) -> str:
    t = text.strip()
    for pat in (
        r"(?i)^(?:make|create|show|print|render|draw)\s+(?:an?\s+)?ascii\s+(?:art|banner|text)\s+(?:of|for|with|say(?:ing)?|that\s+says)?\s*",
        r"(?i)^ascii\s+(?:art|banner)\s+(?:of|for|with|say(?:ing)?|that\s+says)?\s*",
        r"(?i)^figlet\s+",
        r"(?i)^ascii\s+",
    ):
        t = re.sub(pat, "", t).strip()
    return t.strip("'\"")


def _extract_image_path(text: str) -> str:
    t = text.strip()
    m = re.search(rf"(?i)(?:from|of)\s+([^\s'\"]+\.{_IMAGE_EXT})\b", t)
    if m:
        return m.group(1)
    m = re.search(rf"(?i)([^\s'\"]+\.{_IMAGE_EXT})\s+(?:to|into)\s+ascii", t)
    if m:
        return m.group(1)
    return ""


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_ascii_art_request(t):
        return []

    img = _extract_image_path(t)
    if img:
        argv = ["--from-image", img]
        m = re.search(r"(?i)--width\s+(\d+)", t)
        if m:
            argv.extend(["--width", m.group(1)])
        return argv

    prompt = _extract_text_prompt(t)
    m = re.search(r"(?i)(?:font|style)\s+([a-z0-9_-]+)", t)
    if m:
        prompt = re.sub(r"(?i)\s*(?:font|style)\s+[a-z0-9_-]+\s*$", "", prompt).strip()
    if not prompt:
        return []

    argv = [prompt]
    if m:
        argv[:0] = ["--font", m.group(1)]
    return argv


def _render_pyfiglet(text: str, font: str) -> str | None:
    try:
        import pyfiglet
    except ImportError:
        return None
    try:
        return pyfiglet.figlet_format(text, font=font)
    except Exception:
        try:
            return pyfiglet.figlet_format(text, font=DEFAULT_FONT)
        except Exception:
            return None


def _render_system_figlet(text: str, font: str) -> str | None:
    exe = shutil.which("figlet")
    if not exe:
        return None
    for f in (font, DEFAULT_FONT):
        try:
            proc = subprocess.run(
                [exe, "-f", f, text],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def _render_npx_figlet(text: str) -> str | None:
    if not shutil.which("npx"):
        return None
    try:
        proc = subprocess.run(
            ["npx", "--yes", "figlet-cli", text],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _render_block_fallback(text: str) -> str:
    rows = [""] * 5
    for ch in text.upper():
        glyph = _BLOCK_FONT.get(ch, _BLOCK_FONT.get("?"))
        if glyph is None:
            glyph = ["  ?  ", " # # ", "  #  ", " # # ", "  ?  "]
        for i, line in enumerate(glyph):
            rows[i] += line + " "
    return "\n".join(rows).rstrip() + "\n"


def render_text(text: str, font: str = DEFAULT_FONT) -> str:
    text = text.strip()
    if not text:
        raise ValueError("empty text")
    for fn in (
        lambda: _render_pyfiglet(text, font),
        lambda: _render_system_figlet(text, font),
        lambda: _render_npx_figlet(text),
    ):
        out = fn()
        if out:
            return out if out.endswith("\n") else out + "\n"
    return _render_block_fallback(text)


def image_to_ascii(path: Path, width: int = 80) -> str:
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required for image-to-ASCII.\n"
            "Install: pip install Pillow\n"
            "Or: pip install 'arka-agent[vision]'"
        ) from exc

    if not path.is_file():
        raise SystemExit(f"Image not found: {path}")

    width = max(20, min(width, 200))
    img = Image.open(path).convert("L")
    aspect = img.height / img.width if img.width else 1
    height = max(1, int(width * aspect * 0.55))
    img = img.resize((width, height))

    lines: list[str] = []
    pixels = img.load()
    for y in range(height):
        row = []
        for x in range(width):
            lum = pixels[x, y] if pixels is not None else 0
            idx = int(lum / 256 * len(ASCII_CHARS))
            idx = min(idx, len(ASCII_CHARS) - 1)
            row.append(ASCII_CHARS[idx])
        lines.append("".join(row))
    return "\n".join(lines) + "\n"


def render_and_output(
    *,
    text: str = "",
    font: str = DEFAULT_FONT,
    from_image: str = "",
    width: int = 80,
    output: str = "",
) -> int:
    if from_image:
        art = image_to_ascii(Path(from_image).expanduser(), width=width)
    else:
        if not text.strip():
            print("Usage: ascii_art <text> [--font NAME] [-o path]", file=sys.stderr)
            print("       ascii_art --from-image photo.jpg [--width 80]", file=sys.stderr)
            return 1
        art = render_text(text, font=font)

    print(art, end="" if art.endswith("\n") else "\n")

    if output:
        out = Path(output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(art, encoding="utf-8")
        print(f"Saved: {out}")

    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Render ASCII art (figlet / pyfiglet / image)")
    sub = p.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="Parse natural language → ascii_art args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "parse":
        args = build_parser().parse_args(argv)
        return args.func(args)

    if argv and argv[0] in {"-h", "--help", "help"}:
        build_parser().print_help()
        return 0

    nl = nl_to_argv(" ".join(argv))
    if nl and not any(a.startswith("-") for a in argv[:2]):
        argv = nl

    parser = argparse.ArgumentParser(description="Render ASCII art (figlet / pyfiglet / image)")
    parser.add_argument("text", nargs="*", help="Text to render")
    parser.add_argument("-f", "--font", default=DEFAULT_FONT, help="Figlet font name")
    parser.add_argument("--from-image", metavar="PATH", help="Convert image to ASCII")
    parser.add_argument("--width", type=int, default=80, help="Image ASCII width (default 80)")
    parser.add_argument("-o", "--output", help="Save output to file (also prints to terminal)")
    args = parser.parse_args(argv)

    if args.from_image:
        return render_and_output(from_image=args.from_image, width=args.width, output=args.output or "")

    text = " ".join(args.text).strip()
    return render_and_output(text=text, font=args.font, output=args.output or "")


if __name__ == "__main__":
    raise SystemExit(main())
