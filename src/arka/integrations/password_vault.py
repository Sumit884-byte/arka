#!/usr/bin/env python3
"""Generate and store named passwords in an encrypted local vault."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import arka.paths as _ap

    _ap.load_env_file()
    FISH_DIR = _ap.arka_home()
    CACHE = _ap.cache_dir()
except ImportError:
    FISH_DIR = Path(__file__).resolve().parent
    CACHE = Path.home() / ".cache" / "fish-agent"

VAULT_FILE = CACHE / "passwords.vault.json"
KEY_FILE = CACHE / "vault.key"

DEFAULT_LENGTH = 20
NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def _load_env() -> None:
    try:
        import arka.paths as arka_paths

        arka_paths.load_env_file()
        return
    except ImportError:
        pass
    env_path = FISH_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


def _fernet():
    from cryptography.fernet import Fernet

    raw = os.environ.get("ARKA_VAULT_KEY", "").strip()
    if not raw:
        if KEY_FILE.is_file():
            raw = KEY_FILE.read_text(encoding="utf-8").strip()
        else:
            raw = Fernet.generate_key().decode()
            CACHE.mkdir(parents=True, exist_ok=True)
            KEY_FILE.write_text(raw + "\n", encoding="utf-8")
            try:
                KEY_FILE.chmod(0o600)
            except OSError:
                pass
            print(
                f"Created vault key: {KEY_FILE} (keep this file safe; back it up to recover passwords)",
                file=sys.stderr,
            )
    key = raw.encode() if isinstance(raw, str) else raw
    return Fernet(key)


def _validate_name(name: str) -> str:
    name = name.strip()
    if not NAME_RE.match(name):
        raise SystemExit(
            "Name must be 1–64 chars: letters, numbers, dot, underscore, hyphen (start with alphanumeric)."
        )
    return name


def _generate_password(length: int, *, symbols: bool = True) -> str:
    length = max(8, min(int(length), 128))
    alphabet = string.ascii_letters + string.digits
    if symbols:
        alphabet += "!@#$%^&*()-_=+[]{}"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd) and any(c.isdigit() for c in pwd):
            if not symbols or any(c in "!@#$%^&*()-_=+[]{}:" for c in pwd):
                return pwd


def _load_vault() -> dict:
    if not VAULT_FILE.is_file():
        return {"version": 1, "entries": {}}
    try:
        data = json.loads(VAULT_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            return data
    except json.JSONDecodeError:
        pass
    raise SystemExit(f"Vault file corrupted: {VAULT_FILE}")


def _save_vault(data: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    VAULT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        VAULT_FILE.chmod(0o600)
    except OSError:
        pass


def _encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def _decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def cmd_set(name: str, password: str, *, force: bool) -> int:
    name = _validate_name(name)
    password = password.strip("\n")
    if not password:
        raise SystemExit("Password cannot be empty.")
    if len(password) > 512:
        raise SystemExit("Password too long (max 512 characters).")
    vault = _load_vault()
    entries = vault["entries"]
    if name in entries and not force:
        print(f"Password '{name}' already exists. Use --force to replace.", file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries[name] = {
        "password_enc": _encrypt(password),
        "length": len(password),
        "symbols": None,
        "source": "manual",
        "created": entries.get(name, {}).get("created", now),
        "updated": now,
    }
    _save_vault(vault)
    print(f"__NAME__={name}")
    print(f"__STORED__=manual")
    print(f"__LENGTH__={len(password)}")
    return 0


def cmd_generate(name: str, length: int, *, symbols: bool, force: bool) -> int:
    name = _validate_name(name)
    vault = _load_vault()
    entries = vault["entries"]
    if name in entries and not force:
        print(f"Password '{name}' already exists. Use --force to replace.", file=sys.stderr)
        return 1
    pwd = _generate_password(length, symbols=symbols)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries[name] = {
        "password_enc": _encrypt(pwd),
        "length": length,
        "symbols": symbols,
        "source": "generated",
        "created": entries.get(name, {}).get("created", now),
        "updated": now,
    }
    _save_vault(vault)
    print(f"__NAME__={name}")
    print(f"__PASSWORD__={pwd}")
    return 0


def cmd_get(name: str, *, quiet: bool) -> int:
    name = _validate_name(name)
    vault = _load_vault()
    entry = vault["entries"].get(name)
    if not entry:
        print(f"No stored password named '{name}'.", file=sys.stderr)
        return 1
    pwd = _decrypt(entry["password_enc"])
    if quiet:
        print(pwd)
    else:
        print(f"__NAME__={name}")
        print(f"__PASSWORD__={pwd}")
        print(f"__UPDATED__={entry.get('updated', '?')}")
    return 0


def cmd_list() -> int:
    vault = _load_vault()
    entries = vault["entries"]
    if not entries:
        print("No stored passwords.")
        return 0
    print("STORED_PASSWORDS")
    for name in sorted(entries):
        e = entries[name]
        print(f"  {name}  (len={e.get('length', '?')}, source={e.get('source', '?')}, updated={e.get('updated', '?')})")
    return 0


def cmd_delete(name: str) -> int:
    name = _validate_name(name)
    vault = _load_vault()
    if name not in vault["entries"]:
        print(f"No stored password named '{name}'.", file=sys.stderr)
        return 1
    del vault["entries"][name]
    _save_vault(vault)
    print(f"DELETED:{name}")
    return 0


def cmd_once(length: int, *, symbols: bool) -> int:
    pwd = _generate_password(length, symbols=symbols)
    print(f"__PASSWORD__={pwd}")
    print(f"__LENGTH__={length}")
    return 0


def cmd_rotate(name: str, length: int, *, symbols: bool) -> int:
    return cmd_generate(name, length, symbols=symbols, force=True)


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Arka encrypted password vault")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("generate", help="Generate and store a password")
    p.add_argument("name")
    p.add_argument("--length", "-l", type=int, default=DEFAULT_LENGTH)
    p.add_argument("--no-symbols", action="store_true")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("set", help="Store an existing password by name")
    p.add_argument("name")
    p.add_argument("--password", "-p", required=True, help="Password to store (use -p or pipe via stdin)")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("get", help="Retrieve a stored password")
    p.add_argument("name")
    p.add_argument("--quiet", "-q", action="store_true")

    sub.add_parser("list", help="List stored password names")

    p = sub.add_parser("delete", help="Delete a stored password")
    p.add_argument("name")

    p = sub.add_parser("rotate", help="Generate a new password for an existing name")
    p.add_argument("name")
    p.add_argument("--length", "-l", type=int, default=DEFAULT_LENGTH)
    p.add_argument("--no-symbols", action="store_true")

    p = sub.add_parser("once", help="Generate a one-time password (not stored)")
    p.add_argument("--length", "-l", type=int, default=DEFAULT_LENGTH)
    p.add_argument("--no-symbols", action="store_true")

    args = parser.parse_args()
    sym = not getattr(args, "no_symbols", False)

    if args.cmd == "generate":
        return cmd_generate(args.name, args.length, symbols=sym, force=args.force)
    if args.cmd == "set":
        pwd = args.password
        if pwd == "-":
            pwd = sys.stdin.read()
        return cmd_set(args.name, pwd, force=args.force)
    if args.cmd == "get":
        return cmd_get(args.name, quiet=args.quiet)
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "delete":
        return cmd_delete(args.name)
    if args.cmd == "rotate":
        return cmd_rotate(args.name, args.length, symbols=sym)
    if args.cmd == "once":
        return cmd_once(args.length, symbols=sym)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
