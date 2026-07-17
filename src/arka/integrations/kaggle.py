#!/usr/bin/env python3
"""Download and search Kaggle datasets via the Kaggle CLI or Python API."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import webbrowser
import zipfile
from pathlib import Path
from typing import Any

try:
    from arka.paths import downloads_dir, load_env_file

    load_env_file()
except ImportError:

    def downloads_dir() -> Path:
        return Path.home() / "Downloads"

    def load_env_file() -> None:
        pass


_DATASET_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*/[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_SEARCH_QUERY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\s._'-]{0,120}$")
_DATASET_URL_PREFIX = "https://www.kaggle.com/datasets/"
_KNOWN_CMDS = frozenset({"download", "search", "status", "parse", "open"})

_COMPETITIONS_RE = re.compile(r"(?i)\bcompetitions?\b")


def _is_competitions_request(text: str) -> bool:
    return bool(_COMPETITIONS_RE.search(text or ""))

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"kaggle(?:\s+dataset|\s+datasets|\s+download|\s+search|\s+status|\s+open)?|"
    r"open\s+kaggle\s+dataset|"
    r"download\s+(?:a\s+)?kaggle\s+dataset|"
    r"get\s+kaggle\s+dataset|"
    r"fetch\s+kaggle\s+dataset"
    r")\b"
)


def sanitize_dataset_slug(slug: str) -> str:
    raw = (slug or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        m = re.search(r"kaggle\.com/datasets/([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)", raw, re.I)
        if m:
            raw = m.group(1)
    raw = raw.strip("/")
    if not raw or not _DATASET_SLUG_RE.fullmatch(raw):
        raise ValueError(f"Invalid Kaggle dataset slug (expected owner/name): {slug!r}")
    return raw


def build_dataset_url(slug_or_url: str) -> str:
    return f"{_DATASET_URL_PREFIX}{sanitize_dataset_slug(slug_or_url)}"


def _open_url(url: str) -> None:
    if platform.system() == "Darwin":
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    webbrowser.open(url)


def open_dataset(slug_or_url: str) -> str:
    url = build_dataset_url(slug_or_url)
    _open_url(url)
    return f"Opened {url}"


def _no_credentials_message(slug: str | None = None) -> str:
    lines = [
        "Kaggle credentials not configured.",
        "Set KAGGLE_USERNAME/KAGGLE_KEY or ~/.kaggle/kaggle.json — run: kaggle status",
    ]
    if slug:
        lines.extend(
            [
                "",
                "Without API keys, open the dataset page in your browser:",
                f"  kaggle open {slug}",
                f"  kaggle download {slug} --open",
            ]
        )
    return "\n".join(lines)


def _search_no_credentials_message() -> str:
    return (
        "Kaggle credentials not configured. "
        "Set KAGGLE_USERNAME/KAGGLE_KEY or ~/.kaggle/kaggle.json — run: kaggle status\n\n"
        "Without API keys, browse datasets at https://www.kaggle.com/datasets\n"
        "or open a known dataset: kaggle open owner/dataset"
    )


def sanitize_search_query(query: str) -> str:
    raw = re.sub(r"\s+", " ", (query or "").strip())
    if not raw or not _SEARCH_QUERY_RE.fullmatch(raw):
        raise ValueError(f"Invalid search query: {query!r}")
    return raw


def credential_status() -> dict[str, Any]:
    username = (os.environ.get("KAGGLE_USERNAME") or "").strip()
    key = (os.environ.get("KAGGLE_KEY") or "").strip()
    if username and key:
        return {
            "configured": True,
            "username": username,
            "source": "environment",
            "detail": "KAGGLE_USERNAME + KAGGLE_KEY",
        }

    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if kaggle_json.is_file():
        try:
            data = json.loads(kaggle_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                file_user = str(data.get("username") or "").strip()
                file_key = str(data.get("key") or "").strip()
                if file_user and file_key:
                    return {
                        "configured": True,
                        "username": file_user,
                        "source": "kaggle.json",
                        "detail": str(kaggle_json),
                    }
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    return {
        "configured": False,
        "username": "",
        "source": "",
        "detail": "",
    }


def format_status() -> str:
    cred = credential_status()
    cli = find_kaggle_cli()
    py = _python_api_available()
    lines = [
        "━━━ Kaggle credentials ━━━",
        "",
    ]
    if cred["configured"]:
        lines.append(f"  Configured: yes ({cred['source']})")
        lines.append(f"  Username:   {cred['username']}")
        lines.append(f"  Source:     {cred['detail']}")
    else:
        lines.extend(
            [
                "  Configured: no",
                "",
                "  Set KAGGLE_USERNAME and KAGGLE_KEY in ~/.config/arka/.env",
                "  or place credentials in ~/.kaggle/kaggle.json",
                "  (create API token at https://www.kaggle.com/settings)",
            ]
        )
    lines.append("")
    lines.append(f"  kaggle CLI:  {'found at ' + cli if cli else 'not found'}")
    lines.append(f"  kaggle pkg:  {'available' if py else 'not installed'}")
    if not cli and not py:
        lines.append("")
        lines.append("  Install one of:")
        lines.append("    pip install kaggle")
        lines.append("    or download the kaggle CLI binary")
    return "\n".join(lines)


def find_kaggle_cli() -> str | None:
    return shutil.which("kaggle")


def _python_api_available() -> bool:
    try:
        import kaggle  # noqa: F401

        return True
    except (ImportError, SystemExit, OSError):
        return False


def _ensure_output_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _unzip_archives(directory: Path) -> list[str]:
    extracted: list[str] = []
    for archive in sorted(directory.glob("*.zip")):
        try:
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(directory)
            extracted.append(archive.name)
        except (OSError, zipfile.BadZipFile):
            continue
    return extracted


def _download_via_cli(slug: str, *, output_dir: Path, unzip: bool) -> str:
    cli = find_kaggle_cli()
    if not cli:
        raise RuntimeError("kaggle CLI not found on PATH")
    cmd = [cli, "datasets", "download", "-d", slug, "-p", str(output_dir)]
    if unzip:
        cmd.append("--unzip")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "download failed").strip()
        raise RuntimeError(err[:500])
    return (proc.stdout or proc.stderr or "Download complete.").strip()


def _download_via_python(slug: str, *, output_dir: Path, unzip: bool) -> str:
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as exc:
        raise RuntimeError(
            "Neither kaggle CLI nor Python kaggle package is available. "
            "Install with: pip install kaggle"
        ) from exc

    api = KaggleApi()
    api.authenticate()
    api.dataset_download_files(slug, path=str(output_dir), unzip=unzip, quiet=False)
    return f"Downloaded {slug} to {output_dir}"


def download_dataset(
    slug: str,
    *,
    output_dir: Path | None = None,
    unzip: bool = False,
    open_browser: bool = False,
) -> str:
    safe = sanitize_dataset_slug(slug)
    cred = credential_status()
    if not cred["configured"]:
        if open_browser:
            return open_dataset(safe)
        raise RuntimeError(_no_credentials_message(safe))
    out = _ensure_output_dir(output_dir or downloads_dir())

    if find_kaggle_cli():
        message = _download_via_cli(safe, output_dir=out, unzip=unzip)
    elif _python_api_available():
        message = _download_via_python(safe, output_dir=out, unzip=unzip)
        if unzip:
            _unzip_archives(out)
    else:
        raise RuntimeError(
            "Neither kaggle CLI nor Python kaggle package is available. "
            "Install with: pip install kaggle"
        )

    if unzip and find_kaggle_cli():
        extracted = _unzip_archives(out)
        if extracted:
            message = f"{message}\nUnzipped: {', '.join(extracted)}"

    return f"{message}\nSaved to: {out}"


def _search_via_cli(query: str, *, limit: int) -> list[dict[str, str]]:
    cli = find_kaggle_cli()
    if not cli:
        raise RuntimeError("kaggle CLI not found on PATH")
    proc = subprocess.run(
        [cli, "datasets", "list", "-s", query, "--max-size", str(max(1, min(limit, 50)))],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "search failed").strip()
        raise RuntimeError(err[:500])
    return _parse_cli_dataset_table(proc.stdout or "")


def _search_via_python(query: str, *, limit: int) -> list[dict[str, str]]:
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as exc:
        raise RuntimeError(
            "Neither kaggle CLI nor Python kaggle package is available. "
            "Install with: pip install kaggle"
        ) from exc

    api = KaggleApi()
    api.authenticate()
    rows = api.dataset_list(search=query, max_size=max(1, min(limit, 50)))
    hits: list[dict[str, str]] = []
    for row in rows:
        ref = str(getattr(row, "ref", "") or "").strip()
        title = str(getattr(row, "title", "") or ref).strip()
        size = str(getattr(row, "totalBytes", "") or getattr(row, "size", "") or "").strip()
        downloads = str(getattr(row, "downloadCount", "") or "").strip()
        hits.append(
            {
                "ref": ref,
                "title": title,
                "size": size,
                "downloads": downloads,
            }
        )
    return hits


def _parse_cli_dataset_table(text: str) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("ref"):
            continue
        parts = re.split(r"\s{2,}", line)
        if len(parts) < 2:
            continue
        ref = parts[0].strip()
        if "/" not in ref:
            continue
        hits.append(
            {
                "ref": ref,
                "title": parts[1].strip() if len(parts) > 1 else ref,
                "size": parts[-2].strip() if len(parts) > 3 else "",
                "downloads": parts[-1].strip() if len(parts) > 2 else "",
            }
        )
    return hits


def search_datasets(query: str, *, limit: int = 10) -> list[dict[str, str]]:
    cred = credential_status()
    if not cred["configured"]:
        raise RuntimeError(_search_no_credentials_message())

    safe = sanitize_search_query(query)
    if find_kaggle_cli():
        return _search_via_cli(safe, limit=limit)
    if _python_api_available():
        return _search_via_python(safe, limit=limit)
    raise RuntimeError(
        "Neither kaggle CLI nor Python kaggle package is available. "
        "Install with: pip install kaggle"
    )


def format_search_results(query: str, hits: list[dict[str, str]]) -> str:
    if not hits:
        return f"━━━ Kaggle search: {query} ━━━\n\n  No datasets matched."
    lines = [f"━━━ Kaggle search: {query} ━━━", ""]
    for hit in hits:
        ref = hit.get("ref") or "?"
        title = hit.get("title") or ref
        size = hit.get("size") or "—"
        downloads = hit.get("downloads") or "—"
        lines.append(f"  {ref}")
        lines.append(f"    {title[:100]}")
        lines.append(f"    size {size}  downloads {downloads}")
        lines.append("")
    lines.append("Download: kaggle download <owner/dataset>")
    return "\n".join(lines).rstrip()


def _extract_slug(text: str) -> str | None:
    m = re.search(r"kaggle\.com/datasets/([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\b([a-zA-Z0-9][a-zA-Z0-9_-]*/[a-zA-Z0-9][a-zA-Z0-9_-]*)\b", text)
    if m:
        try:
            return sanitize_dataset_slug(m.group(1))
        except ValueError:
            return None
    return None


def _strip_nl_prefix(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:arka\s+)?(?:download|get|fetch)\s+(?:a\s+)?kaggle\s+dataset\s+",
        "",
        t,
    )
    t = re.sub(r"(?i)^(?:please\s+)?(?:arka\s+)?kaggle\s+(?:download|dataset|datasets)\s+", "", t)
    t = re.sub(r"(?i)^kaggle\s+", "", t)
    return t.strip()


def nl_to_argv(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    if _is_competitions_request(raw):
        return []
    lower = raw.lower()
    if not _TRIGGER_RE.search(raw) and "kaggle" not in lower:
        return []

    if re.search(r"(?i)\b(?:status|credentials?|configured|setup|auth)\b", raw):
        return ["status"]

    if re.search(r"(?i)\bopen\b", raw):
        slug = _extract_slug(raw)
        if slug:
            return ["open", slug]
        rest = _strip_nl_prefix(raw)
        rest = re.sub(r"(?i)^open\s+", "", rest).strip()
        if rest and _DATASET_SLUG_RE.fullmatch(rest):
            return ["open", rest]
        rest = re.sub(
            r"(?i)^(?:please\s+)?(?:arka\s+)?(?:open\s+)?(?:kaggle\s+)?(?:dataset|datasets)\s+",
            "",
            raw,
        ).strip()
        if rest and _DATASET_SLUG_RE.fullmatch(rest):
            return ["open", rest]
        return []

    if re.search(r"(?i)\bsearch\b", raw):
        rest = _strip_nl_prefix(raw)
        rest = re.sub(r"(?i)^search\s+", "", rest).strip()
        if rest:
            return ["search", rest]
        return []

    slug = _extract_slug(raw)
    if slug:
        argv = ["download", slug]
        if re.search(r"(?i)\bunzip\b", raw):
            argv.append("--unzip")
        return argv

    rest = _strip_nl_prefix(raw)
    if rest and _DATASET_SLUG_RE.fullmatch(rest):
        return ["download", rest]

    if rest and not re.search(r"(?i)\b(?:download|dataset|datasets)\b", rest):
        return ["search", rest]

    return []


def wants_kaggle(text: str) -> bool:
    raw = text or ""
    if _is_competitions_request(raw):
        return False
    return bool(_TRIGGER_RE.search(raw))


def route_command(text: str) -> str:
    argv = nl_to_argv(text)
    if not argv:
        return ""
    return "kaggle " + " ".join(shlex.quote(a) for a in argv)


def cmd_download(args: argparse.Namespace) -> int:
    slug = (args.dataset or "").strip()
    if not slug:
        print(
            "Usage: kaggle download <owner/dataset> [-o DIR] [--unzip] [--open]",
            file=sys.stderr,
        )
        return 1
    try:
        out = download_dataset(
            slug,
            output_dir=args.output,
            unzip=args.unzip,
            open_browser=args.open_browser,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    slug = (args.dataset or "").strip()
    if not slug:
        print("Usage: kaggle open <owner/dataset>", file=sys.stderr)
        return 1
    try:
        out = open_dataset(slug)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    if not query:
        print("Usage: kaggle search <keywords>", file=sys.stderr)
        return 1
    try:
        hits = search_datasets(query, limit=args.limit)
    except (ValueError, RuntimeError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(format_search_results(query, hits))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    print(format_status())
    return 0 if credential_status()["configured"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download and search Kaggle datasets")
    sub = parser.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="Parse natural language → argv (internal)")
    p_parse.add_argument("text", nargs="+")

    p_download = sub.add_parser("download", help="Download a dataset by owner/slug")
    p_download.add_argument("dataset")
    p_download.add_argument("-o", "--output", type=Path, default=None)
    p_download.add_argument("--unzip", action="store_true")
    p_download.add_argument(
        "--open",
        "--browser",
        dest="open_browser",
        action="store_true",
        help="Open dataset page in browser (no API key required)",
    )
    p_download.set_defaults(func=cmd_download)

    p_open = sub.add_parser("open", help="Open dataset page in browser (no API key)")
    p_open.add_argument("dataset")
    p_open.set_defaults(func=cmd_open)

    p_search = sub.add_parser("search", help="Search datasets by keyword")
    p_search.add_argument("query", nargs="+")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    sub.add_parser("status", help="Check Kaggle credential configuration").set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    if args.cmd == "parse":
        out = nl_to_argv(" ".join(args.text))
        if not out:
            return 1
        print(" ".join(shlex.quote(a) for a in out))
        return 0

    if hasattr(args, "func"):
        return int(args.func(args))

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
