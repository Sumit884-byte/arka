#!/usr/bin/env python3
"""YouTube transcript fetch + optional summarize."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from html import unescape
from pathlib import Path

from arka_compute import ffmpeg_threads, log_compute_summary, yt_dlp_concurrent_fragments

VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})"
    r"|^([A-Za-z0-9_-]{11})$"
)
VTT_INLINE_RE = re.compile(r"<\d[\d:.]*>|</?c>|>>|&gt;&gt;|\[music\]", re.I)
VTT_TAG_RE = re.compile(r"<[^>]+>")
DEFAULT_DOWNLOAD_DIR = Path(
    os.environ.get("YOUTUBE_DOWNLOAD_DIR", str(Path.home() / "Videos/YoutubeDownloads/Singles"))
)
TRANSCRIPT_CACHE_DIR = Path.home() / ".cache/fish-agent/transcripts/youtube"
_API_IP_BLOCKED = False
_API_BLOCK_WARNED = False


def extract_video_id(text: str) -> str | None:
    text = text.strip()
    m = VIDEO_ID_RE.search(text)
    if not m:
        return None
    return m.group(1) or m.group(2)


def video_watch_url(target: str) -> str:
    video_id = extract_video_id(target)
    if not video_id:
        raise SystemExit("Could not parse YouTube URL or video id")
    return f"https://www.youtube.com/watch?v={video_id}"


def shutil_which(name: str) -> str | None:
    for p in os.environ.get("PATH", "").split(":"):
        candidate = Path(p) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _ytdlp_path() -> str | None:
    bulk_venv = Path.home() / "Projects/python/products/youtube_bulk_downloader/.venv/bin/yt-dlp"
    if bulk_venv.is_file():
        return str(bulk_venv)
    return shutil_which("yt-dlp")


def youtube_search(query: str, limit: int = 10) -> list[tuple[str, str, str]]:
    """Search YouTube via yt-dlp; return (video_id, title, channel) tuples."""
    query = query.strip()
    if not query:
        return []
    ytdlp = _ytdlp_path()
    if not ytdlp:
        raise SystemExit("yt-dlp not found — install yt-dlp or run: arka yt-bulk setup")
    limit = max(1, min(limit, 50))
    cmd = [
        ytdlp,
        "--no-update",
        "--flat-playlist",
        "--print",
        "%(id)s\t%(title)s\t%(channel)s",
        f"ytsearch{limit}:{query}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "yt-dlp search failed").strip()
        raise SystemExit(err[:500])
    entries: list[tuple[str, str, str]] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        parts = line.split("\t", 2)
        vid = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else vid
        channel = parts[2].strip() if len(parts) > 2 else ""
        if extract_video_id(vid) and len(vid) == 11:
            entries.append((vid, title, channel))
    return entries


def _caption_languages() -> list[str]:
    raw = (
        os.environ.get("ARKA_MEDIA_LANG")
        or os.environ.get("ARKA_SPEAK_LANG")
        or os.environ.get("YOUTUBE_CAPTION_LANG")
        or "en"
    ).strip()
    base = raw.split("-")[0].lower() or "en"
    langs: list[str] = []
    for code in (raw, base, "en", "en-US", "en-orig"):
        if code and code not in langs:
            langs.append(code)
    return langs


def _clean_caption_text(text: str) -> str:
    text = unescape(text)
    text = VTT_INLINE_RE.sub("", text)
    text = VTT_TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_title(title: str) -> str:
    title = re.sub(r"[【】＂""''`]", "", title)
    title = re.sub(r"[^\w\s]", " ", title, flags=re.UNICODE)
    return re.sub(r"\s+", " ", title).strip().lower()


def _title_matches(filename_title: str, result_title: str) -> bool:
    a = _normalize_title(filename_title)
    b = _normalize_title(result_title)
    if not a or not b:
        return False
    if a == b:
        return True
    return a in b or b in a


def _sidecar_paths(path: Path) -> list[Path]:
    stem = path.stem
    parent = path.parent
    return [
        Path(f"{path}.youtube-id"),
        parent / f"{stem}.youtube-id",
        parent / f"{stem}.info.json",
        parent / f"{path.name}.info.json",
    ]


def _video_id_from_info_json(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    vid = data.get("id") or data.get("video_id")
    if isinstance(vid, str) and extract_video_id(vid):
        return extract_video_id(vid)
    webpage = str(data.get("webpage_url") or data.get("original_url") or "")
    return extract_video_id(webpage)


def _video_id_from_sidecar(path: Path) -> str | None:
    for sidecar in _sidecar_paths(path):
        if sidecar.suffix == ".json":
            vid = _video_id_from_info_json(sidecar)
            if vid:
                return vid
            continue
        if sidecar.is_file():
            vid = sidecar.read_text(encoding="utf-8", errors="replace").strip()
            if extract_video_id(vid):
                return extract_video_id(vid)
    return None


def _video_id_from_metadata(path: Path) -> str | None:
    ffprobe = shutil_which("ffprobe")
    if not ffprobe:
        return None
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format_tags=comment:description",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    tags = (data.get("format") or {}).get("tags") or {}
    for key in ("comment", "description", "title"):
        val = tags.get(key)
        if isinstance(val, str):
            vid = extract_video_id(val)
            if vid:
                return vid
    return None


def _video_id_from_title_search(path: Path) -> str | None:
    if os.environ.get("ARKA_MEDIA_YOUTUBE_SEARCH", "1").strip().lower() in {"0", "no", "false", "off"}:
        return None
    ytdlp = _ytdlp_path()
    if not ytdlp:
        return None
    query = path.stem.strip()
    if len(query) < 8:
        return None
    proc = subprocess.run(
        [
            ytdlp,
            "--no-update",
            "--flat-playlist",
            "--print",
            "%(id)s\t%(title)s",
            f"ytsearch5:{query}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        if not line.strip() or "\t" not in line:
            continue
        vid, title = line.split("\t", 1)
        vid = vid.strip()
        if not extract_video_id(vid):
            continue
        if _title_matches(query, title):
            return vid
    return None


def resolve_video_id_for_path(path: Path, youtube_url: str | None = None) -> str | None:
    path = path.expanduser().resolve()
    for candidate in (
        youtube_url,
        os.environ.get("ARKA_YOUTUBE_URL", "").strip(),
    ):
        if candidate:
            vid = extract_video_id(candidate)
            if vid:
                return vid
    vid = _video_id_from_sidecar(path)
    if vid:
        return vid
    vid = _video_id_from_metadata(path)
    if vid:
        return vid
    return _video_id_from_title_search(path)


def write_video_id_sidecar(media_path: Path, video_id: str) -> None:
    sidecar = media_path.with_suffix(media_path.suffix + ".youtube-id")
    sidecar.write_text(video_id.strip(), encoding="utf-8")


def _parse_vtt(path: Path) -> str:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        if line.startswith("NOTE"):
            continue
        line = _clean_caption_text(line)
        if line:
            lines.append(line)
    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return " ".join(out)


def _yt_env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _is_ip_block_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(x in msg for x in ("ipblocked", "requestblocked", "blocking requests from your ip", "too many requests"))


def _node_js_runtime_args() -> list[str]:
    if _yt_env("ARKA_YT_NO_NODE", "").lower() in {"1", "true", "yes"}:
        return []
    node = shutil_which("node")
    if not node:
        for candidate in (
            Path.home() / ".nvm/versions/node/v20.19.5/bin/node",
            Path("/usr/bin/node"),
        ):
            if candidate.is_file():
                node = str(candidate)
                break
    if node:
        return ["--js-runtimes", f"node:{node}"]
    return []


def _whisper_enabled() -> bool:
    pref = _yt_env("ARKA_YT_WHISPER_FALLBACK", "auto").lower()
    return pref not in {"0", "false", "no", "off"}


def _ytdlp_extra_args(*, player_client: str | None = None) -> list[str]:
    args: list[str] = []
    args.extend(_node_js_runtime_args())
    cookies = _yt_env("ARKA_YT_COOKIES") or _yt_env("YOUTUBE_COOKIES")
    if not cookies:
        for default in (
            Path.home() / ".config/fish/youtube-cookies.txt",
            Path.home() / ".cache/fish-agent/youtube-cookies.txt",
        ):
            if default.is_file():
                cookies = str(default)
                break
    if cookies:
        cp = Path(cookies).expanduser()
        if cp.is_file():
            args.extend(["--cookies", str(cp)])
    browser = _yt_env("ARKA_YT_COOKIES_BROWSER")
    if browser:
        args.extend(["--cookies-from-browser", browser])
    proxy = _yt_env("ARKA_YT_PROXY") or _yt_env("HTTPS_PROXY") or _yt_env("ALL_PROXY")
    if proxy:
        args.extend(["--proxy", proxy])
    client = player_client or _yt_env("ARKA_YT_PLAYER_CLIENT", "android_vr")
    if client:
        args.extend(["--extractor-args", f"youtube:player_client={client}"])
    sleep = _yt_env("ARKA_YT_SLEEP", "")
    if sleep.isdigit() and int(sleep) > 0:
        args.extend(["--sleep-interval", sleep, "--max-sleep-interval", str(int(sleep) + 2)])
    return args


def _transcript_cache_path(video_id: str) -> Path:
    return TRANSCRIPT_CACHE_DIR / f"{video_id}.txt"


def _read_cached_transcript(video_id: str) -> str | None:
    path = _transcript_cache_path(video_id)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text or None


def _write_cached_transcript(video_id: str, text: str) -> None:
    path = _transcript_cache_path(video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip(), encoding="utf-8")


def _skip_transcript_api() -> bool:
    global _API_IP_BLOCKED
    if _API_IP_BLOCKED:
        return True
    pref = _yt_env("ARKA_YT_SKIP_TRANSCRIPT_API", "").lower()
    return pref in {"1", "true", "yes", "on"}


def _prefer_ytdlp_transcripts() -> bool:
    pref = _yt_env("ARKA_YT_PREFER_YTDLP", "1").lower()
    return pref not in {"0", "false", "no", "off"}


def transcript_via_api(video_id: str, *, quiet: bool = False) -> str | None:
    global _API_IP_BLOCKED, _API_BLOCK_WARNED
    if _skip_transcript_api():
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    langs = _caption_languages()
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=langs)
        parts = [_clean_caption_text(s.text) for s in fetched if s.text and s.text.strip()]
        text = " ".join(parts).strip()
        return text or None
    except Exception as exc:
        if _is_ip_block_error(exc):
            _API_IP_BLOCKED = True
            if not quiet and not _API_BLOCK_WARNED:
                _API_BLOCK_WARNED = True
                print(
                    "arka_youtube: caption API blocked by YouTube — using yt-dlp only "
                    "(set ARKA_YT_COOKIES=~/cookies.txt or ARKA_YT_SKIP_TRANSCRIPT_API=1)",
                    file=sys.stderr,
                )
        elif not quiet:
            short = str(exc).split("\n")[0][:180]
            print(f"arka_youtube: caption API failed: {short}", file=sys.stderr)
        return None


def _ytdlp_run_subs(video_id: str, *, quiet: bool = False) -> str | None:
    ytdlp = _ytdlp_path()
    if not ytdlp:
        return None
    url = f"https://www.youtube.com/watch?v={video_id}"
    langs = ",".join(_caption_languages())
    sub_langs = f"{langs},en.*,hi.*"
    clients = [
        c.strip()
        for c in (_yt_env("ARKA_YT_PLAYER_CLIENT", "android_vr") + ",web").split(",")
        if c.strip()
    ]
    seen: set[str] = set()
    retries = max(0, int(_yt_env("ARKA_YT_SUB_RETRIES", "1") or "0"))
    retry_wait = max(5, int(_yt_env("ARKA_YT_429_WAIT", "45") or "45"))

    for client in clients:
        if client in seen:
            continue
        seen.add(client)
        for attempt in range(retries + 1):
            with tempfile.TemporaryDirectory(prefix="arka-yt-") as td:
                out_tpl = str(Path(td) / "sub")
                cmd = [
                    ytdlp,
                    "--no-update",
                    "--write-auto-sub",
                    "--write-sub",
                    "--skip-download",
                    "--sub-langs",
                    sub_langs,
                    "--sub-format",
                    "vtt/best/srv3/json3",
                    "-o",
                    out_tpl,
                    *_ytdlp_extra_args(player_client=client),
                    url,
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=180)
                err = (proc.stderr or proc.stdout or "").strip()
                if proc.returncode != 0 and err:
                    is_429 = "429" in err or "too many requests" in err.lower()
                    if is_429 and attempt < retries:
                        if not quiet:
                            print(
                                f"arka_youtube: rate limited — waiting {retry_wait}s before retry …",
                                file=sys.stderr,
                            )
                        time.sleep(retry_wait)
                        continue
                    if not quiet and not _yt_env("ARKA_YT_QUIET"):
                        print(
                            f"arka_youtube: yt-dlp subtitles ({client}): {err.split(chr(10))[0][:200]}",
                            file=sys.stderr,
                        )
                for pattern in (f"{out_tpl}*.vtt", f"{out_tpl}*.json3", f"{out_tpl}*.srv3"):
                    files = sorted(glob.glob(pattern))
                    if not files:
                        continue
                    path = Path(files[0])
                    if path.suffix == ".vtt":
                        text = _parse_vtt(path)
                        if text:
                            return text
                    if path.suffix == ".json3":
                        try:
                            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                            parts = [
                                _clean_caption_text(ev.get("segs", [{}])[0].get("utf8", ""))
                                for ev in data.get("events") or []
                                if isinstance(ev, dict)
                            ]
                            text = " ".join(p for p in parts if p).strip()
                            if text:
                                return text
                        except (json.JSONDecodeError, OSError, IndexError, KeyError):
                            pass
            break
    return None


def transcript_via_ytdlp(video_id: str) -> str | None:
    return _ytdlp_run_subs(video_id)


def transcript_via_whisper(video_id: str) -> str | None:
    """Download audio and transcribe via STT (works when caption APIs are rate-limited)."""
    if not _whisper_enabled():
        return None
    ytdlp = _ytdlp_path()
    if not ytdlp:
        return None
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"arka_youtube: captions unavailable — transcribing audio for {video_id} …", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="arka-yt-whisper-") as td:
        out_tpl = str(Path(td) / "audio.%(ext)s")
        cmd = [
            ytdlp,
            "--no-update",
            "-f",
            "bestaudio/best",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "-o",
            out_tpl,
            *_ytdlp_extra_args(player_client="android_vr"),
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            if err:
                print(f"arka_youtube: audio download failed: {err.split(chr(10))[0][:200]}", file=sys.stderr)
            return None
        audio_files = sorted(Path(td).glob("audio.*"))
        if not audio_files:
            return None
        try:
            from arka_media import _load_fish_env, transcribe_file

            _load_fish_env()
            return transcribe_file(audio_files[0], skip_youtube=True).strip() or None
        except Exception as exc:
            print(f"arka_youtube: whisper fallback failed: {exc}", file=sys.stderr)
            return None


def get_transcript(target: str) -> tuple[str, str]:
    video_id = extract_video_id(target)
    if not video_id:
        raise SystemExit("Could not parse YouTube URL or video id")
    text = fetch_transcript_text(video_id)
    if not text:
        raise SystemExit("Transcript not available")
    return video_id, text


def fetch_transcript_text(video_id: str, *, use_cache: bool = True) -> str | None:
    video_id = (video_id or "").strip()
    if not video_id:
        return None

    if use_cache:
        cached = _read_cached_transcript(video_id)
        if cached:
            return cached

    text: str | None = None
    backend = _yt_env("ARKA_YT_TRANSCRIPT", "auto").lower()

    if backend in {"ytdlp", "yt-dlp"}:
        text = transcript_via_ytdlp(video_id)
    elif backend == "api":
        text = transcript_via_api(video_id)
    elif _prefer_ytdlp_transcripts():
        text = transcript_via_ytdlp(video_id)
        if not text:
            text = transcript_via_api(video_id, quiet=True)
    else:
        text = transcript_via_api(video_id)
        if not text:
            text = transcript_via_ytdlp(video_id)

    if not text:
        text = transcript_via_whisper(video_id)

    if text:
        _write_cached_transcript(video_id, text)
        return text.strip()
    return None


def fetch_transcript_with_source(video_id: str) -> tuple[str | None, str]:
    """Return (text, source) where source is cache|ytdlp|api|whisper|none."""
    cached = _read_cached_transcript(video_id)
    if cached:
        return cached, "cache"

    if _prefer_ytdlp_transcripts() and not _skip_transcript_api():
        text = transcript_via_ytdlp(video_id)
        if text:
            _write_cached_transcript(video_id, text)
            return text.strip(), "ytdlp"
        text = transcript_via_api(video_id, quiet=True)
        if text:
            _write_cached_transcript(video_id, text)
            return text.strip(), "api"
    else:
        text = fetch_transcript_text(video_id, use_cache=False)
        if text:
            return text, "auto"

    text = transcript_via_whisper(video_id)
    if text:
        _write_cached_transcript(video_id, text)
        return text.strip(), "whisper"
    return None, "none"


def try_transcript_for_media(path: Path, youtube_url: str | None = None) -> tuple[str, str, str] | None:
    """Return (video_id, transcript, source) or None if captions unavailable."""
    video_id = resolve_video_id_for_path(path, youtube_url=youtube_url)
    if not video_id:
        return None
    text, source = fetch_transcript_with_source(video_id)
    if text:
        write_video_id_sidecar(path, video_id)
        return video_id, text, f"youtube-{source}"
    return None


def cmd_download(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Download a single YouTube video")
    parser.add_argument("target", help="YouTube URL, shorts link, or video id")
    parser.add_argument("--audio", "-a", action="store_true", help="Extract MP3 instead of video")
    parser.add_argument(
        "--quality",
        "-q",
        default=os.environ.get("YOUTUBE_DOWNLOAD_QUALITY", "1080"),
        choices=["1080", "720", "480", "best"],
    )
    parser.add_argument("-o", "--output-dir", help="Save directory")
    args = parser.parse_args(argv)

    video_id = extract_video_id(args.target)
    if not video_id:
        raise SystemExit("Could not parse YouTube URL or video id")
    url = video_watch_url(args.target)
    out_dir = Path(args.output_dir).expanduser() if args.output_dir else DEFAULT_DOWNLOAD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ytdlp = _ytdlp_path()
    if not ytdlp:
        raise SystemExit("yt-dlp not found — install: pip install yt-dlp  (or youtube_bulk --setup via project venv)")
    out_tpl = str(out_dir / "%(title)s.%(ext)s")
    threads = ffmpeg_threads()
    frags = yt_dlp_concurrent_fragments()
    log_compute_summary()

    common = [
        ytdlp,
        "--write-info-json",
        "-o",
        out_tpl,
        "--no-playlist",
        "--concurrent-fragments",
        str(frags),
        url,
    ]

    if args.audio:
        cmd = [
            *common[:1],
            "-f",
            "bestaudio/best",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            *common[1:],
        ]
    else:
        if args.quality == "best":
            fmt = "bestvideo+bestaudio/best"
        else:
            fmt = f"bestvideo[height<={args.quality}]+bestaudio/best[height<={args.quality}]"
        cmd = [
            *common[:1],
            "-f",
            fmt,
            "--merge-output-format",
            "mp4",
            "--downloader-args",
            f"ffmpeg:-threads {threads}",
            *common[1:],
        ]

    print(f"Downloading → {out_dir}/", file=sys.stderr)
    proc = subprocess.run(cmd, check=False)
    if proc.returncode == 0 and video_id:
        for info in sorted(out_dir.glob("*.info.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if _video_id_from_info_json(info) != video_id:
                continue
            stem = info.name[: -len(".info.json")]
            for ext in (".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus"):
                media = out_dir / f"{stem}{ext}"
                if media.is_file():
                    write_video_id_sidecar(media, video_id)
                    break
            break
    return proc.returncode


def summarize_transcript(text: str, question: str) -> str:
    from arka_llm import llm_complete

    system = (
        "Summarize the YouTube transcript clearly. Use short paragraphs or bullets. "
        "If the user asked a specific question, answer it from the transcript."
    )
    user = f"Question/focus: {question}\n\nTranscript:\n{text[:14000]}"
    return llm_complete(system, user, temperature=0.2).strip()


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] in {"download", "fetch"}:
        return cmd_download(sys.argv[2:])

    parser = argparse.ArgumentParser(description="Fetch YouTube transcript")
    parser.add_argument("target", help="YouTube URL or video id")
    parser.add_argument("--summarize", "-s", action="store_true", help="Summarize via LLM")
    parser.add_argument("--question", "-q", default="Summarize the main points")
    parser.add_argument("-o", "--output", help="Save transcript to file")
    args = parser.parse_args()

    video_id, text = get_transcript(args.target)
    print(f"Video: https://youtube.com/watch?v={video_id}")
    print(f"Length: {len(text.split())} words\n")

    if args.summarize:
        summary = summarize_transcript(text, args.question)
        print("━━━ Summary ━━━")
        print(summary)
    else:
        print(text)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"\nSaved transcript: {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
