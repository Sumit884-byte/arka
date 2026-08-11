"""Load .env into os.environ (cross-platform)."""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from arka.paths import arka_home, cache_dir, checkout_root, config_dir, env_file

_PLACEHOLDER_RE = re.compile(
    # Match your_secret_here AND your-secret-here (hyphen form is common in templates)
    r"^your[-_].*[-_]here$|^your[-_]secret[-_]here$|^changeme$|^xxx+$|^replace[_-]?me$",
    re.IGNORECASE,
)

# Never map stripped keys to these (OS / shell collisions).
_BLOCKED_SHORT = frozenset({"HOME", "PATH", "USER", "SHELL", "PWD", "LANG", "TERM"})

# Path-like vars that must never keep template placeholders (OpenSSL writes SSLKEYLOGFILE).
_PATH_LIKE_KEYS = frozenset(
    {
        "SSLKEYLOGFILE",
        "KEYCHAIN_PATH",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "CURL_CA_BUNDLE",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "AWS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
    }
)


def _is_placeholder(val: str) -> bool:
    v = (val or "").strip()
    if not v:
        return True
    return bool(_PLACEHOLDER_RE.match(v))


def _is_path_like_key(key: str) -> bool:
    k = (key or "").strip().upper()
    if k in _PATH_LIKE_KEYS:
        return True
    return k.endswith(("_PATH", "_FILE", "_DIR", "_CREDENTIALS", "_CERT", "_BUNDLE"))


def _scrub_placeholder_env() -> None:
    """Remove placeholder values already present in the process environment."""
    for key, val in list(os.environ.items()):
        if not _is_placeholder(val):
            continue
        # Always drop path-like placeholders; they cause Errno 30 / broken TLS.
        if _is_path_like_key(key) or val.strip().lower() in {
            "your-secret-here",
            "your_secret_here",
        }:
            os.environ.pop(key, None)


def canonical_env_key(key: str) -> str:
    """Normalize .env keys: drop legacy ARKA_ prefix (one-way, not dual aliases)."""
    key = key.strip()
    if key == "ARKA_HOME":
        return "INSTALL_HOME"
    if key.startswith("ARKA_"):
        short = key[5:]
        if short in _BLOCKED_SHORT:
            return key
        return short
    return key


def _apply_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = canonical_env_key(key.strip())
        val = val.strip().strip("'\"")
        val = re.sub(r"\s+#.*$", "", val).strip()
        if not key or _is_placeholder(val):
            continue
        current = os.environ.get(key, "").strip()
        if not current or _is_placeholder(current):
            os.environ[key] = val


def env_get(key: str, default: str = "") -> str:
    """Read one env var (empty / placeholder → default)."""
    val = os.environ.get(key, "").strip()
    if val and not _is_placeholder(val):
        return val
    return default


def env_int(name: str, default: int) -> int:
    """Read int env var (missing / empty → default)."""
    return int(os.environ.get(name) or str(default))


_ENV_LOADED = False
_ENV_LOAD_LOCK = threading.Lock()


def reset_env_loaded() -> None:
    """Clear load-once guard (tests only)."""
    global _ENV_LOADED
    with _ENV_LOAD_LOCK:
        _ENV_LOADED = False


def load_env(extra: Path | None = None, *, force: bool = False) -> None:
    global _ENV_LOADED
    if not force and extra is None:
        with _ENV_LOAD_LOCK:
            if _ENV_LOADED:
                return

    paths: list[Path] = []
    if extra:
        paths.append(extra)
    root = checkout_root()
    if root:
        dev_env = root / ".env"
        if dev_env.is_file():
            paths.append(dev_env)
    paths.append(env_file())
    legacy = Path.home() / ".config" / "fish" / ".env"
    if legacy.is_file():
        paths.append(legacy)
    home_env = arka_home() / ".env"
    if home_env.is_file():
        paths.append(home_env)

    seen: set[Path] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        _apply_env_file(path)

    # Shell-sourced .env can leave placeholders in the process; scrub them.
    _scrub_placeholder_env()

    # Apply only Arka-managed defaults after explicit environment files.
    try:
        from arka.core.default_config import read as read_defaults

        defaults = read_defaults().get("defaults", {})
        if isinstance(defaults, dict):
            for key, value in defaults.items():
                if isinstance(key, str) and isinstance(value, str):
                    os.environ.setdefault(key, value)
    except (ImportError, OSError, ValueError, TypeError):
        pass

    os.environ.setdefault("CONFIG_DIR", str(config_dir()))
    os.environ.setdefault("CACHE_DIR", str(cache_dir()))

    try:
        from arka.core.network_proxy import apply_proxy_env

        apply_proxy_env()
    except ImportError:
        pass

    if extra is None:
        with _ENV_LOAD_LOCK:
            _ENV_LOADED = True
