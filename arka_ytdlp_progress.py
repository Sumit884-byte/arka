"""yt-dlp downloads with Arka progress bar (N/M done · pct)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from arka_progress import ProgressBar, progress_clear, progress_enabled, progress_note

_ITEM_RE = re.compile(r"\[download\]\s+Downloading item\s+(\d+)\s+of\s+(\d+)", re.I)
_PCT_RE = re.compile(r"\[download\]\s+([\d.]+)%")
_TITLE_RE = re.compile(r"\[download\]\s+Destination:\s+(.+)$")
_DONE_ITEM_RE = re.compile(r"\[download\]\s+100%|\[ExtractAudio\]\s+Destination:", re.I)


def ytdlp_common_opts() -> dict[str, Any]:
    """Shared yt-dlp options (cookies, proxy, player client)."""
    opts: dict[str, Any] = {"noprogress": progress_enabled(), "no_update": True}
    cookies = (os.environ.get("ARKA_YT_COOKIES") or os.environ.get("YOUTUBE_COOKIES") or "").strip()
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
            opts["cookiefile"] = str(cp)
    browser = (os.environ.get("ARKA_YT_COOKIES_BROWSER") or "").strip()
    if browser:
        opts["cookiesfrombrowser"] = (browser.split(",")[0].strip(),)
    proxy = (
        os.environ.get("ARKA_YT_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("ALL_PROXY")
        or ""
    ).strip()
    if proxy:
        opts["proxy"] = proxy
    client = (os.environ.get("ARKA_YT_PLAYER_CLIENT") or "android_vr").strip()
    if client:
        opts["extractor_args"] = {"youtube": {"player_client": [c.strip() for c in client.split(",") if c.strip()]}}
    sleep = (os.environ.get("ARKA_YT_SLEEP") or "").strip()
    if sleep.isdigit() and int(sleep) > 0:
        opts["sleep_interval"] = int(sleep)
        opts["max_sleep_interval"] = int(sleep) + 2
    return opts


def build_format_opts(*, audio: bool, quality: str, threads: int, frags: int) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "writeinfojson": True,
        "concurrent_fragment_downloads": max(1, int(frags)),
    }
    if audio:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }
        ]
    else:
        if quality == "best":
            opts["format"] = "bestvideo+bestaudio/best"
        else:
            opts["format"] = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
        opts["merge_output_format"] = "mp4"
        opts["postprocessor_args"] = {"ffmpeg": ["-threads", str(max(1, int(threads)))]}
    return opts


def _hook_factory(bar: ProgressBar | None, playlist_total: list[int | None]):
    def hook(d: dict[str, Any]) -> None:
        if bar is None:
            return
        status = d.get("status")
        info = d.get("info_dict") or {}
        title = (info.get("title") or info.get("id") or Path(d.get("filename") or "").stem or "")[:34]
        n = info.get("n_entries") or info.get("playlist_count") or playlist_total[0]
        idx = info.get("playlist_index")

        if n:
            playlist_total[0] = int(n)
            if bar.total != int(n):
                bar.set(bar.current, total=int(n))

        if status == "downloading":
            file_pct = 0
            total_b = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            down_b = d.get("downloaded_bytes") or 0
            if total_b:
                file_pct = int(down_b * 100 / total_b)
            if idx and playlist_total[0]:
                bar.set(int(idx) - 1, label=f"→ {title} · {file_pct}%")
            elif playlist_total[0] and playlist_total[0] > 1:
                bar.fraction(down_b / total_b if total_b else 0, label=f"→ {title} · {file_pct}%")
            else:
                if total_b:
                    bar.fraction(down_b / total_b, label=f"→ {title}")
                else:
                    bar.set(0, label=f"→ {title}")
        elif status == "finished":
            if playlist_total[0] and int(playlist_total[0]) > 1 and idx:
                bar.set(int(idx), total=int(playlist_total[0]), label=title)
            else:
                bar.set(1, total=1, label=title)

    return hook


def run_ytdlp_download(url: str, ydl_opts: dict[str, Any], *, phase: str = "Download") -> int:
    """Run yt-dlp with a progress bar. Uses Python API when available."""
    try:
        import yt_dlp
    except ImportError:
        return _run_subprocess(url, ydl_opts, phase=phase)

    use_bar = progress_enabled()
    bar = ProgressBar(phase, total=1, unit="done") if use_bar else None
    playlist_total: list[int | None] = [None]
    hook = _hook_factory(bar, playlist_total)

    merged = {**ytdlp_common_opts(), **ydl_opts}
    hooks = list(merged.pop("progress_hooks", []))
    hooks.insert(0, hook)
    merged["progress_hooks"] = hooks
    if use_bar:
        merged["quiet"] = True
        merged["no_warnings"] = True

    try:
        with yt_dlp.YoutubeDL(merged) as ydl:
            err = ydl.download([url])
    except Exception as exc:
        if bar is not None:
            progress_clear()
        print(f"yt-dlp error: {exc}", file=sys.stderr)
        return 1

    if bar is not None:
        total = playlist_total[0] or max(bar.total, bar.current or 1)
        bar.set(total, total=total)
        bar.done("Downloaded")
    elif not use_bar:
        progress_note(f"  Saved download from {url}")

    return 0 if err == 0 else err


def _opts_to_cli(ydl_opts: dict[str, Any]) -> list[str]:
    """Best-effort CLI flags for subprocess fallback."""
    from arka_youtube import _ytdlp_path

    exe = _ytdlp_path()
    if not exe:
        raise SystemExit("yt-dlp not found — install: pip install yt-dlp")

    cmd = [exe, "--no-update"]
    if progress_enabled():
        cmd.append("--no-progress")
    if ydl_opts.get("outtmpl"):
        cmd.extend(["-o", str(ydl_opts["outtmpl"])])
    if ydl_opts.get("format"):
        cmd.extend(["-f", str(ydl_opts["format"])])
    if ydl_opts.get("merge_output_format"):
        cmd.extend(["--merge-output-format", str(ydl_opts["merge_output_format"])])
    if ydl_opts.get("writeinfojson"):
        cmd.append("--write-info-json")
    if ydl_opts.get("yesplaylist"):
        cmd.append("--yes-playlist")
    if ydl_opts.get("noplaylist"):
        cmd.append("--no-playlist")
    if ydl_opts.get("ignoreerrors"):
        cmd.append("--ignore-errors")
    if ydl_opts.get("playliststart"):
        cmd.extend(["--playlist-start", str(ydl_opts["playliststart"])])
    if ydl_opts.get("playlistend"):
        cmd.extend(["--playlist-end", str(ydl_opts["playlistend"])])
    if ydl_opts.get("concurrent_fragment_downloads"):
        cmd.extend(["--concurrent-fragments", str(ydl_opts["concurrent_fragment_downloads"])])
    post = ydl_opts.get("postprocessors") or []
    if any(p.get("key") == "FFmpegExtractAudio" for p in post):
        cmd.extend(["--extract-audio", "--audio-format", "mp3", "--audio-quality", "0"])
    pp_args = ydl_opts.get("postprocessor_args") or {}
    ffmpeg_args = pp_args.get("ffmpeg") if isinstance(pp_args, dict) else None
    if ffmpeg_args:
        cmd.extend(["--downloader-args", f"ffmpeg:{ ' '.join(ffmpeg_args) }"])
    cookiefile = ydl_opts.get("cookiefile")
    if cookiefile:
        cmd.extend(["--cookies", str(cookiefile)])
    cfb = ydl_opts.get("cookiesfrombrowser")
    if cfb:
        cmd.extend(["--cookies-from-browser", str(cfb[0])])
    proxy = ydl_opts.get("proxy")
    if proxy:
        cmd.extend(["--proxy", str(proxy)])
    ext = ydl_opts.get("extractor_args") or {}
    yt = ext.get("youtube") or {}
    clients = yt.get("player_client") or []
    if clients:
        cmd.extend(["--extractor-args", f"youtube:player_client={clients[0]}"])
    return cmd


def _run_subprocess(url: str, ydl_opts: dict[str, Any], *, phase: str = "Download") -> int:
    merged = {**ytdlp_common_opts(), **ydl_opts}
    cmd = _opts_to_cli(merged)
    cmd.append(url)

    use_bar = progress_enabled()
    bar = ProgressBar(phase, total=1, unit="done") if use_bar else None
    current_item = 0
    total_items = 1
    current_title = ""
    file_pct = 0

    if not use_bar:
        print(f"  {phase} → {url}", file=sys.stderr)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        m_item = _ITEM_RE.search(line)
        if m_item:
            current_item = int(m_item.group(1))
            total_items = int(m_item.group(2))
            if bar is not None:
                bar.set(current_item - 1, total=total_items, label=f"→ item {current_item}")
            continue
        m_title = _TITLE_RE.search(line)
        if m_title:
            current_title = Path(m_title.group(1).strip()).stem[:34]
            continue
        m_pct = _PCT_RE.search(line)
        if m_pct:
            file_pct = int(float(m_pct.group(1)))
            if bar is not None:
                if total_items > 1:
                    bar.set(current_item - 1, total=total_items, label=f"→ {current_title} · {file_pct}%")
                else:
                    bar.fraction(file_pct / 100.0, label=f"→ {current_title or 'Downloading'}")
            continue
        if _DONE_ITEM_RE.search(line):
            if bar is not None and total_items > 1:
                bar.set(current_item, total=total_items, label=current_title)
            elif bar is not None:
                bar.set(1, total=1, label=current_title or "Done")
            continue
        if not use_bar and ("[download]" in line or "[Merger]" in line):
            print(line, file=sys.stderr)

    code = proc.wait()
    if bar is not None:
        if code == 0:
            bar.set(total_items, total=total_items)
            bar.done("Downloaded")
        else:
            progress_clear()
            print(f"  Download failed (exit {code})", file=sys.stderr)
    return code
