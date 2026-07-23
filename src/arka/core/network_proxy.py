#!/usr/bin/env python3
"""Outbound proxy and VPN-aware networking for Arka.

Env vars (standard — respected by curl, Python urllib, httpx, requests):
  HTTP_PROXY, HTTPS_PROXY, ALL_PROXY, NO_PROXY

Arka aliases (ARKA_* keys normalize on load via env.canonical_env_key):
  PROXY              — single URL applied to HTTP/HTTPS when those are unset
  NO_PROXY           — from ARKA_NO_PROXY; merged with existing NO_PROXY
  PROXY_ENABLED      — from ARKA_PROXY_ENABLED; 0/false/off disables apply_proxy_env
  VPN_PROXY          — from ARKA_VPN_PROXY; auto-applied when a VPN interface is up
  VPN_INTERFACE      — from ARKA_VPN_INTERFACE; extra interface name to treat as VPN
  PROXY_LIST         — from ARKA_PROXY_LIST; comma-separated proxy pool
  PROXY_LIST_FILE    — from ARKA_PROXY_LIST_FILE; file path (lines or JSON array)
  PROXY_ROTATION     — from ARKA_PROXY_ROTATION; round-robin|random|sticky (default round-robin)
  PROXY_ROTATE_ON_FAIL — from ARKA_PROXY_ROTATE_ON_FAIL; 1 rotates pool on proxy_test failure

Toggle without editing .env: ``~/.config/arka/proxy.enabled`` (1/0), set by
``arka proxy on`` / ``arka proxy off``.

Rotation state persists in ``~/.cache/arka/proxy-rotation.json``.
CLI: ``arka proxy rotate | list | use <index|url>``.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

try:
    from arka.env import env_get
    from arka.paths import cache_dir, config_dir, load_env_file
except ImportError:

    def load_env_file() -> None:
        pass

    def env_get(key: str, default: str = "") -> str:
        val = os.environ.get(key, "").strip()
        return val or default

    def config_dir() -> Path:
        if v := os.environ.get("CONFIG_DIR", "").strip():
            return Path(v).expanduser().resolve()
        return Path.home() / ".config" / "arka"

    def cache_dir() -> Path:
        if v := os.environ.get("CACHE_DIR", "").strip():
            return Path(v).expanduser().resolve()
        return Path.home() / ".cache" / "arka"


_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
_PROXY_KEY_ALIASES = ("http_proxy", "https_proxy", "all_proxy", "no_proxy")
_TEST_URL = "https://api.ipify.org?format=json"
_VPN_IF_RE = re.compile(
    r"^(?:tailscale\d*|wg\d+|tun\d+|tap\d+|utun\d+|zt\w*|nebula\d*|nordlynx\d*|ppp\d+)$",
    re.IGNORECASE,
)
_PROXY_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"(?:check|show|test|status|rotate|list)\s+(?:my\s+)?(?:proxy|proxies|vpn)|"
    r"proxy\s+(?:status|test|on|off|rotate|list|use)|"
    r"rotate\s+proxy|"
    r"vpn\s+(?:status|connected|active)|"
    r"network\s+proxy"
    r")\b"
)
_ROTATION_MODES = frozenset({"round-robin", "random", "sticky"})


def proxy_enabled_file() -> Path:
    return config_dir() / "proxy.enabled"


def proxy_rotation_state_file() -> Path:
    return cache_dir() / "proxy-rotation.json"


def _truthy(raw: str, *, default: bool = True) -> bool:
    val = (raw or "").strip().lower()
    if not val:
        return default
    return val not in ("0", "false", "no", "off")


def is_proxy_enabled() -> bool:
    """Whether Arka should propagate proxy env mappings."""
    env_val = env_get("PROXY_ENABLED", "")
    if env_val:
        return _truthy(env_val, default=True)
    path = proxy_enabled_file()
    if path.is_file():
        try:
            return _truthy(path.read_text(encoding="utf-8"), default=True)
        except OSError:
            pass
    return True


def set_proxy_enabled(enabled: bool) -> None:
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    proxy_enabled_file().write_text("1\n" if enabled else "0\n", encoding="utf-8")
    os.environ["PROXY_ENABLED"] = "1" if enabled else "0"
    apply_proxy_env()


def _set_if_empty(key: str, value: str, applied: dict[str, str]) -> None:
    if not value or os.environ.get(key, "").strip():
        return
    os.environ[key] = value
    applied[key] = value


def _set_proxy_values(proxy: str, applied: dict[str, str], *, force: bool = False) -> None:
    if not proxy:
        return
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        if force or not os.environ.get(key, "").strip():
            os.environ[key] = proxy
            applied[key] = proxy


def _parse_proxy_entries(raw: str) -> list[str]:
    text = (raw or "").replace("\n", ",")
    entries: list[str] = []
    for chunk in text.split(","):
        val = chunk.strip()
        if val and not val.startswith("#"):
            entries.append(val)
    return entries


def load_proxy_pool() -> list[str]:
    """Return configured proxy URLs from PROXY_LIST and/or PROXY_LIST_FILE."""
    pool: list[str] = []
    file_path = env_get("PROXY_LIST_FILE")
    if file_path:
        path = Path(file_path).expanduser()
        if path.is_file():
            try:
                raw = path.read_text(encoding="utf-8").strip()
            except OSError:
                raw = ""
            if raw.startswith("["):
                try:
                    payload = json.loads(raw)
                    if isinstance(payload, list):
                        pool.extend(str(item).strip() for item in payload if str(item).strip())
                except json.JSONDecodeError:
                    pass
            else:
                for line in raw.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        pool.append(line)
    pool.extend(_parse_proxy_entries(env_get("PROXY_LIST")))
    seen: set[str] = set()
    unique: list[str] = []
    for url in pool:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def rotation_mode() -> str:
    mode = env_get("PROXY_ROTATION", "round-robin").strip().lower()
    return mode if mode in _ROTATION_MODES else "round-robin"


def load_rotation_state() -> dict[str, Any]:
    path = proxy_rotation_state_file()
    if not path.is_file():
        return {"index": 0, "pinned": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"index": 0, "pinned": False}
    if not isinstance(payload, dict):
        return {"index": 0, "pinned": False}
    index = payload.get("index", 0)
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = 0
    return {"index": max(0, index), "pinned": bool(payload.get("pinned", False))}


def save_rotation_state(*, index: int, pinned: bool | None = None) -> None:
    path = proxy_rotation_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = load_rotation_state()
    if pinned is not None:
        state["pinned"] = pinned
    state["index"] = max(0, int(index))
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def active_pool_index(pool: list[str]) -> int:
    if not pool:
        return -1
    state = load_rotation_state()
    index = state.get("index", 0)
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = 0
    mode = rotation_mode()
    if mode == "random" and not state.get("pinned") and index >= len(pool):
        index = random.randrange(len(pool))
        save_rotation_state(index=index, pinned=False)
    return index % len(pool)


def pick_pool_proxy(pool: list[str] | None = None) -> tuple[str, int]:
    """Return (proxy_url, index) for the current rotation state."""
    entries = pool if pool is not None else load_proxy_pool()
    if not entries:
        return "", -1
    index = active_pool_index(entries)
    return entries[index], index


def rotate_proxy(*, advance: bool = True) -> tuple[str, int]:
    """Advance rotation and apply the next pool proxy. Returns (url, index)."""
    pool = load_proxy_pool()
    if not pool:
        raise ValueError("no proxy pool configured (set PROXY_LIST or PROXY_LIST_FILE)")
    state = load_rotation_state()
    current = int(state.get("index", 0)) % len(pool)
    mode = rotation_mode()
    if advance:
        if mode == "random":
            next_index = random.randrange(len(pool))
        else:
            next_index = (current + 1) % len(pool)
    else:
        next_index = current
    save_rotation_state(index=next_index, pinned=False)
    proxy = pool[next_index]
    applied = apply_proxy_env()
    return proxy, next_index


def pin_proxy(spec: str) -> tuple[str, int]:
    """Pin a pool entry by 0-based index or exact URL. Returns (url, index)."""
    pool = load_proxy_pool()
    if not pool:
        raise ValueError("no proxy pool configured (set PROXY_LIST or PROXY_LIST_FILE)")
    target = (spec or "").strip()
    if not target:
        raise ValueError("usage: arka proxy use <index|url>")
    index = -1
    if target.isdigit():
        index = int(target)
        if index < 0 or index >= len(pool):
            raise ValueError(f"index out of range: {index} (pool size {len(pool)})")
    else:
        for idx, url in enumerate(pool):
            if url == target:
                index = idx
                break
        if index < 0:
            raise ValueError(f"proxy not in pool: {redact_proxy_url(target)}")
    save_rotation_state(index=index, pinned=True)
    apply_proxy_env()
    return pool[index], index


def rotate_proxy_on_error() -> tuple[str, int] | None:
    """Advance pool on failure when PROXY_ROTATE_ON_FAIL is enabled."""
    if not _truthy(env_get("PROXY_ROTATE_ON_FAIL", ""), default=False):
        return None
    if not load_proxy_pool():
        return None
    try:
        return rotate_proxy(advance=True)
    except ValueError:
        return None


def detect_vpn_interfaces() -> list[dict[str, str]]:
    """Return active network interfaces that look like VPN tunnels."""
    names: set[str] = set()
    extra = env_get("VPN_INTERFACE", "").strip()
    if extra:
        names.add(extra)

    try:
        import psutil

        stats = psutil.net_if_stats()
        for name, info in stats.items():
            if not info.isup:
                continue
            if _VPN_IF_RE.match(name):
                names.add(name)
    except (ImportError, OSError, AttributeError):
        pass

    rows: list[dict[str, str]] = []
    for name in sorted(names):
        kind = "custom"
        lower = name.lower()
        if lower.startswith("tailscale"):
            kind = "tailscale"
        elif lower.startswith("wg"):
            kind = "wireguard"
        elif lower.startswith(("tun", "tap", "utun")):
            kind = "openvpn/tun"
        elif lower.startswith("zt"):
            kind = "zerotier"
        rows.append({"name": name, "kind": kind})
    return rows


def vpn_active() -> bool:
    return bool(detect_vpn_interfaces())


def apply_proxy_env() -> dict[str, str]:
    """Apply proxy mappings into os.environ for this process and child tools."""
    if not is_proxy_enabled():
        return {}

    applied: dict[str, str] = {}
    pool = load_proxy_pool()
    if pool:
        proxy, _index = pick_pool_proxy(pool)
        _set_proxy_values(proxy, applied, force=True)
    else:
        proxy = env_get("PROXY") or env_get("HTTP_PROXY") or env_get("HTTPS_PROXY")
        if not proxy and vpn_active():
            proxy = env_get("VPN_PROXY")

        if proxy:
            _set_if_empty("HTTP_PROXY", proxy, applied)
            _set_if_empty("HTTPS_PROXY", proxy, applied)
            _set_if_empty("ALL_PROXY", proxy, applied)

        https = env_get("HTTPS_PROXY")
        if https:
            _set_if_empty("ALL_PROXY", https, applied)

    for upper, lower in zip(_PROXY_KEYS, _PROXY_KEY_ALIASES):
        val = os.environ.get(upper, "").strip()
        if val and not os.environ.get(lower, "").strip():
            os.environ[lower] = val
            applied[lower] = val

    return applied


def redact_proxy_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "***"
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"***@{host}{port}"
        return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return url


@dataclass(frozen=True)
class ProxyConfig:
    enabled: bool
    http_proxy: str
    https_proxy: str
    all_proxy: str
    no_proxy: str
    source_proxy: str
    vpn_active: bool
    vpn_interfaces: tuple[dict[str, str], ...]
    applied_keys: tuple[str, ...]
    pool_size: int
    pool_index: int
    rotation_mode: str
    pool_pinned: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "http_proxy": redact_proxy_url(self.http_proxy),
            "https_proxy": redact_proxy_url(self.https_proxy),
            "all_proxy": redact_proxy_url(self.all_proxy),
            "no_proxy": self.no_proxy,
            "source_proxy": redact_proxy_url(self.source_proxy),
            "vpn_active": self.vpn_active,
            "vpn_interfaces": list(self.vpn_interfaces),
            "applied_keys": list(self.applied_keys),
            "pool_size": self.pool_size,
            "pool_index": self.pool_index,
            "rotation_mode": self.rotation_mode,
            "pool_pinned": self.pool_pinned,
        }


def proxy_config() -> ProxyConfig:
    applied = apply_proxy_env()
    interfaces = tuple(detect_vpn_interfaces())
    pool = load_proxy_pool()
    state = load_rotation_state()
    pool_index = active_pool_index(pool) if pool else -1
    return ProxyConfig(
        enabled=is_proxy_enabled(),
        http_proxy=env_get("HTTP_PROXY"),
        https_proxy=env_get("HTTPS_PROXY"),
        all_proxy=env_get("ALL_PROXY"),
        no_proxy=env_get("NO_PROXY"),
        source_proxy=env_get("PROXY") or env_get("VPN_PROXY"),
        vpn_active=bool(interfaces),
        vpn_interfaces=interfaces,
        applied_keys=tuple(sorted(applied)),
        pool_size=len(pool),
        pool_index=pool_index,
        rotation_mode=rotation_mode(),
        pool_pinned=bool(state.get("pinned")),
    )


def doctor_lines() -> list[str]:
    cfg = proxy_config()
    lines = ["  Proxy:"]
    if not cfg.enabled:
        lines.append("    status: disabled (PROXY_ENABLED=0 or arka proxy off)")
    elif cfg.http_proxy or cfg.https_proxy or cfg.all_proxy:
        lines.append(f"    HTTP:  {redact_proxy_url(cfg.http_proxy) or '-'}")
        lines.append(f"    HTTPS: {redact_proxy_url(cfg.https_proxy) or '-'}")
        if cfg.all_proxy:
            lines.append(f"    ALL:   {redact_proxy_url(cfg.all_proxy)}")
    elif cfg.source_proxy:
        lines.append(f"    source: {redact_proxy_url(cfg.source_proxy)} (not applied — check PROXY_ENABLED)")
    else:
        lines.append("    status: none configured")
    if cfg.no_proxy:
        lines.append(f"    NO_PROXY: {cfg.no_proxy[:120]}")
    if cfg.vpn_interfaces:
        names = ", ".join(f"{row['name']} ({row['kind']})" for row in cfg.vpn_interfaces)
        lines.append(f"    VPN:   active — {names}")
        if env_get("VPN_PROXY") and not (cfg.http_proxy or cfg.https_proxy):
            lines.append(f"    hint:  set VPN_PROXY={redact_proxy_url(env_get('VPN_PROXY'))} or HTTPS_PROXY")
    else:
        lines.append("    VPN:   not detected")
    if cfg.pool_size:
        active = cfg.pool_index if cfg.pool_index >= 0 else 0
        pin = " pinned" if cfg.pool_pinned else ""
        lines.append(
            f"    pool:  {cfg.pool_size} proxies, index {active}, mode {cfg.rotation_mode}{pin}"
        )
    return lines


def proxy_test(*, url: str = _TEST_URL, timeout: float = 12.0) -> dict[str, Any]:
    apply_proxy_env()
    req = urllib.request.Request(url, headers={"User-Agent": "arka-proxy-test/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        rotated = rotate_proxy_on_error()
        result: dict[str, Any] = {
            "ok": False,
            "url": url,
            "error": f"HTTP {exc.code}",
            "proxy": proxy_config().as_dict(),
        }
        if rotated:
            result["rotated_to"] = redact_proxy_url(rotated[0])
            result["rotated_index"] = rotated[1]
        return result
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        rotated = rotate_proxy_on_error()
        result: dict[str, Any] = {
            "ok": False,
            "url": url,
            "error": str(exc),
            "proxy": proxy_config().as_dict(),
        }
        if rotated:
            result["rotated_to"] = redact_proxy_url(rotated[0])
            result["rotated_index"] = rotated[1]
        return result

    ip = ""
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            ip = str(payload.get("ip") or "")
    except json.JSONDecodeError:
        ip = body.strip()[:80]
    return {
        "ok": True,
        "url": url,
        "ip": ip,
        "proxy": proxy_config().as_dict(),
    }


def cmd_status(_args: argparse.Namespace) -> int:
    cfg = proxy_config()
    print(f"enabled={cfg.enabled}")
    print(f"http_proxy={redact_proxy_url(cfg.http_proxy) or '-'}")
    print(f"https_proxy={redact_proxy_url(cfg.https_proxy) or '-'}")
    print(f"all_proxy={redact_proxy_url(cfg.all_proxy) or '-'}")
    print(f"no_proxy={cfg.no_proxy or '-'}")
    if cfg.source_proxy:
        print(f"source={redact_proxy_url(cfg.source_proxy)}")
    if cfg.vpn_interfaces:
        print("vpn=active")
        for row in cfg.vpn_interfaces:
            print(f"  {row['name']}\t{row['kind']}")
    else:
        print("vpn=none")
    if cfg.applied_keys:
        print(f"applied={','.join(cfg.applied_keys)}")
    if cfg.pool_size:
        print(f"pool_size={cfg.pool_size}")
        print(f"pool_index={cfg.pool_index}")
        print(f"rotation_mode={cfg.rotation_mode}")
        if cfg.pool_pinned:
            print("pool_pinned=true")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    result = proxy_test(url=str(getattr(args, "url", _TEST_URL)), timeout=float(getattr(args, "timeout", 12.0)))
    if result.get("ok"):
        print(f"ok ip={result.get('ip') or '?'} url={result['url']}")
        return 0
    print(f"fail error={result.get('error')} url={result['url']}", file=sys.stderr)
    return 1


def cmd_on(_args: argparse.Namespace) -> int:
    set_proxy_enabled(True)
    apply_proxy_env()
    print("proxy enabled")
    return 0


def cmd_off(_args: argparse.Namespace) -> int:
    set_proxy_enabled(False)
    print("proxy disabled (explicit HTTP_PROXY in .env is unchanged)")
    return 0


def cmd_rotate(_args: argparse.Namespace) -> int:
    try:
        proxy, index = rotate_proxy()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"active index={index} proxy={redact_proxy_url(proxy)}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    pool = load_proxy_pool()
    if not pool:
        print("pool=empty (set PROXY_LIST or PROXY_LIST_FILE)")
        return 0
    active = active_pool_index(pool)
    mode = rotation_mode()
    state = load_rotation_state()
    print(f"pool_size={len(pool)} rotation_mode={mode} active_index={active}")
    if state.get("pinned"):
        print("pinned=true")
    for idx, url in enumerate(pool):
        marker = "*" if idx == active else " "
        print(f"{marker} [{idx}] {redact_proxy_url(url)}")
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    spec = str(getattr(args, "target", "") or "").strip()
    try:
        proxy, index = pin_proxy(spec)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"pinned index={index} proxy={redact_proxy_url(proxy)}")
    return 0


def wants_proxy_status(text: str) -> bool:
    return bool(_PROXY_TRIGGER_RE.search(text or ""))


def route_command(text: str) -> str:
    if not wants_proxy_status(text):
        return ""
    clean = (text or "").strip().lower()
    if re.search(r"\b(off|disable)\b", clean):
        return "proxy off"
    if re.search(r"\b(on|enable)\b", clean):
        return "proxy on"
    if re.search(r"\btest\b", clean):
        return "proxy test"
    if re.search(r"\brotate\b", clean):
        return "proxy rotate"
    if re.search(r"\blist\b", clean) and re.search(r"\bprox", clean):
        return "proxy list"
    return "proxy status"


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    apply_proxy_env()
    parser = argparse.ArgumentParser(description="Arka outbound proxy and VPN helpers")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to proxy command")
    p_route.add_argument("text", nargs="+")

    sub.add_parser("status", help="Show proxy and VPN status").set_defaults(func=cmd_status)
    sub.add_parser("on", help="Enable proxy env propagation").set_defaults(func=cmd_on)
    sub.add_parser("off", help="Disable proxy env propagation").set_defaults(func=cmd_off)
    sub.add_parser("rotate", help="Advance to the next pool proxy").set_defaults(func=cmd_rotate)
    sub.add_parser("list", help="Show proxy pool and active entry").set_defaults(func=cmd_list)

    p_use = sub.add_parser("use", help="Pin a pool proxy by index or URL")
    p_use.add_argument("target", help="0-based index or exact proxy URL")
    p_use.set_defaults(func=cmd_use)

    p_test = sub.add_parser("test", help="HTTP GET through configured proxy")
    p_test.add_argument("--url", default=_TEST_URL)
    p_test.add_argument("--timeout", type=float, default=12.0)
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args(argv)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    func = getattr(args, "func", None)
    if callable(func):
        return int(func(args) or 0)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
