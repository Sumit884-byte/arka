#!/usr/bin/env python3
"""Track and report desktop app usage time for Arka."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

CACHE = Path.home() / ".cache" / "fish-agent"
USAGE_DIR = CACHE / "usage"
WEBSITE_DIR = USAGE_DIR / "websites"
PID_FILE = CACHE / "arka_usage.pid"
INTERVAL = int(os.environ.get("ARKA_USAGE_INTERVAL", "20"))
IDLE_SEC = int(os.environ.get("ARKA_USAGE_IDLE_SEC", "120"))
WEB_TRACK = os.environ.get("ARKA_WEB_TRACK", "1").lower() not in ("0", "false", "no")
BROWSER_RE = re.compile(
    r"(?i)firefox|brave|chrome|chromium|vivaldi|edge|opera|navigator|zen|safari"
)
CHROMIUM_HISTORY_LINUX = (
    Path.home() / ".config" / "google-chrome" / "Default" / "History",
    Path.home() / ".config" / "BraveSoftware" / "Brave-Browser" / "Default" / "History",
    Path.home() / ".config" / "chromium" / "Default" / "History",
    Path.home() / ".config" / "microsoft-edge" / "Default" / "History",
    Path.home() / ".config" / "vivaldi" / "Default" / "History",
)
CHROMIUM_HISTORY_MACOS = (
    Path.home() / "Library/Application Support/Google/Chrome/Default/History",
    Path.home() / "Library/Application Support/BraveSoftware/Brave-Browser/Default/History",
    Path.home() / "Library/Application Support/Chromium/Default/History",
    Path.home() / "Library/Application Support/Microsoft Edge/Default/History",
    Path.home() / "Library/Application Support/Vivaldi/Default/History",
)
RANGE_RE = re.compile(
    r" - (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})[–-](\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
)


def host_platform() -> str:
    """macos | linux | windows | … — prefers cached arka_platform profile."""
    try:
        from arka_platform import cached_platform

        plat = cached_platform()
        if plat:
            return plat
    except ImportError:
        pass
    sysname = platform.system()
    if sysname == "Darwin":
        return "macos"
    if sysname.startswith("Linux"):
        return "linux"
    if sysname == "Windows":
        return "windows"
    return sysname.lower()


def chromium_history_paths() -> tuple[Path, ...]:
    if host_platform() == "macos":
        return CHROMIUM_HISTORY_MACOS
    return CHROMIUM_HISTORY_LINUX


def macos_active_app() -> str:
    """Frontmost app via lsappinfo (no Accessibility permission needed)."""
    try:
        front = subprocess.run(
            ["lsappinfo", "front"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if front.returncode != 0:
            return "Unknown"
        asn = front.stdout.strip().split()[0] if front.stdout.strip() else ""
        if not asn:
            return "Unknown"
        info = subprocess.run(
            ["lsappinfo", "info", "-only", "name", asn],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if info.returncode != 0:
            return "Unknown"
        m = re.search(r'"LSDisplayName"="([^"]+)"', info.stdout)
        if m:
            return normalize_app(m.group(1))
        m2 = re.search(r'name="([^"]+)"', info.stdout, re.I)
        if m2:
            return normalize_app(m2.group(1))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "Unknown"


def macos_idle_seconds() -> float | None:
    """Seconds since last keyboard/mouse input (IOHIDSystem)."""
    try:
        proc = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode != 0:
            return None
        m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', proc.stdout)
        if m:
            return int(m.group(1)) / 1_000_000_000.0
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def gnome_history_enabled() -> bool:
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.screen-time-limits", "history-enabled"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if out.returncode == 0:
            return out.stdout.strip().lower() in ("true", "'true'")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


def gnome_session_ranges() -> list[tuple[int, int]]:
    """Login-session periods from GNOME malcontent-timerd (Settings → Screen Time)."""
    user = os.environ.get("USER", "")
    if not user:
        return []
    try:
        proc = subprocess.run(
            ["malcontent-client", "-q", "query-usage", user, "login-session", ""],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    ranges: list[tuple[int, int]] = []
    for m in RANGE_RE.finditer(proc.stdout):
        try:
            start = int(datetime.fromisoformat(m.group(1)).timestamp())
            end = int(datetime.fromisoformat(m.group(2)).timestamp())
            if end > start:
                ranges.append((start, end))
        except ValueError:
            continue
    return ranges


def _day_bounds(d: date) -> tuple[int, int]:
    start = datetime.combine(d, datetime.min.time())
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def _overlap_seconds(start: int, end: int, window_start: int, window_end: int) -> int:
    lo = max(start, window_start)
    hi = min(end, window_end)
    return max(0, hi - lo)


def logind_active_since_epoch() -> int | None:
    """When the current graphical session started (systemd logind Timestamp)."""
    sid = os.environ.get("XDG_SESSION_ID", "").strip()
    candidates: list[str] = [sid] if sid else []

    if not candidates:
        user = os.environ.get("USER", "")
        try:
            proc = subprocess.run(
                ["loginctl", "list-sessions", "--no-legend"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] == user:
                        candidates.append(parts[0])
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    for session_id in candidates:
        if not session_id:
            continue
        try:
            proc = subprocess.run(
                [
                    "loginctl",
                    "show-session",
                    session_id,
                    "-p",
                    "State",
                    "-p",
                    "Class",
                    "-p",
                    "Timestamp",
                    "-p",
                    "ActiveSince",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode != 0:
                continue
            meta = {}
            for line in proc.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    meta[k] = v.strip()
            if meta.get("State") != "active" or meta.get("Class") not in ("user", ""):
                continue
            ts = meta.get("ActiveSince") or meta.get("Timestamp")
            if not ts:
                continue
            proc2 = subprocess.run(
                ["date", "+%s", "-d", ts],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc2.returncode == 0 and proc2.stdout.strip().isdigit():
                return int(proc2.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            continue
    return None


def gnome_completed_seconds_between(since: date, until: date) -> int:
    """Sum malcontent login-session segments only (no current-session estimate)."""
    total = 0
    ranges = gnome_session_ranges()
    d = since
    while d <= until:
        ws, we = _day_bounds(d)
        for start, end in ranges:
            total += _overlap_seconds(start, end, ws, we)
        d += timedelta(days=1)
    return total


def gnome_today_total_seconds() -> tuple[int, int, int]:
    """Completed GNOME segments, current-session extra, and total for today."""
    today = date.today()
    completed = gnome_completed_seconds_between(today, today)
    extra = 0
    active_since = logind_active_since_epoch()
    if active_since:
        now = int(time.time())
        ws, we = _day_bounds(today)
        session_today = _overlap_seconds(active_since, now, ws, we)
        if session_today > completed:
            extra = session_today - completed
    return completed, extra, completed + extra


def gnome_seconds_between(since: date, until: date) -> int:
    if since == until == date.today():
        return gnome_today_total_seconds()[2]
    return gnome_completed_seconds_between(since, until)


def gnome_available() -> bool:
    return bool(gnome_session_ranges()) or gnome_history_enabled()


def today_file() -> Path:
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    return USAGE_DIR / f"{date.today().isoformat()}.json"


def today_website_file() -> Path:
    WEBSITE_DIR.mkdir(parents=True, exist_ok=True)
    return WEBSITE_DIR / f"{date.today().isoformat()}.json"


def is_browser(app: str) -> bool:
    return bool(BROWSER_RE.search(app))


def domain_from_url(url: str) -> str:
    url = (url or "").strip()
    if not url or url.startswith("about:") or url.startswith("chrome:"):
        return ""
    if "://" not in url:
        url = f"https://{url}"
    host = urllib.parse.urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host[:80]


def _query_sqlite_copy(db_path: Path, sql: str) -> str | None:
    if not db_path.exists():
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        shutil.copy2(db_path, tmp_path)
        conn = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
        try:
            row = conn.execute(sql).fetchone()
        finally:
            conn.close()
            tmp_path.unlink(missing_ok=True)
        if row and row[0]:
            return str(row[0])
    except (OSError, sqlite3.Error):
        return None
    return None


def chromium_last_url() -> str | None:
    sql = "SELECT url FROM urls ORDER BY last_visit_time DESC LIMIT 1"
    for path in chromium_history_paths():
        url = _query_sqlite_copy(path, sql)
        if url:
            return url
    return None


def firefox_last_url() -> str | None:
    base = Path.home() / ".mozilla" / "firefox"
    if not base.is_dir():
        return None
    sql = (
        "SELECT p.url FROM moz_places p "
        "JOIN moz_historyvisits v ON v.place_id = p.id "
        "ORDER BY v.visit_date DESC LIMIT 1"
    )
    for profile in sorted(base.glob("*.default*")):
        url = _query_sqlite_copy(profile / "places.sqlite", sql)
        if url:
            return url
    return None


def mpris_browser_url() -> str | None:
    try:
        proc = subprocess.run(
            ["playerctl", "-l"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode != 0:
            return None
        for player in proc.stdout.splitlines():
            if not BROWSER_RE.search(player):
                continue
            proc2 = subprocess.run(
                ["playerctl", "--player", player, "metadata", "xesam:url"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc2.returncode == 0:
                url = proc2.stdout.strip()
                if url and url != "No players found":
                    return url
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def active_window_title() -> str:
    js = (
        "(() => {"
        "  const w = global.display.focus_window;"
        "  if (!w) return '';"
        "  return (w.get_title && w.get_title()) || '';"
        "})()"
    )
    try:
        out = subprocess.run(
            [
                "gdbus", "call", "--session", "--dest", "org.gnome.Shell",
                "--object-path", "/org/gnome/Shell",
                "--method", "org.gnome.Shell.Eval", js,
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if out.returncode == 0:
            m = re.search(r"'((?:\\'|[^'])*)'", out.stdout)
            if m:
                return m.group(1).encode().decode("unicode_escape").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def active_website(app: str) -> str:
    if not is_browser(app):
        return ""
    for url in (mpris_browser_url(), chromium_last_url(), firefox_last_url()):
        domain = domain_from_url(url or "")
        if domain:
            return domain
    title = active_window_title()
    if title:
        # "Page title - Brave" -> ignore; no reliable domain in title alone
        pass
    return ""


def merge_website_days(since: date, until: date) -> dict[str, int]:
    totals: dict[str, int] = {}
    d = since
    while d <= until:
        for site, secs in load_day(WEBSITE_DIR / f"{d.isoformat()}.json").items():
            totals[site] = totals.get(site, 0) + secs
        d += timedelta(days=1)
    return totals


def load_day(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {k: int(v) for k, v in data.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def save_day(path: Path, data: dict[str, int]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def normalize_app(name: str) -> str:
    name = re.sub(r"\s+", " ", name.strip())
    if not name:
        return "Unknown"
    # WM_CLASS often returns "firefox.Firefox" -> Firefox
    if "." in name and name == name.lower():
        name = name.rsplit(".", 1)[-1]
    return name[:80]


def user_idle_seconds() -> float | None:
    if host_platform() == "macos":
        return macos_idle_seconds()
    for cmd in (
        ["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor",
         "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
         "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime"],
        ["xprintidle"],
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if out.returncode != 0:
                continue
            text = out.stdout.strip()
            if cmd[0] == "xprintidle":
                return int(text) / 1000.0
            # gdbus returns "(uint32 12345,'')"
            m = re.search(r"uint32\s+(\d+)", text)
            if m:
                return int(m.group(1)) / 1000.0
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            continue
    return None


def active_app() -> str:
    if host_platform() == "macos":
        return macos_active_app()

    # GNOME Wayland / Shell
    js = (
        "(() => {"
        "  const w = global.display.focus_window;"
        "  if (!w) return 'Unknown';"
        "  const c = w.get_wm_class && w.get_wm_class();"
        "  const t = w.get_title && w.get_title();"
        "  return c || t || 'Unknown';"
        "})()"
    )
    try:
        out = subprocess.run(
            [
                "gdbus", "call", "--session", "--dest", "org.gnome.Shell",
                "--object-path", "/org/gnome/Shell",
                "--method", "org.gnome.Shell.Eval", js,
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if out.returncode == 0:
            m = re.search(r"'((?:\\'|[^'])*)'", out.stdout)
            if m:
                return normalize_app(m.group(1).encode().decode("unicode_escape"))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # X11 fallbacks
    for cmd in (
        ["bash", "-lc", "xdotool getwindowfocus getwindowname 2>/dev/null"],
        ["bash", "-lc", "xprop -id $(xdotool getwindowfocus 2>/dev/null) WM_CLASS 2>/dev/null | awk -F'\"' '{print $2}'"],
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
            if out.returncode == 0 and out.stdout.strip():
                return normalize_app(out.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return "Unknown"


def activitywatch_summary(days: int = 1) -> dict[str, int] | None:
    """Optional: merge ActivityWatch bucket data if running."""
    base = os.environ.get("ARKA_ACTIVITYWATCH_URL", "http://127.0.0.1:5600")
    try:
        with urllib.request.urlopen(f"{base}/api/0/buckets/", timeout=3) as resp:
            buckets = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    since = (datetime.now() - timedelta(days=days)).isoformat()
    totals: dict[str, int] = {}
    for bid, meta in buckets.items():
        if meta.get("type") != "currentwindow":
            continue
        app = normalize_app(meta.get("client", meta.get("id", "Unknown")))
        url = f"{base}/api/0/buckets/{urllib.parse.quote(bid, safe='')}/events?start={since}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                events = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        for ev in events:
            dur = ev.get("duration", 0)
            if isinstance(dur, (int, float)):
                totals[app] = totals.get(app, 0) + int(dur)
            elif isinstance(dur, dict):
                secs = dur.get("seconds", 0)
                totals[app] = totals.get(app, 0) + int(secs)
    return totals or None


def fmt_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def merge_days(since: date, until: date) -> dict[str, int]:
    totals: dict[str, int] = {}
    d = since
    while d <= until:
        for app, secs in load_day(USAGE_DIR / f"{d.isoformat()}.json").items():
            totals[app] = totals.get(app, 0) + secs
        d += timedelta(days=1)
    aw = activitywatch_summary(days=(until - since).days + 1)
    if aw:
        for app, secs in aw.items():
            totals[app] = max(totals.get(app, 0), secs)
    return totals


def report(period: str = "today", top: int = 15) -> str:
    today = date.today()
    if period in ("today", "day"):
        since = today
        label = "Today"
    elif period in ("week", "7d"):
        since = today - timedelta(days=6)
        label = "This week"
    elif period in ("yesterday",):
        since = today - timedelta(days=1)
        today = since
        label = "Yesterday"
    else:
        since = today
        label = period.capitalize()

    lines: list[str] = []
    gnome_secs = gnome_seconds_between(since, today)
    totals = merge_days(since, today)
    app_total = sum(totals.values()) if totals else 0

    # One-line summary first (works well for voice/TTS)
    summary_parts: list[str] = []
    if gnome_secs > 0:
        summary_parts.append(f"{fmt_duration(gnome_secs)} on the computer")
    if app_total > 0:
        top_app = max(totals.items(), key=lambda x: x[1])[0]
        summary_parts.append(f"top app {top_app} {fmt_duration(totals[top_app])}")
    if summary_parts:
        lines.append(f"{label}: " + ", ".join(summary_parts) + ".")
        lines.append("")

    if gnome_secs > 0 or (host_platform() == "linux" and gnome_history_enabled()):
        lines.append(f"{label}'s screen time (GNOME):")
        if since == today == date.today():
            completed, extra, total = gnome_today_total_seconds()
            if total > 0:
                if extra > 0 and completed > 0:
                    lines.append(
                        f"  Computer active — {fmt_duration(total)} "
                        f"({fmt_duration(completed)} logged + {fmt_duration(extra)} current session)"
                    )
                elif extra > 0:
                    lines.append(
                        f"  Computer active — {fmt_duration(total)} (current session, not fully logged yet)"
                    )
                else:
                    lines.append(f"  Computer active — {fmt_duration(total)}")
            else:
                lines.append("  Computer active — no recorded time in this period")
        elif gnome_secs > 0:
            lines.append(f"  Computer active — {fmt_duration(gnome_secs)}")
        else:
            lines.append("  Computer active — no recorded sessions in this period")
            week_secs = gnome_completed_seconds_between(today - timedelta(days=6), today)
            if week_secs > 0 and period in ("today", "day"):
                lines.append(f"  This week — {fmt_duration(week_secs)}")

    if totals:
        ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:top]
        lines.append("")
        lines.append(f"Per-app (Arka tracker — {fmt_duration(app_total)}):")
        for app, secs in ranked:
            pct = (secs / app_total * 100) if app_total else 0
            lines.append(f"  {app} — {fmt_duration(secs)} ({pct:.0f}%)")
    elif gnome_secs == 0:
        lines.append("")
        plat = host_platform()
        if plat == "macos":
            lines.append("Per-app: tracker runs in background — allow a few minutes to collect.")
        else:
            lines.append("Per-app: tracker runs automatically on login (needs time to collect).")

    if WEB_TRACK:
        sites = merge_website_days(since, today)
        if sites:
            site_total = sum(sites.values())
            ranked_s = sorted(sites.items(), key=lambda x: x[1], reverse=True)[:top]
            lines.append("")
            lines.append(f"Websites (Arka tracker — {fmt_duration(site_total)}):")
            for site, secs in ranked_s:
                pct = (secs / site_total * 100) if site_total else 0
                lines.append(f"  {site} — {fmt_duration(secs)} ({pct:.0f}%)")
            top_site = ranked_s[0][0]
            if summary_parts and site_total > 0:
                lines[0] = (
                    f"{label}: "
                    + ", ".join(summary_parts)
                    + f", top site {top_site} {fmt_duration(ranked_s[0][1])}."
                )
                if lines[1] == "":
                    pass
        elif totals or gnome_secs > 0:
            lines.append("")
            lines.append("Websites: browsing in Brave/Chrome/Firefox is tracked automatically.")

    if not lines:
        plat = host_platform()
        if plat == "macos":
            return (
                "No screen time data yet.\n"
                "App and website tracking start with: arka usage start\n"
                "(runs in background; allow a few minutes to collect data)"
            )
        if plat == "linux":
            return (
                "No screen time data yet.\n"
                "GNOME records session time when Screen Time history is enabled.\n"
                "App and website tracking start automatically on login."
            )
        return (
            "No screen time data yet.\n"
            "Start tracking with: arka usage start"
        )

    return "\n".join(lines)


def report_gnome_sessions(limit: int = 20) -> str:
    ranges = gnome_session_ranges()
    if not ranges:
        return "No GNOME session history (is history-enabled on?)"
    lines = ["GNOME login-session history (malcontent-timerd):"]
    for start, end in sorted(ranges, reverse=True)[:limit]:
        s = datetime.fromtimestamp(start).isoformat(sep=" ", timespec="seconds")
        e = datetime.fromtimestamp(end).isoformat(sep=" ", timespec="seconds")
        lines.append(f"  {s} → {e}  ({fmt_duration(end - start)})")
    return "\n".join(lines)


def track_loop() -> None:
    PID_FILE.write_text(str(os.getpid()))
    last_app = ""
    last_site = ""
    last_tick = time.time()

    def _credit(app: str, site: str, elapsed: int) -> None:
        if elapsed <= 0:
            return
        if app and app != "Unknown":
            path = today_file()
            data = load_day(path)
            data[app] = data.get(app, 0) + elapsed
            save_day(path, data)
        if WEB_TRACK and site:
            wpath = today_website_file()
            wdata = load_day(wpath)
            wdata[site] = wdata.get(site, 0) + elapsed
            save_day(wpath, wdata)

    def _stop(*_args):
        app = last_app
        site = last_site if WEB_TRACK and last_app and is_browser(last_app) else ""
        _credit(app, site, max(0, int(time.time() - last_tick)))
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while True:
        time.sleep(INTERVAL)
        now = time.time()
        elapsed = int(now - last_tick)
        last_tick = now

        idle = user_idle_seconds()
        if idle is not None and idle >= IDLE_SEC:
            last_app = ""
            last_site = ""
            continue

        app = active_app()
        if app == "Unknown":
            last_app = ""
            last_site = ""
            continue

        site = active_website(app) if WEB_TRACK and is_browser(app) else ""
        _credit(app, site, elapsed)
        last_app = app
        last_site = site


def start_daemon() -> None:
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            return
        except OSError:
            PID_FILE.unlink(missing_ok=True)
    log = CACHE / "arka_usage.log"
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as fh:
        subprocess.Popen(
            [sys.executable, __file__, "track"],
            stdout=fh,
            stderr=fh,
            start_new_session=True,
        )


def stop_daemon() -> None:
    if not PID_FILE.exists():
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    PID_FILE.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka app usage tracker")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("track")
    sub.add_parser("start")
    sub.add_parser("stop")
    p_rep = sub.add_parser("report")
    p_rep.add_argument("period", nargs="?", default="today")
    p_rep.add_argument("--top", type=int, default=15)
    sub.add_parser("gnome")

    args = parser.parse_args()
    if args.cmd == "track":
        track_loop()
        return 0
    if args.cmd == "start":
        start_daemon()
        mode = "app + website" if WEB_TRACK else "app"
        print(f"Usage tracker started ({mode}).", file=sys.stderr)
        return 0
    if args.cmd == "stop":
        stop_daemon()
        return 0
    if args.cmd == "report":
        print(report(args.period, args.top))
        return 0
    if args.cmd == "gnome":
        print(report_gnome_sessions())
        return 0

    print(report("today"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
