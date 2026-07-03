#!/usr/bin/env python3
"""Spotify playback: AppleScript (macOS), playerctl (Linux), optional Web API search."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TRACK_ID_RE = re.compile(r"(?:spotify:track:|open\.spotify\.com/track/)([a-zA-Z0-9]{22})")
_TOKEN_CACHE: tuple[str, float] | None = None


def _env(*names: str) -> str:
    for name in names:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return ""


def _is_macos() -> bool:
    try:
        from arka.core.platform import cached_platform

        plat = cached_platform()
        if plat:
            return plat == "macos"
    except ImportError:
        pass
    return platform.system() == "Darwin"


def _mac_spotify_app() -> bool:
    return _is_macos() and Path("/Applications/Spotify.app").is_dir()


def _open_url(url: str) -> None:
    if _is_macos():
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _osascript(script: str, *, timeout: float = 30.0) -> tuple[int, str]:
    if not shutil.which("osascript"):
        return 1, ""
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, out


def _normalize_query(text: str) -> str:
    q = " ".join(text.split())
    q = re.sub(r"(?i)\s+on\s+spotify\s*", " ", q)
    q = re.sub(r"(?i)^spotify\s+", "", q)
    q = re.sub(r"(?i)^play\s+", "", q)
    q = re.sub(r"(?i)\s+(from|by)\s+", " ", q)
    q = re.sub(r"(?i)\b(song|songs|track|tracks|music|audio)\b", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _extract_track_id(text: str) -> str | None:
    m = TRACK_ID_RE.search(text)
    return m.group(1) if m else None


def _client_token() -> str | None:
    global _TOKEN_CACHE
    cid = _env("SPOTIPY_CLIENT_ID", "SPOTIFY_CLIENT_ID")
    secret = _env("SPOTIPY_CLIENT_SECRET", "SPOTIFY_CLIENT_SECRET")
    if not cid or not secret:
        return None
    now = time.time()
    if _TOKEN_CACHE and _TOKEN_CACHE[1] > now + 30:
        return _TOKEN_CACHE[0]
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        headers={"Authorization": f"Basic {_b64(cid + ':' + secret)}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        token = str(data.get("access_token") or "")
        expires = int(data.get("expires_in") or 3600)
        if token:
            _TOKEN_CACHE = (token, now + expires)
            return token
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        pass
    return None


def _b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode()).decode()


def _api_search(query: str, *, limit: int = 5) -> list[dict]:
    token = _client_token()
    if not token:
        return []
    params = urllib.parse.urlencode({"q": query, "type": "track", "limit": limit})
    req = urllib.request.Request(
        f"https://api.spotify.com/v1/search?{params}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        items = data.get("tracks", {}).get("items") or []
        hits: list[dict] = []
        for row in items:
            if not isinstance(row, dict):
                continue
            tid = row.get("id")
            if not tid:
                continue
            artists = row.get("artists") or []
            artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict))
            hits.append(
                {
                    "id": tid,
                    "name": row.get("name") or "",
                    "artist": artist,
                    "uri": row.get("uri") or f"spotify:track:{tid}",
                }
            )
        return hits
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return []


def _itunes_search(query: str, *, limit: int = 5) -> list[tuple[str, str]]:
    url = (
        "https://itunes.apple.com/search?"
        + urllib.parse.urlencode({"term": query, "entity": "song", "limit": limit})
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        out: list[tuple[str, str]] = []
        for row in data.get("results") or []:
            if not isinstance(row, dict):
                continue
            track = (row.get("trackName") or "").strip()
            artist = (row.get("artistName") or "").strip()
            if track:
                out.append((track, artist))
        return out
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return []


def _ddg_track_ids(query: str) -> list[str]:
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    ids: list[str] = []
    try:
        with DDGS() as ddgs:
            for row in ddgs.text(f"site:open.spotify.com/track {query}", max_results=8):
                href = row.get("href") or row.get("url") or ""
                body = row.get("body") or ""
                for blob in (href, body):
                    for m in TRACK_ID_RE.finditer(blob):
                        tid = m.group(1)
                        if tid not in ids:
                            ids.append(tid)
    except Exception:
        pass
    return ids


def _pick_best(hits: list[dict], query: str) -> dict | None:
    if not hits:
        return None
    q = query.lower()
    words = [w for w in re.split(r"\s+", q) if len(w) > 2]
    best = hits[0]
    best_score = -1.0
    for hit in hits:
        blob = f"{hit.get('name', '')} {hit.get('artist', '')}".lower()
        score = sum(2.0 for w in words if w in blob)
        if q in blob:
            score += 5.0
        if score > best_score:
            best_score = score
            best = hit
    return best


def _track_title(track_id: str) -> tuple[str, str]:
    url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track_id}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        title = (data.get("title") or "").strip()
        return title, ""
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return "", ""


def search_track(query: str) -> dict | None:
    """Resolve a song query to Spotify track metadata."""
    query = _normalize_query(query)
    if not query:
        return None

    tid = _extract_track_id(query)
    if tid:
        return {"id": tid, "name": query, "artist": "", "uri": f"spotify:track:{tid}"}

    hits = _api_search(query)
    if hits:
        return _pick_best(hits, query)

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials

        cid = _env("SPOTIPY_CLIENT_ID", "SPOTIFY_CLIENT_ID")
        secret = _env("SPOTIPY_CLIENT_SECRET", "SPOTIFY_CLIENT_SECRET")
        if cid and secret:
            sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=cid, client_secret=secret))
            raw = sp.search(q=query, type="track", limit=5)
            items = raw.get("tracks", {}).get("items") or []
            hits = []
            for row in items:
                artists = ", ".join(a.get("name", "") for a in row.get("artists") or [])
                hits.append(
                    {
                        "id": row.get("id"),
                        "name": row.get("name") or "",
                        "artist": artists,
                        "uri": row.get("uri") or "",
                    }
                )
            picked = _pick_best(hits, query)
            if picked:
                return picked
    except ImportError:
        pass
    except Exception:
        pass

    for track, artist in _itunes_search(query):
        term = f"{track} {artist}".strip()
        hits = _api_search(term)
        if hits:
            return _pick_best(hits, query)

    for tid in _ddg_track_ids(query):
        name, _ = _track_title(tid)
        return {"id": tid, "name": name or query, "artist": "", "uri": f"spotify:track:{tid}"}

    for track, artist in _itunes_search(query):
        for tid in _ddg_track_ids(f"{track} {artist}"):
            return {"id": tid, "name": track, "artist": artist, "uri": f"spotify:track:{tid}"}

    return None


def _mac_play_uri(uri: str) -> bool:
    uri = uri.replace('"', '\\"')
    script = f'''
tell application "Spotify"
    if not running then
        launch
        delay 2
    end if
    activate
    play track "{uri}"
end tell
'''
    code, err = _osascript(script, timeout=45)
    if code != 0:
        print(f"AppleScript error: {err or code}", file=sys.stderr)
        return False
    return True


def _mac_control(action: str) -> bool:
    mapping = {
        "play": "play",
        "pause": "pause",
        "stop": "pause",
        "toggle": "playpause",
        "playpause": "playpause",
        "next": "next track",
        "skip": "next track",
        "prev": "previous track",
        "previous": "previous track",
        "back": "previous track",
    }
    cmd = mapping.get(action.lower())
    if not cmd:
        return False
    script = f'''
tell application "Spotify"
    if not running then
        return "not running"
    end if
    {cmd}
end tell
'''
    code, _ = _osascript(script)
    return code == 0


def _mac_status() -> None:
    script = '''
tell application "Spotify"
    if not running then
        return "not running"
    end if
    set st to player state as string
    set tr to current track
    set tname to name of tr
    set tartist to artist of tr
    set talbum to album of tr
    return st & "||" & tname & "||" & tartist & "||" & talbum
end tell
'''
    code, out = _osascript(script)
    if code != 0 or not out:
        print("Spotify is not running.")
        return
    if out == "not running":
        print("Spotify is not running.")
        return
    parts = out.split("||")
    if len(parts) >= 4:
        print(f"Status: {parts[0]}")
        print(f"Track:  {parts[1]}")
        print(f"Artist: {parts[2]}")
        print(f"Album:  {parts[3]}")
    else:
        print(out)


def _linux_has_spotify() -> bool:
    if shutil.which("spotify"):
        return True
    try:
        proc = subprocess.run(["flatpak", "list", "--app"], capture_output=True, text=True, timeout=8)
        if "com.spotify.Client" in (proc.stdout or ""):
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc = subprocess.run(["snap", "list"], capture_output=True, text=True, timeout=8)
        if re.search(r"^spotify\s", proc.stdout or "", re.M):
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


def _linux_start_spotify() -> None:
    if shutil.which("spotify"):
        subprocess.Popen(["spotify"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif shutil.which("flatpak"):
        subprocess.Popen(
            ["flatpak", "run", "com.spotify.Client"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif shutil.which("snap"):
        subprocess.Popen(["snap", "run", "spotify"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _linux_play_uri(uri: str) -> bool:
    if not shutil.which("playerctl"):
        _open_url(uri.replace("spotify:", "https://open.spotify.com/").replace("track:", "track/"))
        return False
    if _linux_has_spotify():
        _linux_start_spotify()
        time.sleep(2)
    _open_url(uri if uri.startswith("http") else _spotify_web_url(uri))
    for _ in range(12):
        time.sleep(1)
        proc = subprocess.run(["playerctl", "--player=spotify", "play"], capture_output=True)
        if proc.returncode == 0:
            st = subprocess.run(["playerctl", "--player=spotify", "status"], capture_output=True, text=True)
            if "Playing" in (st.stdout or ""):
                return True
    return False


def _spotify_web_url(uri: str) -> str:
    if uri.startswith("spotify:track:"):
        return f"https://open.spotify.com/track/{uri.rsplit(':', 1)[-1]}"
    if uri.startswith("spotify:search:"):
        q = uri.split(":", 2)[-1]
        return f"https://open.spotify.com/search/{q}/tracks"
    if uri.startswith("http"):
        return uri
    return f"https://open.spotify.com/{uri.replace('spotify:', '')}"


def play_uri(uri: str) -> int:
    if _mac_spotify_app():
        if _mac_play_uri(uri):
            return 0
    if not _is_macos() and _linux_play_uri(uri):
        return 0
    _open_url(_spotify_web_url(uri))
    print("Opened Spotify in browser — click Play if needed.", file=sys.stderr)
    return 1


def play_track_id(track_id: str) -> int:
    return play_uri(f"spotify:track:{track_id}")


def play_query(query: str) -> int:
    query = _normalize_query(query)
    if not query:
        print("Usage: play_spotify <song or spotify URL>", file=sys.stderr)
        return 1

    hit = search_track(query)
    if hit:
        label = hit.get("name") or query
        artist = hit.get("artist") or ""
        if artist:
            print(f"✓ {label} — {artist}")
        else:
            print(f"✓ Track: {hit['id']}")
        return play_uri(hit["uri"])

    encoded = urllib.parse.quote(query)
    if _mac_spotify_app():
        print(f"Search not resolved — trying Spotify search: {query}")
        if _mac_play_uri(f"spotify:search:{encoded}"):
            return 0

    url = f"https://open.spotify.com/search/{encoded}/tracks"
    print(f"Could not resolve track — opening search: {query}", file=sys.stderr)
    print("Tip: set SPOTIPY_CLIENT_ID + SPOTIPY_CLIENT_SECRET in .env for reliable search.", file=sys.stderr)
    _open_url(url)
    return 1


def control(action: str, *, play_query_text: str = "") -> int:
    action = (action or "status").lower()
    if action == "play" and play_query_text.strip():
        return play_query(play_query_text)

    if _mac_spotify_app():
        if action == "status":
            _mac_status()
            return 0
        if _mac_control(action):
            print(f"Spotify: {action}")
            return 0

    if shutil.which("playerctl"):
        player = "spotify"
        proc = subprocess.run(["playerctl", "-l"], capture_output=True, text=True)
        players = (proc.stdout or "").splitlines()
        if "spotify" not in players:
            for p in players:
                if "spotify" in p.lower() or "chrome" in p.lower() or "brave" in p.lower():
                    player = p
                    break
        mapping = {"play": "play", "pause": "pause", "stop": "pause", "toggle": "play-pause", "playpause": "play-pause", "next": "next", "skip": "next", "prev": "previous", "previous": "previous", "back": "previous"}
        cmd = mapping.get(action)
        if cmd:
            subprocess.run(["playerctl", f"--player={player}", cmd], check=False)
            print(f"Spotify ({player}): {action}")
            return 0
        if action == "status":
            for key in ("status", "metadata", "title", "artist", "album"):
                pass
            st = subprocess.run(["playerctl", f"--player={player}", "status"], capture_output=True, text=True)
            title = subprocess.run(["playerctl", f"--player={player}", "metadata", "title"], capture_output=True, text=True)
            artist = subprocess.run(["playerctl", f"--player={player}", "metadata", "artist"], capture_output=True, text=True)
            print(f"Status: {(st.stdout or '').strip()}")
            print(f"Track:  {(title.stdout or '').strip()}")
            print(f"Artist: {(artist.stdout or '').strip()}")
            return 0

    print("No Spotify desktop app or playerctl available.", file=sys.stderr)
    return 1


def cmd_play(args: argparse.Namespace) -> int:
    if not args.query:
        print("Usage: arka_spotify.py play <song>", file=sys.stderr)
        return 1
    print("━━━ Spotify Playback ━━━")
    return play_query(" ".join(args.query))


def cmd_search(args: argparse.Namespace) -> int:
    hit = search_track(" ".join(args.query))
    if not hit:
        print("No match.")
        return 1
    print(json.dumps(hit, ensure_ascii=False))
    return 0


def cmd_control(args: argparse.Namespace) -> int:
    if args.action == "play" and args.rest:
        return play_query(" ".join(args.rest))
    return control(args.action)


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Arka Spotify playback")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_play = sub.add_parser("play", help="Search and play a song")
    p_play.add_argument("query", nargs="+")
    p_play.set_defaults(func=cmd_play)

    p_search = sub.add_parser("search", help="Resolve query to track JSON")
    p_search.add_argument("query", nargs="+")
    p_search.set_defaults(func=cmd_search)

    p_ctl = sub.add_parser("control", help="play|pause|next|prev|status")
    p_ctl.add_argument("action")
    p_ctl.add_argument("rest", nargs="*")
    p_ctl.set_defaults(func=cmd_control)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
