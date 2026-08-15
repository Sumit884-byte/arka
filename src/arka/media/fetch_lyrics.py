#!/usr/bin/env python3
"""Fetch song lyrics and optionally translate or remix with music generation."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from arka.agent.survival_lang import google_translate, resolve_lang_code

UA = "arka-fetch-lyrics/1.0"
LRCLIB_SEARCH = "https://lrclib.net/api/search"
LYRICS_OVH = "https://api.lyrics.ovh/v1/{artist}/{title}"
CHUNK_CHARS = 1500


def _default_output_dir() -> Path:
    env_dir = os.environ.get("LYRICS_OUTPUT_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / "Music" / "arka-lyrics"


def _slug(text: str, *, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())[:limit].strip("-")
    return slug or "lyrics"


def _http_json(url: str, *, timeout: int = 20) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _http_text(url: str, *, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_song_query(text: str) -> tuple[str, str]:
    """Return (artist, title) from common phrasing."""
    t = text.strip()
    if not t:
        raise ValueError("song query is required")

    m = re.search(r"(?i)^(.+?)\s+by\s+(.+?)(?:\s+(?:translate|to|into|and)\b.*)?$", t)
    if m:
        return m.group(2).strip(), m.group(1).strip()

    m = re.search(r"(?i)^(.+?)\s*[-–—]\s*(.+)$", t)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    if " - " in t:
        artist, title = t.split(" - ", 1)
        return artist.strip(), title.strip()

    raise ValueError(f"Could not parse artist/title from: {text!r} (try 'Title by Artist')")


def search_lrclib(artist: str, title: str) -> dict[str, object] | None:
    query = urllib.parse.quote(f"{artist} {title}".strip())
    try:
        data = _http_json(f"{LRCLIB_SEARCH}?q={query}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    if not isinstance(data, list) or not data:
        return None

    artist_l = artist.lower()
    title_l = title.lower()
    best: dict[str, object] | None = None
    best_score = -1
    for item in data:
        if not isinstance(item, dict):
            continue
        item_artist = str(item.get("artistName") or "").lower()
        item_title = str(item.get("trackName") or item.get("name") or "").lower()
        score = 0
        if artist_l and artist_l in item_artist:
            score += 2
        if title_l and title_l in item_title:
            score += 2
        if item_artist == artist_l:
            score += 1
        if item_title == title_l:
            score += 1
        if score > best_score:
            best_score = score
            best = item
    return best or (data[0] if isinstance(data[0], dict) else None)


def fetch_lyrics_ovh(artist: str, title: str) -> str:
    artist_enc = urllib.parse.quote(artist.strip())
    title_enc = urllib.parse.quote(title.strip())
    url = LYRICS_OVH.format(artist=artist_enc, title=title_enc)
    try:
        data = _http_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(f"No lyrics found for {title!r} by {artist!r}") from exc
        raise RuntimeError(f"Lyrics provider error ({exc.code})") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Lyrics provider unavailable: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected lyrics response")
    lyrics = str(data.get("lyrics") or "").strip()
    if not lyrics:
        raise RuntimeError(f"No lyrics found for {title!r} by {artist!r}")
    return lyrics


def fetch_lyrics(artist: str, title: str) -> dict[str, object]:
    artist = artist.strip()
    title = title.strip()
    if not artist or not title:
        raise ValueError("artist and title are required")

    provider = "lrclib"
    lyrics = ""
    album = ""
    duration: int | None = None

    hit = search_lrclib(artist, title)
    if hit:
        lyrics = str(hit.get("plainLyrics") or hit.get("syncedLyrics") or "").strip()
        album = str(hit.get("albumName") or "")
        raw_duration = hit.get("duration")
        if isinstance(raw_duration, (int, float)):
            duration = int(raw_duration)
        artist = str(hit.get("artistName") or artist)
        title = str(hit.get("trackName") or hit.get("name") or title)

    if not lyrics:
        provider = "lyrics.ovh"
        lyrics = fetch_lyrics_ovh(artist, title)

    return {
        "artist": artist,
        "title": title,
        "album": album,
        "duration": duration,
        "provider": provider,
        "lyrics": lyrics,
        "char_count": len(lyrics),
        "line_count": len([line for line in lyrics.splitlines() if line.strip()]),
    }


def _chunk_text(text: str, *, max_chars: int = CHUNK_CHARS) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(para) <= max_chars:
            current = para
            continue
        for line in para.splitlines():
            line = line.strip()
            if not line:
                continue
            candidate = f"{current}\n{line}".strip() if current else line
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = line
    if current:
        chunks.append(current)
    return chunks


def translate_lyrics(
    lyrics: str,
    *,
    target_lang: str,
    source_lang: str = "auto",
) -> dict[str, object]:
    target = resolve_lang_code(target_lang)
    if not target:
        raise ValueError(f"Unsupported target language: {target_lang!r}")
    source = resolve_lang_code(source_lang) if source_lang != "auto" else "auto"

    chunks = _chunk_text(lyrics)
    if not chunks:
        raise ValueError("No lyrics text to translate")

    translated_parts: list[str] = []
    for chunk in chunks:
        translated_parts.append(google_translate(chunk, target=target, source=source))
    translated = "\n\n".join(part.strip() for part in translated_parts if part.strip())
    if not translated:
        raise RuntimeError("Translation returned empty text")

    return {
        "target_lang": target,
        "source_lang": source,
        "lyrics": translated,
        "char_count": len(translated),
        "line_count": len([line for line in translated.splitlines() if line.strip()]),
        "chunks": len(chunks),
    }


def _save_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def fetch_lyrics_result(
    artist: str,
    title: str,
    *,
    target_lang: str | None = None,
    style: str | None = None,
    generate: bool = False,
    output: str | Path | None = None,
    duration: int | None = None,
    instrumental: bool = False,
) -> dict[str, object]:
    fetched = fetch_lyrics(artist, title)
    result: dict[str, object] = {"fetch": fetched}

    lyrics_for_music = str(fetched["lyrics"])
    if target_lang:
        translated = translate_lyrics(lyrics_for_music, target_lang=target_lang)
        result["translation"] = translated
        lyrics_for_music = str(translated["lyrics"])

        out_dir = _default_output_dir()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = f"{_slug(str(fetched['artist']))}-{_slug(str(fetched['title']))}-{translated['target_lang']}-{ts}"
        original_path = out_dir / f"{base}-original.txt"
        translated_path = out_dir / f"{base}-translated.txt"
        _save_text(original_path, str(fetched["lyrics"]))
        _save_text(translated_path, lyrics_for_music)
        result["original_file"] = str(original_path)
        result["translated_file"] = str(translated_path)

    if generate:
        from arka.media.music_generate import music_generate_result

        prompt = (style or f"{fetched['title']} cover in {target_lang or 'original language'}").strip()
        music = music_generate_result(
            prompt,
            output=output,
            duration=duration,
            lyrics=lyrics_for_music,
            instrumental=instrumental,
        )
        result["music"] = music

    return result


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    m = re.search(
        r"(?i)(?:fetch|get|find|show)\s+(?:the\s+)?lyrics\s+(?:for|of)\s+(?P<title>.+?)\s+by\s+(?P<artist>.+)$",
        t,
    )
    if m:
        return ["fetch", m.group("artist").strip(), m.group("title").strip()]

    m = re.search(
        r"(?i)(?:translate|remix)\s+(?:the\s+)?(?:lyrics|song)\s+(?:of|for)\s+(?P<title>.+?)\s+by\s+(?P<artist>.+?)\s+(?:to|into)\s+(?P<lang>[a-zA-Z][\w-]*)",
        t,
    )
    if m:
        argv = [
            "translate",
            m.group("artist").strip(),
            m.group("title").strip(),
            "--target",
            m.group("lang").strip(),
        ]
        if re.search(r"(?i)\b(?:generate|create|make|remix|new\s+song)\b", t):
            argv.append("--generate")
        return argv

    m = re.search(
        r"(?i)translate\s+(?P<title>.+?)\s+by\s+(?P<artist>.+?)\s+(?:to|into)\s+(?P<lang>[a-zA-Z][\w-]*)",
        t,
    )
    if m and re.search(r"(?i)\b(?:lyrics|song|music)\b", t):
        argv = [
            "translate",
            m.group("artist").strip(),
            m.group("title").strip(),
            "--target",
            m.group("lang").strip(),
        ]
        if re.search(r"(?i)\b(?:generate|create|make|remix|new\s+song)\b", t):
            argv.append("--generate")
        return argv

    return []


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fetch song lyrics, translate them, and optionally generate a new track",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  fetch_lyrics fetch Queen \"Bohemian Rhapsody\"\n"
            "  fetch_lyrics fetch --query \"Shape of You by Ed Sheeran\"\n"
            "  fetch_lyrics translate Queen \"Bohemian Rhapsody\" --target hindi\n"
            "  fetch_lyrics translate \"Ed Sheeran\" \"Shape of You\" --target ta --generate --style \"tamil pop\"\n"
            "  fetch_lyrics check\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    p_fetch = sub.add_parser("fetch", help="Fetch lyrics for a song")
    p_fetch.add_argument("artist", nargs="?", help="Artist name")
    p_fetch.add_argument("title", nargs="*", help="Song title (words joined)")
    p_fetch.add_argument("-q", "--query", help="Song as 'Title by Artist'")
    p_fetch.add_argument("-o", "--output", help="Save lyrics to this .txt path")
    p_fetch.set_defaults(func=cmd_fetch)

    p_translate = sub.add_parser("translate", help="Fetch lyrics and translate to another language")
    p_translate.add_argument("artist", nargs="?", help="Artist name")
    p_translate.add_argument("title", nargs="*", help="Song title (words joined)")
    p_translate.add_argument("-q", "--query", help="Song as 'Title by Artist'")
    p_translate.add_argument("-t", "--target", required=True, help="Target language (hindi, ta, es, …)")
    p_translate.add_argument("--style", help="Music style prompt when using --generate")
    p_translate.add_argument("-d", "--duration", type=int, help="Generated song length in seconds")
    p_translate.add_argument("--generate", action="store_true", help="Generate a new track with translated lyrics")
    p_translate.add_argument("--instrumental", action="store_true", help="Instrumental only when generating music")
    p_translate.add_argument("-o", "--output", help="Output path for generated .mp3 (with --generate)")
    p_translate.set_defaults(func=cmd_translate)

    p_parse = sub.add_parser("parse", help="Parse natural language → fetch_lyrics args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify network access to lyrics providers")
    p_check.set_defaults(func=cmd_check)

    return p


def _resolve_song(args: argparse.Namespace) -> tuple[str, str]:
    if args.query:
        return parse_song_query(str(args.query))
    artist = str(getattr(args, "artist", "") or "").strip()
    raw_title = getattr(args, "title", None)
    if isinstance(raw_title, list):
        title = " ".join(str(part).strip() for part in raw_title if str(part).strip())
    else:
        title = str(raw_title or "").strip()
    if artist and title:
        return artist, title
    raise ValueError("Provide artist + title, or --query 'Title by Artist'")


def cmd_fetch(args: argparse.Namespace) -> int:
    artist, title = _resolve_song(args)
    print(f"Fetching lyrics for {title!r} by {artist!r} …", file=sys.stderr)
    fetched = fetch_lyrics(artist, title)
    lyrics = str(fetched["lyrics"])
    if args.output:
        saved = _save_text(Path(args.output).expanduser(), lyrics)
        fetched["output"] = str(saved)
    print(json.dumps(fetched, indent=2, ensure_ascii=False))
    if not args.output:
        print("\n--- lyrics ---\n")
        print(lyrics)
    return 0


def cmd_translate(args: argparse.Namespace) -> int:
    artist, title = _resolve_song(args)
    print(
        f"Fetching and translating {title!r} by {artist!r} → {args.target} …",
        file=sys.stderr,
    )
    result = fetch_lyrics_result(
        artist,
        title,
        target_lang=str(args.target),
        style=str(args.style or "").strip() or None,
        generate=bool(args.generate),
        output=args.output,
        duration=args.duration,
        instrumental=bool(args.instrumental),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    translation = result.get("translation")
    if isinstance(translation, dict):
        print("\n--- translated lyrics ---\n")
        print(str(translation.get("lyrics") or ""))
    music = result.get("music")
    if isinstance(music, dict) and music.get("output"):
        print(f"\nSaved track: {music['output']}", file=sys.stderr)
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    ok = True
    for name, url in (
        ("lrclib", f"{LRCLIB_SEARCH}?q=test"),
        ("lyrics.ovh", LYRICS_OVH.format(artist="Queen", title="Bohemian%20Rhapsody")),
    ):
        try:
            _http_json(url) if name == "lrclib" else _http_json(url)
            print(f"  {name}: ok")
        except Exception as exc:
            ok = False
            print(f"  {name}: unavailable ({exc})")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        build_parser().print_help()
        return 0
    if args[0] in {"-h", "--help"}:
        build_parser().parse_args(["fetch", "--help"])
        return 0
    try:
        ns = build_parser().parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not getattr(ns, "command", None):
        build_parser().print_help()
        return 0
    try:
        return int(ns.func(ns))
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
