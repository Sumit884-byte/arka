"""Generate an interactive quiz website around a media asset."""
from __future__ import annotations

import argparse
import html
from pathlib import Path


def convert(source: str, output: str | None = None, title: str | None = None) -> Path:
    media = Path(source).expanduser().resolve()
    if not media.is_file():
        raise ValueError("source must be an existing media file")
    ext = media.suffix.lower()
    tag = "img" if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else "audio" if ext in {".mp3", ".wav", ".ogg"} else "video" if ext in {".mp4", ".webm", ".mov"} else "iframe"
    src = html.escape(media.name, quote=True)
    if tag == "img":
        embed = f"<img src='{src}' alt='Quiz media'>"
    elif tag in {"audio", "video"}:
        embed = f"<{tag} src='{src}' controls></{tag}>"
    else:
        embed = f"<iframe src='{src}' title='Quiz media'></iframe>"
    page_title = html.escape(title or media.stem.replace("_", " ").title())
    document = f"""<!doctype html><meta charset='utf-8'><title>{page_title} quiz</title><style>body{{font:16px system-ui;max-width:800px;margin:2rem auto;padding:1rem}}img,video,iframe{{max-width:100%;width:100%;max-height:480px}}.q{{padding:1rem 0;border-bottom:1px solid #ddd}}button{{padding:.6rem 1rem}}</style><h1>{page_title}</h1><section>{embed}</section><form id='quiz'><div class='q'><b>Question 1</b><p>What is the most important detail in this media?</p><input required placeholder='Write your answer'></div><button>Check answers</button></form><p id='result'></p><script>quiz.onsubmit=e=>{{e.preventDefault();result.textContent='Quiz submitted. Add validated answers to score this question.'}}</script>"""
    target = Path(output).expanduser().resolve() if output else media.with_name(media.stem + "-quiz.html")
    target.write_text(document, encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka media-quiz")
    parser.add_argument("source")
    parser.add_argument("--output")
    parser.add_argument("--title")
    args = parser.parse_args(argv)
    try:
        print(convert(args.source, args.output, args.title))
        return 0
    except (OSError, ValueError) as exc:
        print(f"media-quiz: {exc}")
        return 2
