#!/usr/bin/env python3
"""YouTube bulk downloader — integrate ~/Projects/python/products/youtube_bulk_downloader."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from arka_progress import ProgressBar, progress_enabled
from arka_compute import export_env_defaults, io_workers, log_compute_summary

PROJECT_DIR = Path(
    os.environ.get("YOUTUBE_BULK_DIR", str(Path.home() / "Projects/python/products/youtube_bulk_downloader"))
).expanduser()
APP_PY = PROJECT_DIR / "app.py"
CACHE_DIR = Path.home() / ".cache/fish-agent/youtube-bulk"
PID_FILE = CACHE_DIR / "server.pid"
LOG_FILE = CACHE_DIR / "server.log"
DEFAULT_PORT = int(os.environ.get("YOUTUBE_BULK_PORT", "5000"))
DEFAULT_DOWNLOAD_PATH = Path("/home/s/Videos/YoutubeDownloads")


def _project_python() -> str:
    override = os.environ.get("YOUTUBE_BULK_PYTHON", "").strip()
    if override and Path(override).is_file():
        return override
    venv_py = PROJECT_DIR / ".venv/bin/python3"
    if venv_py.is_file():
        return str(venv_py)
    arka_py = Path.home() / ".config/fish/venv-arka/bin/python3"
    if arka_py.is_file():
        return str(arka_py)
    return sys.executable


def _base_url() -> str:
    host = os.environ.get("YOUTUBE_BULK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    return f"http://{host}:{DEFAULT_PORT}"


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_server_pid() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        PID_FILE.unlink(missing_ok=True)
        return None
    if pid > 0 and _process_alive(pid):
        return pid
    PID_FILE.unlink(missing_ok=True)
    return None


def _server_responding() -> bool:
    try:
        with urllib.request.urlopen(f"{_base_url()}/api/status", timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _api_get(path: str) -> dict:
    with urllib.request.urlopen(f"{_base_url()}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _api_post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{_base_url()}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ensure_project() -> None:
    if not APP_PY.is_file():
        raise SystemExit(f"youtube_bulk: app not found at {APP_PY}")


def cmd_status(_args: argparse.Namespace) -> int:
    _ensure_project()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pid = _read_server_pid()
    online = _server_responding()
    print("━━━ YouTube Bulk Downloader ━━━")
    print(f"Project:  {PROJECT_DIR}")
    print(f"Web UI:   {_base_url()}/")
    print(f"Save to:  {DEFAULT_DOWNLOAD_PATH}")
    if pid and online:
        print(f"Server:   running (pid {pid})")
    elif pid:
        print(f"Server:   pid {pid} stale (not responding)")
    else:
        print("Server:   stopped")
    if online:
        try:
            st = _api_get("/api/status")
            print("")
            print(f"Download: {st.get('status', 'idle')} — {st.get('progress', 0)}/{st.get('total', 0)}")
            if st.get("folder"):
                print(f"Folder:   {st.get('folder')}")
            if st.get("current_video"):
                print(f"Current:  {st.get('current_video')}")
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            print(f"Status API error: {exc}", file=sys.stderr)
    print("")
    print("Usage: youtube_bulk [status|start|stop|open|download|library|logs]")
    print("       youtube_bulk download <url> [--channel] [--audio] [--quality 1080] [--limit N] [--wait]")
    return 0


def cmd_start(_args: argparse.Namespace) -> int:
    _ensure_project()
    export_env_defaults()
    log_compute_summary()
    if _read_server_pid() and _server_responding():
        print(f"youtube_bulk: already running at {_base_url()}/")
        return 0
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    py = _project_python()
    with open(LOG_FILE, "ab") as fh:
        proc = subprocess.Popen(
            [py, str(APP_PY)],
            cwd=str(PROJECT_DIR),
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    for _ in range(30):
        time.sleep(0.2)
        if _server_responding():
            print(f"youtube_bulk: started (pid {proc.pid}) → {_base_url()}/")
            return 0
        if proc.poll() is not None:
            break
    print(f"youtube_bulk: server failed to start — see {LOG_FILE}", file=sys.stderr)
    PID_FILE.unlink(missing_ok=True)
    return 1


def cmd_stop(_args: argparse.Namespace) -> int:
    pid = _read_server_pid()
    if not pid:
        print("youtube_bulk: not running")
        return 0
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    PID_FILE.unlink(missing_ok=True)
    print(f"youtube_bulk: stopped (pid {pid})")
    return 0


def cmd_open(_args: argparse.Namespace) -> int:
    url = f"{_base_url()}/"
    if not _server_responding():
        print("youtube_bulk: starting server …", file=sys.stderr)
        if cmd_start(_args) != 0:
            return 1
    print(f"Opening {url}")
    webbrowser.open(url)
    return 0


def _normalize_download_type(url: str, channel: bool) -> tuple[str, str]:
    url = url.strip()
    if channel:
        if not url.startswith("http"):
            if not url.startswith("@"):
                url = "@" + url
            url = f"https://www.youtube.com/{url}/videos"
        elif not url.endswith(("/videos", "/shorts", "/streams")):
            url = url.rstrip("/") + "/videos"
        return url, "channel"
    return url, "playlist"


def _download_via_api(args: argparse.Namespace) -> int:
    url, dtype = _normalize_download_type(args.url, args.channel)
    payload = {
        "url": url,
        "quality": args.quality,
        "type": dtype,
        "format_mode": "audio" if args.audio else "video",
        "limit": args.limit,
    }
    try:
        _api_post("/api/download", payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Download rejected ({exc.code}): {body}") from exc
    print(f"Started download ({dtype}, {payload['format_mode']}, {args.quality}p): {url}")
    if args.wait:
        return _wait_for_download()
    print(f"Track progress: youtube_bulk status  |  {_base_url()}/")
    return 0


def _wait_for_download() -> int:
    last_log = 0
    bar = ProgressBar("Downloading", total=100) if progress_enabled() else None
    while True:
        try:
            st = _api_get("/api/status")
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            if bar is not None:
                bar.done("Failed")
            print(f"Status poll failed: {exc}", file=sys.stderr)
            return 1
        logs = st.get("logs") or []
        for line in logs[last_log:]:
            if bar is None:
                print(line)
        last_log = len(logs)
        total = int(st.get("total") or 0)
        prog = int(st.get("progress") or 0)
        if bar is not None and total > 0:
            label = st.get("current_video") or "Downloading"
            bar.set(prog, total=total, label=str(label)[:40])
        status = st.get("status", "idle")
        if not st.get("active") and status in {"complete", "idle", "error"}:
            if bar is not None:
                bar.done("Done" if status != "error" else "Error")
            elif logs[last_log:]:
                for line in logs[last_log:]:
                    print(line)
            if status == "error":
                return 1
            if bar is None:
                print("Done.")
            return 0
        time.sleep(1)


def _download_direct(args: argparse.Namespace) -> int:
    url, dtype = _normalize_download_type(args.url, args.channel)
    fmt_mode = "audio" if args.audio else "video"
    py = _project_python()
    script = r"""
