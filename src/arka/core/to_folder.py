"""cd to a folder by name — portable resolver and NL routing."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _canonical_dir(path: Path) -> Path | None:
    try:
        p = path.expanduser()
        if not p.is_dir():
            return None
        return p.resolve()
    except OSError:
        return None


def _xdg_dir(name: str) -> Path | None:
    try:
        proc = subprocess.run(
            ["xdg-user-dir", name],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0:
            p = Path(proc.stdout.strip())
            if p.is_dir():
                return p
    except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def resolve_folder(name: str, *, cwd: Path | None = None, home: Path | None = None) -> Path | None:
    """Resolve a folder name to an absolute path (first unique match)."""
    name = name.strip()
    if not name:
        return None
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    low = name.casefold()

    try:
        from arka.core.folder_cache import (
            fuzzy_home_match,
            get_cached_folder,
            remember_folder,
            resolve_alias,
        )

        cached = get_cached_folder(name)
        if cached is not None:
            return cached
        aliased = resolve_alias(name, home=home)
        if aliased is not None:
            remember_folder(name, aliased)
            return aliased
    except ImportError:
        pass

    raw: list[Path] = [cwd / name, home / name]

    for xdg in ("DOWNLOAD", "DOCUMENTS", "DESKTOP", "PICTURE", "MUSIC", "VIDEO"):
        d = _xdg_dir(xdg)
        if d and d.name.casefold() == low:
            raw.append(d)

    for base in (home, cwd):
        if not base.is_dir():
            continue
        try:
            for d in base.iterdir():
                if d.is_dir() and d.name.casefold() == low:
                    raw.append(d)
        except OSError:
            pass

    seen: set[Path] = set()
    candidates: list[Path] = []
    for p in raw:
        c = _canonical_dir(p)
        if c and c not in seen:
            seen.add(c)
            candidates.append(c)

    if not candidates:
        try:
            proc = subprocess.run(
                ["find", str(home), "-maxdepth", "4", "-type", "d", "-iname", name],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for line in proc.stdout.splitlines()[:20]:
                c = _canonical_dir(Path(line))
                if c and c not in seen:
                    seen.add(c)
                    candidates.append(c)
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if len(candidates) == 1:
        result = candidates[0]
    elif candidates:
        result = candidates[0]
    else:
        try:
            from arka.core.folder_cache import fuzzy_home_match, remember_folder

            result = fuzzy_home_match(name, home=home)
        except ImportError:
            result = None

    if result is not None:
        try:
            from arka.core.folder_cache import remember_folder

            remember_folder(name, result)
        except ImportError:
            pass
    return result


def parse_folder_name(text: str) -> str | None:
    cmd = re.sub(r"(?i)^arka\s+", "", (text or "").strip())
    if not cmd:
        return None

    if re.match(
        r"(?i)^(?:convert|translate|send|post|dub|rename|move|copy|export|save|write|listen|remind)\b",
        cmd,
    ):
        return None

    m = re.match(r"(?i)^to\s+(.+)$", cmd)
    if m:
        return m.group(1).strip()

    m = re.match(
        r"(?i)^(?:go|cd|change|navigate)\s+to\s+(?:folder|directory)\s+(.+)$",
        cmd,
    )
    if m:
        return m.group(1).strip()

    m = re.match(
        r"(?i)^(?:go|cd|change|navigate)\s+to\s+(?:the\s+)?(?:my\s+)?"
        r"(downloads?|documents?|desktop|pictures?|photos?|music|videos?|projects?|home)\b"
        r"(?:\s+(?:folder|directory))?\s*$",
        cmd,
    )
    if m:
        return m.group(1).strip()

    m = re.match(
        r"(?i)^(?:go|cd|change|navigate)\s+to\s+(?:the\s+)?(?:my\s+)?"
        r"(.+?)(?:\s+(?:folder|directory))?\s*$",
        cmd,
    )
    if m:
        tail = m.group(1).strip()
        if tail and not re.search(r"(?i)\b(?:youtube|spotify|gym|bed|sleep|work|school|store|shop|url|site|page)\b", tail):
            return tail
    return None


def route_command(cmd: str) -> str | None:
    name = parse_folder_name(cmd)
    if not name:
        return None
    return f"to {name}"


def nl_to_argv(text: str) -> list[str] | None:
    name = parse_folder_name(text)
    if not name:
        return []
    return ["to", name]
