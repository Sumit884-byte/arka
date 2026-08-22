"""Google OAuth setup — MCP tool, CLI, and NL routing for Gmail/Calendar APIs."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from arka.integrations import google_oauth as oauth

REVOKE_URI = "https://oauth2.googleapis.com/revoke"
DEVICE_CODE_URI = "https://oauth2.googleapis.com/device/code"

SERVICE_SCOPES: dict[str, dict[str, Any]] = {
    "gmail": {
        "label": "Gmail",
        "recommended": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        "optional": [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.labels",
        ],
    },
    "calendar": {
        "label": "Google Calendar",
        "recommended": [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ],
        "optional": [
            "https://www.googleapis.com/auth/calendar",
        ],
    },
    "drive": {
        "label": "Google Drive",
        "recommended": [
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "optional": [
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive",
        ],
    },
    "profile": {
        "label": "OpenID profile",
        "recommended": ["openid", "email"],
        "optional": [],
    },
}

DEFAULT_SCOPES: tuple[str, ...] = oauth.SCOPES

_OAUTH_NL = re.compile(
    r"(?i)(?:"
    r"oauth\s+google|google\s+oauth|setup\s+google\s+oauth|google\s+oauth\s+(?:setup|login|status|scopes|refresh|revoke)|"
    r"connect\s+(?:my\s+)?google\s+account|link\s+(?:my\s+)?google\s+account|"
    r"google\s+(?:login|sign[\s-]?in|connect|auth|setup|status|logout|revoke|refresh)|"
    r"connect\s+(?:my\s+)?(?:google|gmail|calendar)|"
    r"sign[\s-]?in\s+(?:to\s+)?(?:google|gmail|calendar)"
    r")"
)


def _env_path() -> Path:
    try:
        from arka.paths import env_file

        return env_file()
    except ImportError:
        return Path.home() / ".config" / "arka" / ".env"


def _token_store_paths() -> dict[str, str]:
    cache = oauth._cache()
    return {
        "cache_dir": str(cache),
        "legacy_token_file": str(oauth._legacy_token_file()),
        "accounts_dir": str(oauth._accounts_dir()),
        "encryption_key_file": str(oauth._key_file()),
    }


def _granted_scopes(tokens: dict[str, Any] | None) -> list[str]:
    if not tokens:
        return []
    raw = str(tokens.get("scopes") or "").strip()
    if raw:
        return [part for part in raw.split() if part]
    return list(DEFAULT_SCOPES)


def _token_valid(tokens: dict[str, Any] | None) -> bool:
    if not tokens:
        return False
    access = str(tokens.get("access_token") or "")
    expires_at = float(tokens.get("expires_at") or 0)
    refresh = str(tokens.get("refresh_token") or "")
    if access and expires_at > time.time():
        return True
    return bool(refresh)


def _account_status(account: str | None = None) -> dict[str, Any]:
    tokens = oauth.load_tokens(account)
    email = str(tokens.get("email") or "").strip() if tokens else ""
    valid = _token_valid(tokens)
    return {
        "account": account,
        "email": email,
        "signed_in": bool(tokens),
        "token_valid": valid,
        "granted_scopes": _granted_scopes(tokens),
        "expires_at": float(tokens.get("expires_at") or 0) if tokens else 0,
        "path": str(oauth._token_file(account)),
    }


def setup_payload(*, dry_run: bool = False, open_console: bool = False) -> dict[str, Any]:
    configured = oauth.credentials_configured()
    redirect = oauth.redirect_uri()
    env_path = _env_path()
    payload: dict[str, Any] = {
        "provider": "google",
        "configured": configured,
        "dry_run": dry_run,
        "env_file": str(env_path),
        "redirect_uri": redirect,
        "env_keys": {
            "client_id": ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_CLIENT_ID"],
            "client_secret": ["GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_CLIENT_SECRET"],
            "redirect_uri": ["GOOGLE_OAUTH_REDIRECT_URI"],
            "port": ["GOOGLE_OAUTH_PORT"],
        },
        "steps": [
            "Enable Gmail API and Google Calendar API in Google Cloud Console.",
            "OAuth consent screen → External → Testing → add your Gmail as a test user.",
            "Create OAuth client ID → Web application.",
            f"Add authorized redirect URI: {redirect}",
            f"Add GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET to {env_path}",
            "Run: arka reload && arka oauth google login",
        ],
        "console_urls": {
            "credentials": "https://console.cloud.google.com/apis/credentials",
            "library": "https://console.cloud.google.com/apis/library",
            "consent": "https://console.cloud.google.com/apis/credentials/consent",
        },
        "cli": ["arka oauth google setup", "arka google oauth setup", "arka google login"],
        "mcp": {"tool": "arka_oauth", "action": "setup"},
    }
    if not configured:
        payload["next"] = "Add OAuth client credentials to .env, then run login."
    else:
        payload["next"] = "Credentials found — run login to link your Google account."
    if open_console and not dry_run:
        try:
            import webbrowser

            webbrowser.open(payload["console_urls"]["credentials"])
            payload["opened"] = payload["console_urls"]["credentials"]
        except OSError:
            payload["opened"] = None
    return payload


def status_payload(*, account: str | None = None) -> dict[str, Any]:
    id_key, sec_key = oauth.credentials_source()
    accounts = oauth.list_linked_accounts()
    rows = [_account_status(None)]
    for row in accounts:
        key = str(row.get("key") or "")
        if key:
            rows.append(_account_status(key))
    selected = _account_status(account) if account else None
    return {
        "provider": "google",
        "configured": oauth.credentials_configured(),
        "credentials_from": {"client_id": id_key or None, "client_secret": sec_key or None},
        "redirect_uri": oauth.redirect_uri(),
        "storage": _token_store_paths(),
        "default_scopes": list(DEFAULT_SCOPES),
        "linked_accounts": accounts,
        "accounts": rows,
        "selected_account": selected,
        "signed_in": bool(accounts),
        "cli": ["arka oauth status", "arka oauth google status", "arka google status"],
    }


def scopes_payload(*, service: str | None = None) -> dict[str, Any]:
    svc = (service or "").strip().lower()
    if svc:
        if svc not in SERVICE_SCOPES:
            raise ValueError(f"unknown service {service!r} — choose from: {', '.join(SERVICE_SCOPES)}")
        selected = {svc: SERVICE_SCOPES[svc]}
    else:
        selected = SERVICE_SCOPES
    tokens = oauth.load_tokens()
    granted = set(_granted_scopes(tokens))
    return {
        "provider": "google",
        "default_active_scopes": list(DEFAULT_SCOPES),
        "services": selected,
        "granted_scopes": sorted(granted),
        "note": "Arka's Google login uses the default_active_scopes bundle (Gmail + Calendar + openid/email).",
    }


def _revoke_remote(token: str) -> None:
    if not token:
        return
    oauth._http_json(
        REVOKE_URI,
        method="POST",
        data={"token": token},
    )


def refresh_payload(*, account: str | None = None) -> dict[str, Any]:
    if not oauth.credentials_configured():
        raise RuntimeError("Google OAuth not configured — run setup first")
    if not oauth.load_tokens(account):
        raise RuntimeError("Not signed in — run login first")
    access = oauth.get_access_token(account=account, force_refresh=True)
    tokens = oauth.load_tokens(account) or {}
    return {
        "ok": True,
        "provider": "google",
        "account": account,
        "email": str(tokens.get("email") or ""),
        "token_valid": True,
        "access_token_present": bool(access),
        "expires_at": float(tokens.get("expires_at") or 0),
    }


def revoke_payload(
    *,
    account: str | None = None,
    all_accounts: bool = False,
    remote: bool = True,
) -> dict[str, Any]:
    removed: list[dict[str, Any]] = []

    def _remove_one(acct: str | None, tokens: dict[str, Any] | None) -> None:
        if remote and tokens:
            tok = str(tokens.get("refresh_token") or tokens.get("access_token") or "")
            try:
                _revoke_remote(tok)
            except RuntimeError:
                pass
        oauth.clear_tokens(acct)
        removed.append(
            {
                "account": acct,
                "email": str((tokens or {}).get("email") or ""),
                "path": str(oauth._token_file(acct)),
            }
        )

    if all_accounts:
        legacy = oauth.load_tokens(None)
        if legacy:
            _remove_one(None, legacy)
        for row in oauth.list_linked_accounts():
            key = str(row.get("key") or "")
            tokens = oauth.load_tokens(key)
            if tokens:
                _remove_one(key, tokens)
        oauth.clear_all_tokens()
    elif account:
        tokens = oauth.load_tokens(account)
        if not tokens:
            raise RuntimeError(f"No stored tokens for account {account!r}")
        _remove_one(account, tokens)
    else:
        tokens = oauth.load_tokens(None)
        if not tokens and not oauth.list_linked_accounts():
            raise RuntimeError("Not signed in — nothing to revoke")
        _remove_one(None, tokens)

    return {"ok": True, "provider": "google", "revoked": removed}


def _poll_device_code(device_code: str, *, interval: int, timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    wait = max(interval, 5)
    while time.time() < deadline:
        time.sleep(wait)
        payload = oauth._http_json(
            oauth.TOKEN_URI,
            method="POST",
            data={
                "client_id": oauth.client_id(),
                "client_secret": oauth.client_secret(),
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        if payload.get("access_token"):
            return payload
        err = str(payload.get("error") or "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            wait += 5
            continue
        if err:
            raise RuntimeError(str(payload.get("error_description") or err))
    raise RuntimeError(f"Device authorization timed out after {timeout}s")


def run_device_login(
    *,
    timeout: int = 300,
    account: str | None = None,
    add_account: bool = False,
) -> dict[str, Any]:
    if not oauth.credentials_configured():
        raise RuntimeError("Google OAuth not configured — run setup first")
    payload = oauth._http_json(
        DEVICE_CODE_URI,
        method="POST",
        data={
            "client_id": oauth.client_id(),
            "scope": " ".join(DEFAULT_SCOPES),
        },
    )
    if payload.get("error"):
        raise RuntimeError(str(payload.get("error_description") or payload.get("error")))
    user_code = str(payload.get("user_code") or "")
    verification_url = str(payload.get("verification_url") or "https://google.com/device")
    device_code = str(payload.get("device_code") or "")
    interval = int(payload.get("interval") or 5)
    expires_in = int(payload.get("expires_in") or timeout)
    print(f"Go to {verification_url} and enter code: {user_code}\n")
    token_payload = _poll_device_code(device_code, interval=interval, timeout=min(timeout, expires_in))
    merged = oauth._merge_token_response(None, token_payload)
    email = oauth.resolve_user_email(token_payload)
    if email:
        merged["email"] = email
    merged["scopes"] = " ".join(DEFAULT_SCOPES)
    store_account: str | None = None
    if add_account:
        store_account = oauth._sanitize_account_key(account or email or "account")
        if account:
            merged["account_alias"] = account.strip()
    elif account:
        store_account = oauth._sanitize_account_key(account)
        merged["account_alias"] = account.strip()
    oauth.save_tokens(merged, account=store_account)
    return merged


def login_payload(
    *,
    open_browser: bool = True,
    headless: bool = False,
    timeout: int = 180,
    account: str | None = None,
    add_account: bool = False,
) -> dict[str, Any]:
    if not oauth.credentials_configured():
        return {
            "ok": False,
            "error": "Google OAuth not configured",
            "setup": setup_payload(dry_run=True),
        }
    if headless or not open_browser:
        try:
            merged = run_device_login(
                timeout=max(timeout, 300),
                account=account,
                add_account=add_account or bool(account),
            )
            mode = "device_code"
        except RuntimeError as exc:
            if "invalid_client" not in str(exc).lower() and "unsupported" not in str(exc).lower():
                raise
            merged = oauth.run_login(
                open_browser=False,
                timeout=timeout,
                account=account,
                add_account=add_account or bool(account),
            )
            mode = "loopback_url"
    else:
        merged = oauth.run_login(
            open_browser=True,
            timeout=timeout,
            account=account,
            add_account=add_account or bool(account),
        )
        mode = "browser"
    email = str(merged.get("email") or "")
    return {
        "ok": True,
        "provider": "google",
        "mode": mode,
        "email": email,
        "account": account,
        "granted_scopes": _granted_scopes(merged),
        "storage": str(oauth._token_file(account if (add_account or account) else None)),
    }


def handle_action(arguments: dict[str, Any]) -> dict[str, Any]:
    provider = str(arguments.get("provider") or "google").strip().lower()
    if provider not in ("google", "gmail", "calendar"):
        raise ValueError("provider must be google (aliases: gmail, calendar)")
    action = str(arguments.get("action") or "status").strip().lower()
    account = str(arguments.get("account") or "").strip() or None
    dry_run = bool(arguments.get("dry_run", False))

    if action in ("setup", "configure", "config"):
        return setup_payload(
            dry_run=dry_run or not oauth.credentials_configured(),
            open_console=bool(arguments.get("open_console", False)),
        )
    if action == "status":
        return status_payload(account=account)
    if action == "scopes":
        service = str(arguments.get("service") or "").strip() or None
        return scopes_payload(service=service)
    if action in ("login", "setup_login"):
        if dry_run:
            return setup_payload(dry_run=True)
        return login_payload(
            open_browser=not bool(arguments.get("no_browser", False)),
            headless=bool(arguments.get("headless", False)),
            timeout=int(arguments.get("timeout") or 180),
            account=account,
            add_account=bool(arguments.get("add", False)),
        )
    if action == "refresh":
        return refresh_payload(account=account)
    if action in ("revoke", "logout"):
        return revoke_payload(
            account=account,
            all_accounts=bool(arguments.get("all", False)),
            remote=not bool(arguments.get("local_only", False)),
        )
    raise ValueError("action must be status, setup, login, scopes, refresh, or revoke")


def is_oauth_request(text: str) -> bool:
    return bool(_OAUTH_NL.search((text or "").strip()))


def route_command(text: str) -> str | None:
    cmd = (text or "").strip()
    if not is_oauth_request(cmd):
        return None
    lower = cmd.lower()
    if re.search(r"(?i)\b(setup|configure|config)\b", lower):
        return "oauth google setup"
    if re.search(r"(?i)\b(scopes|scope)\b", lower):
        return "oauth google scopes"
    if re.search(r"(?i)\b(refresh)\b", lower):
        return "oauth google refresh"
    if re.search(r"(?i)\b(revoke|logout|sign[\s-]?out|disconnect)\b", lower):
        if re.search(r"(?i)\ball\b", lower):
            return "oauth google revoke --all"
        return "oauth google revoke"
    if re.search(r"(?i)\b(status|connected|signed\s+in)\b", lower):
        return "oauth google status"
    return "oauth google login"


def _print_setup(payload: dict[str, Any]) -> None:
    print("Google OAuth setup for Arka\n" + "=" * 32)
    for idx, step in enumerate(payload.get("steps") or [], 1):
        print(f"{idx}. {step}")
    print(f"\nRedirect URI: {payload.get('redirect_uri')}")
    print(f"Env file: {payload.get('env_file')}")
    if payload.get("next"):
        print(f"\nNext: {payload['next']}")


def _cmd_setup(args: argparse.Namespace) -> int:
    payload = setup_payload(
        dry_run=bool(getattr(args, "dry_run", False)),
        open_console=not bool(getattr(args, "no_browser", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0
    _print_setup(payload)
    return 0 if payload.get("configured") else 1


def _cmd_status(args: argparse.Namespace) -> int:
    payload = status_payload(account=str(getattr(args, "account", None) or "").strip() or None)
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        if not payload.get("configured"):
            return 1
        return 0 if payload.get("signed_in") else 1
    if not payload.get("configured"):
        print("Google OAuth client not configured in .env.")
        print(f"Run: arka oauth google setup\nEnv: {payload['env_file']}")
        return 1
    if not payload.get("signed_in"):
        print("OAuth client configured; not signed in.")
        print(f"Run: arka oauth google login\nRedirect URI: {payload['redirect_uri']}")
        return 1
    print(f"Google OAuth OK — {len(payload.get('linked_accounts') or [])} linked account(s)")
    for row in payload.get("linked_accounts") or []:
        email = row.get("email") or "unknown"
        alias = str(row.get("alias") or "").strip()
        suffix = f" [{alias}]" if alias else ""
        print(f"  • {email}{suffix}")
    print(f"Token storage: {payload['storage']['cache_dir']}")
    return 0


def _cmd_login(args: argparse.Namespace) -> int:
    if not oauth.credentials_configured():
        _cmd_setup(args)
        return 1
    try:
        payload = login_payload(
            open_browser=not bool(getattr(args, "no_browser", False)),
            headless=bool(getattr(args, "headless", False)),
            timeout=int(getattr(args, "timeout", 180) or 180),
            account=str(getattr(args, "account", None) or "").strip() or None,
            add_account=bool(getattr(args, "add", False)),
        )
    except RuntimeError as exc:
        print(f"Sign-in failed: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0
    email = payload.get("email") or "your Google account"
    print(f"✓ Signed in as {email} ({payload.get('mode')})")
    return 0


def _cmd_scopes(args: argparse.Namespace) -> int:
    service = str(getattr(args, "service", None) or "").strip() or None
    payload = scopes_payload(service=service)
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0
    print("Google OAuth scopes\n" + "-" * 20)
    for key, meta in payload["services"].items():
        print(f"\n{meta['label']} ({key})")
        print("  Recommended:")
        for scope in meta.get("recommended") or []:
            mark = "✓" if scope in payload["granted_scopes"] else " "
            print(f"    [{mark}] {scope}")
        for scope in meta.get("optional") or []:
            mark = "✓" if scope in payload["granted_scopes"] else " "
            print(f"    [{mark}] {scope} (optional)")
    return 0


def _cmd_refresh(args: argparse.Namespace) -> int:
    account = str(getattr(args, "account", None) or "").strip() or None
    try:
        payload = refresh_payload(account=account)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0
    print(f"✓ Refreshed token for {payload.get('email') or account or 'primary account'}")
    return 0


def _cmd_revoke(args: argparse.Namespace) -> int:
    account = str(getattr(args, "account", None) or "").strip() or None
    try:
        payload = revoke_payload(
            account=account,
            all_accounts=bool(getattr(args, "all", False)),
            remote=not bool(getattr(args, "local_only", False)),
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0
    print(f"✓ Revoked {len(payload.get('revoked') or [])} local Google token file(s)")
    return 0


def _add_google_subcommands(gsub: argparse._SubParsersAction) -> None:
    p_setup = gsub.add_parser("setup", help="Show Google Cloud OAuth setup steps")
    p_setup.add_argument("--dry-run", action="store_true", help="Instructions only")
    p_setup.add_argument("--no-browser", action="store_true", help="Do not open Cloud Console")
    p_setup.set_defaults(func=_cmd_setup)

    p_status = gsub.add_parser("status", help="Check OAuth client and sign-in status")
    p_status.add_argument("--account", help="Optional linked account key")
    p_status.set_defaults(func=_cmd_status)

    p_login = gsub.add_parser("login", aliases=["signin", "sign-in"], help="Sign in with Google")
    p_login.add_argument("--no-browser", action="store_true", help="Skip opening browser")
    p_login.add_argument("--headless", action="store_true", help="Use device-code flow when possible")
    p_login.add_argument("--timeout", type=int, default=180)
    p_login.add_argument("--add", action="store_true", help="Link another Google account")
    p_login.add_argument("--account", help="Account alias when using --add")
    p_login.set_defaults(func=_cmd_login)

    p_scopes = gsub.add_parser("scopes", help="List recommended OAuth scopes")
    p_scopes.add_argument("--service", choices=sorted(SERVICE_SCOPES))
    p_scopes.set_defaults(func=_cmd_scopes)

    p_refresh = gsub.add_parser("refresh", help="Refresh an expired access token")
    p_refresh.add_argument("--account")
    p_refresh.set_defaults(func=_cmd_refresh)

    p_revoke = gsub.add_parser("revoke", aliases=["logout"], help="Remove stored Google tokens")
    p_revoke.add_argument("--account")
    p_revoke.add_argument("--all", action="store_true")
    p_revoke.add_argument("--local-only", action="store_true", help="Skip Google revoke API")
    p_revoke.set_defaults(func=_cmd_revoke)


def main(argv: list[str] | None = None) -> int:
    raw = list(argv or [])
    json_mode = False
    if "--json" in raw:
        json_mode = True
        raw = [part for part in raw if part != "--json"]
    if raw and raw[0] not in ("google", "-h", "--help") and raw[0] in {
        "setup",
        "status",
        "login",
        "signin",
        "sign-in",
        "scopes",
        "refresh",
        "revoke",
        "logout",
    }:
        raw = ["google", *raw]

    parser = argparse.ArgumentParser(
        description="Google OAuth setup for Gmail, Calendar, and related Google APIs",
        prog="arka oauth",
    )
    sub = parser.add_subparsers(dest="provider")

    google = sub.add_parser("google", help="Google OAuth (Gmail, Calendar, …)")
    google.add_argument("--json", action="store_true", help="Emit JSON instead of human text")
    gsub = google.add_subparsers(dest="cmd")
    _add_google_subcommands(gsub)

    args = parser.parse_args(raw)
    if json_mode:
        args.json = True
    if getattr(args, "provider", None) != "google" or not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