import sys
sys.path.insert(0, sys.argv[1])
import os
os.chdir(sys.argv[1])
from app import perform_download, download_state

url, quality, dtype, limit, fmt_mode = sys.argv[2:7]
limit = int(limit) if limit else None
perform_download(url, quality, dtype, limit, fmt_mode)
for line in download_state.get("logs") or []:
    print(line)
status = download_state.get("status", "error")
raise SystemExit(0 if status in ("complete", "idle") else 1)
"""
    limit = str(args.limit) if args.limit else ""
    proc = subprocess.run(
        [py, "-c", script, str(PROJECT_DIR), url, args.quality, dtype, limit, fmt_mode],
        cwd=str(PROJECT_DIR),
        check=False,
    )
    return proc.returncode


def cmd_download(args: argparse.Namespace) -> int:
    _ensure_project()
    export_env_defaults()
    log_compute_summary()
    if not args.url:
        raise SystemExit("URL required — playlist, channel URL, or @handle")
    if _server_responding():
        return _download_via_api(args)
    print("youtube_bulk: running headless (web UI not started)", file=sys.stderr)
    return _download_direct(args)


def cmd_library(_args: argparse.Namespace) -> int:
    _ensure_project()
    if _server_responding():
        try:
            data = _api_get("/api/library")
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            print(f"Library API failed: {exc}", file=sys.stderr)
            return 1
        library = data.get("library") or {}
    else:
        library = {}
        root = DEFAULT_DOWNLOAD_PATH
        if root.is_dir():
            for folder in sorted(root.iterdir()):
                if not folder.is_dir():
                    continue
                items = []
                for f in sorted(folder.iterdir()):
                    if f.suffix.lower() in {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus"}:
                        kind = "audio" if f.suffix.lower() in {".mp3", ".m4a", ".opus"} else "video"
                        items.append({"name": f.name, "type": kind})
                if items:
                    library[folder.name] = items
    if not library:
        print("Library empty.")
        return 0
    for folder, items in sorted(library.items()):
        print(f"\n{folder}/")
        for item in items:
            kind = item.get("type", "video")
            print(f"  [{kind}] {item.get('name', '')}")
    return 0


def cmd_logs(_args: argparse.Namespace) -> int:
    if _server_responding():
        st = _api_get("/api/status")
        for line in (st.get("logs") or [])[-50:]:
            print(line)
        return 0
    if LOG_FILE.is_file():
        print(LOG_FILE.read_text(encoding="utf-8", errors="replace")[-8000:])
        return 0
    print("No logs yet.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="YouTube bulk playlist/channel downloader (yt-dlp + web UI)",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Server + download status").set_defaults(func=cmd_status)
    sub.add_parser("start", help="Start web UI server").set_defaults(func=cmd_start)
    sub.add_parser("stop", help="Stop web UI server").set_defaults(func=cmd_stop)
    sub.add_parser("open", help="Open web UI in browser").set_defaults(func=cmd_open)
    sub.add_parser("library", help="List downloaded media").set_defaults(func=cmd_library)
    sub.add_parser("logs", help="Recent download/server logs").set_defaults(func=cmd_logs)

    p_dl = sub.add_parser("download", help="Download playlist or channel")
    p_dl.add_argument("url", nargs="?", help="Playlist URL, channel URL, or @handle")
    p_dl.add_argument("--channel", action="store_true", help="Treat URL as YouTube channel")
    p_dl.add_argument("--audio", action="store_true", help="Extract MP3 instead of video")
    p_dl.add_argument("--quality", default="1080", choices=["1080", "720", "480"])
    p_dl.add_argument("--limit", type=int, default=None, help="Max newest items (channels)")
    p_dl.add_argument("--wait", action="store_true", help="Block until download finishes")
    p_dl.set_defaults(func=cmd_download)

    args = parser.parse_args()
    if not args.cmd:
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
