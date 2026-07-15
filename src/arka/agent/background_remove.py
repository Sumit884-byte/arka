"""Remove image backgrounds with the optional local rembg backend."""
from __future__ import annotations
import argparse
from pathlib import Path

def remove_background(source: str, output: str | None = None) -> Path:
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"Image not found: {src}")
    try:
        from rembg import remove
    except ImportError as exc:
        raise RuntimeError("Install background removal with: pip install 'arka-agent[vision]'") from exc
    dest = Path(output).expanduser() if output else src.with_name(f"{src.stem}-no-bg.png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(remove(src.read_bytes()))
    return dest

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Remove an image background")
    p.add_argument("source")
    p.add_argument("-o", "--output")
    args = p.parse_args(argv)
    try:
        print(remove_background(args.source, args.output))
    except (FileNotFoundError, RuntimeError) as exc:
        p.error(str(exc))
    return 0
