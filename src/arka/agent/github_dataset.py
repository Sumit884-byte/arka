"""Import common data files from public GitHub dataset repositories."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import signal
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arka.paths import cache_dir


DATA_EXTENSIONS = {".csv", ".json", ".jsonl", ".ndjson", ".tsv", ".yaml", ".yml", ".xml", ".parquet"}
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_DATA_FILE_BYTES = 64 * 1024 * 1024
MAX_DISCOVERED_FILES = 200
DEFAULT_BRANCHES = ("main", "master")
CONFIG_JSON_NAMES = {
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "jsconfig.json",
    "composer.json",
    "manifest.json",
    "pnpm-lock.yaml",
}


class DatasetRepoError(RuntimeError):
    pass


class _DownloadDeadline(DatasetRepoError):
    pass


class _DiscoveredFilesDownloadError(DatasetRepoError):
    pass


class _deadline:
    def __init__(self, seconds: float) -> None:
        self.seconds = max(1.0, seconds)
        self.previous_handler: Any = None
        self.enabled = False

    def __enter__(self) -> None:
        if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
            return

        def _raise_timeout(signum: int, frame: Any) -> None:
            raise _DownloadDeadline(f"download timed out after {self.seconds:g}s")

        self.previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        self.enabled = True

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self.previous_handler)


@dataclass(frozen=True)
class GitHubRepo:
    owner: str
    name: str
    branch: str | None = None

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def cache_key(self) -> str:
        return f"{self.owner}__{self.name}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"


def parse_repo(value: str) -> GitHubRepo:
    raw = (value or "").strip()
    raw = raw.removesuffix(".git")
    match = re.search(
        r"(?:https?://github\.com/|git@github\.com:)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:/(?:tree|blob)/([^/#?\s]+))?",
        raw,
        re.I,
    )
    if not match:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?::([^/#?\s]+))?", raw)
    if not match:
        raise ValueError(f"expected a GitHub repo URL or owner/repo slug, got: {value!r}")
    owner, name, branch = match.groups()
    return GitHubRepo(owner=owner, name=name, branch=branch)


def dataset_dir(repo: GitHubRepo) -> Path:
    return cache_dir() / "datasets" / "github" / repo.cache_key


def manifest_path(repo: GitHubRepo) -> Path:
    return dataset_dir(repo) / "manifest.json"


def files_dir(repo: GitHubRepo) -> Path:
    return dataset_dir(repo) / "files"


def _download_bytes(url: str, *, timeout: float, max_bytes: int = MAX_ARCHIVE_BYTES) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ArkaGitHubDataset/1.0"})
    with _deadline(timeout):
        with urllib.request.urlopen(request, timeout=timeout) as response:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise DatasetRepoError(f"archive exceeded {max_bytes} bytes; use a smaller repo or explicit data file")
                chunks.append(chunk)
            return b"".join(chunks)


def _download_json(url: str, *, timeout: float) -> Any:
    data = _download_bytes(url, timeout=timeout, max_bytes=8 * 1024 * 1024)
    return json.loads(data.decode("utf-8"))


def _archive_urls(repo: GitHubRepo) -> list[tuple[str, str]]:
    branches = [repo.branch] if repo.branch else list(DEFAULT_BRANCHES)
    return [(branch, f"https://codeload.github.com/{repo.owner}/{repo.name}/zip/refs/heads/{branch}") for branch in branches if branch]


def _safe_member_path(member: str) -> Path | None:
    parts = Path(member).parts
    if len(parts) < 2:
        return None
    relative = Path(*parts[1:])
    if relative.is_absolute() or ".." in relative.parts:
        return None
    return relative


def _looks_like_data_file(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    if path.name.lower() in CONFIG_JSON_NAMES:
        return False
    if path.suffix.lower() not in DATA_EXTENSIONS:
        return False
    lowered = "/".join(part.lower() for part in path.parts)
    if any(part.lower() in {"node_modules", ".git", "venv", "dist", "build"} for part in path.parts):
        return False
    if any(skip in lowered for skip in ("/node_modules/", "/.git/", "/venv/", "/dist/", "/build/")):
        return False
    return True


def _api_contents_url(repo: GitHubRepo, branch: str, path: str = "") -> str:
    suffix = f"/{path}" if path else ""
    return f"https://api.github.com/repos/{repo.owner}/{repo.name}/contents{suffix}?ref={branch}"


def _discover_api_files(repo: GitHubRepo, *, branch: str, timeout: float) -> list[dict[str, Any]]:
    queue = [""]
    files: list[dict[str, Any]] = []
    while queue and len(files) < MAX_DISCOVERED_FILES:
        path = queue.pop(0)
        payload = _download_json(_api_contents_url(repo, branch, path), timeout=timeout)
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("type")
            entry_path = str(entry.get("path") or "")
            if not entry_path:
                continue
            relative = Path(entry_path)
            if entry_type == "dir":
                lowered = entry_path.lower()
                if any(part in {"node_modules", ".git", "venv", "dist", "build"} for part in relative.parts):
                    continue
                if lowered.count("/") <= 4:
                    queue.append(entry_path)
            elif entry_type == "file" and _looks_like_data_file(relative):
                download_url = str(entry.get("download_url") or "")
                if download_url:
                    files.append(
                        {
                            "path": entry_path,
                            "download_url": download_url,
                            "size": int(entry.get("size") or 0),
                        }
                    )
    return files


def _preview_file(path: Path) -> dict[str, Any]:
    kind = path.suffix.lower().lstrip(".")
    preview: dict[str, Any] = {"format": kind, "size_bytes": path.stat().st_size}
    try:
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8", errors="replace") as handle:
                reader = csv.reader(handle)
                header = next(reader, [])
                sample_rows = [row for _, row in zip(range(5), reader)]
            preview.update({"columns": header, "sample_rows": sample_rows})
        elif path.suffix.lower() == ".tsv":
            with path.open(newline="", encoding="utf-8", errors="replace") as handle:
                reader = csv.reader(handle, delimiter="\t")
                header = next(reader, [])
                sample_rows = [row for _, row in zip(range(5), reader)]
            preview.update({"columns": header, "sample_rows": sample_rows})
        elif path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, list):
                preview["records"] = len(data)
                preview["sample_rows"] = data[:5]
                if data and isinstance(data[0], dict):
                    preview["columns"] = list(data[0].keys())
            elif isinstance(data, dict):
                preview["keys"] = list(data.keys())[:50]
        elif path.suffix.lower() in {".jsonl", ".ndjson"}:
            rows = []
            with path.open(encoding="utf-8", errors="replace") as handle:
                for _, line in zip(range(5), handle):
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
            preview["sample_rows"] = rows
            if rows and isinstance(rows[0], dict):
                preview["columns"] = list(rows[0].keys())
    except Exception as exc:  # noqa: BLE001 - preview is best-effort, not validation.
        preview["preview_error"] = str(exc)
    return preview


def _write_discovered_files(repo: GitHubRepo, discovered: list[dict[str, Any]], *, timeout: float) -> list[dict[str, Any]]:
    out_dir = files_dir(repo)
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[dict[str, Any]] = []
    for item in discovered:
        relative = Path(str(item["path"]))
        target = out_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = _download_bytes(str(item["download_url"]), timeout=timeout, max_bytes=MAX_DATA_FILE_BYTES)
        target.write_bytes(content)
        preview = _preview_file(target)
        extracted.append({"path": str(relative), "cache_path": str(target), **preview})
    return extracted


def _extract_archive_files(repo: GitHubRepo, archive_bytes: bytes) -> list[dict[str, Any]]:
    out_dir = files_dir(repo)
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = _safe_member_path(info.filename)
            if relative is None or not _looks_like_data_file(relative):
                continue
            target = out_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            preview = _preview_file(target)
            extracted.append(
                {
                    "path": str(relative),
                    "cache_path": str(target),
                    **preview,
                }
            )
    return extracted


def import_repo(repo_value: str, *, force: bool = False, timeout: float = 120.0) -> dict[str, Any]:
    repo = parse_repo(repo_value)
    root = dataset_dir(repo)
    out_dir = files_dir(repo)
    manifest = manifest_path(repo)
    if manifest.exists() and not force:
        return json.loads(manifest.read_text(encoding="utf-8"))

    last_error: Exception | None = None
    extracted: list[dict[str, Any]] = []
    branch_used = repo.branch or DEFAULT_BRANCHES[0]
    import_method = "github_contents_api"

    for branch in ([repo.branch] if repo.branch else list(DEFAULT_BRANCHES)):
        if not branch:
            continue
        try:
            discovered = _discover_api_files(repo, branch=branch, timeout=timeout)
            if discovered:
                branch_used = branch
                try:
                    extracted = _write_discovered_files(repo, discovered, timeout=timeout)
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, DatasetRepoError) as exc:
                    raise _DiscoveredFilesDownloadError(
                        f"found {len(discovered)} data file(s) in {repo.slug} on {branch}, but download failed: {exc}"
                    ) from exc
                break
        except _DiscoveredFilesDownloadError:
            raise
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            DatasetRepoError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            last_error = exc

    if not extracted:
        import_method = "zip_archive"
        for branch, url in _archive_urls(repo):
            try:
                archive_bytes = _download_bytes(url, timeout=timeout)
                extracted = _extract_archive_files(repo, archive_bytes)
                branch_used = branch
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, DatasetRepoError, zipfile.BadZipFile) as exc:
                last_error = exc
    if not extracted:
        if last_error:
            raise DatasetRepoError(f"could not import data files from {repo.slug}: {last_error}")
        raise DatasetRepoError(f"no common data files found in {repo.slug}; supported: {', '.join(sorted(DATA_EXTENSIONS))}")

    meta = {
        "source": repo.url,
        "repo": repo.slug,
        "branch": branch_used,
        "import_method": import_method,
        "cache_dir": str(out_dir),
        "files": sorted(extracted, key=lambda item: item["path"]),
        "file_count": len(extracted),
        "note": "License is not inferred automatically; inspect the upstream repository before redistribution.",
    }
    root.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def load_manifest(repo_value: str) -> dict[str, Any]:
    repo = parse_repo(repo_value)
    target = manifest_path(repo)
    if not target.is_file():
        raise FileNotFoundError(f"dataset repo not imported; run: arka github-dataset import {repo.slug}")
    return json.loads(target.read_text(encoding="utf-8"))


def search_manifest(repo_value: str, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    manifest = load_manifest(repo_value)
    terms = [term.lower() for term in re.findall(r"[a-z0-9]+", query)]
    files = manifest.get("files", [])
    if not terms:
        return files[:limit]

    def score(item: dict[str, Any]) -> int:
        haystack = json.dumps(item, ensure_ascii=False).lower()
        return sum(1 for term in terms if term in haystack)

    ranked = sorted(((score(item), item) for item in files), key=lambda pair: (-pair[0], pair[1].get("path", "")))
    return [item for value, item in ranked if value > 0][:limit]


def route_command(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    try:
        repo = parse_repo(clean)
    except ValueError:
        return ""
    if not re.search(r"(?i)\b(?:data|dataset|datasets|csv|json|table|repo|repository)\b", clean):
        return ""
    if re.search(r"(?i)\b(?:search|find|show|list)\b", clean):
        query = re.sub(r"https?://github\.com/[^\s]+|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", " ", clean)
        query = re.sub(r"(?i)\b(?:search|find|show|list|github|data|dataset|datasets|files?|repo|repository|from|in|this|for)\b", " ", query)
        return f"github_dataset search {repo.slug} {' '.join(query.split())}".strip()
    if re.search(r"(?i)\b(?:add|import|load|download|cache|get|use)\b", clean):
        return f"github_dataset import {repo.slug}"
    return ""


def _print_summary(meta: dict[str, Any]) -> None:
    print(f"repo\t{meta['repo']}")
    print(f"branch\t{meta['branch']}")
    print(f"files\t{meta['file_count']}")
    print(f"cache\t{meta['cache_dir']}")
    for item in meta["files"][:12]:
        details = []
        if item.get("columns"):
            details.append(f"columns={len(item['columns'])}")
        if item.get("records") is not None:
            details.append(f"records={item['records']}")
        details.append(f"bytes={item.get('size_bytes', 0)}")
        print(f"- {item['path']} ({', '.join(details)})")
    if len(meta["files"]) > 12:
        print(f"... {len(meta['files']) - 12} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka github-dataset")
    sub = parser.add_subparsers(dest="cmd")
    p_import = sub.add_parser("import", help="Download and cache data files from a GitHub repo")
    p_import.add_argument("repo")
    p_import.add_argument("--force", action="store_true")
    p_import.add_argument("--timeout", type=float, default=120.0)
    p_import.add_argument("--json", action="store_true")
    p_status = sub.add_parser("status", help="Show imported dataset repo manifest")
    p_status.add_argument("repo")
    p_status.add_argument("--json", action="store_true")
    p_search = sub.add_parser("search", help="Search imported file manifests")
    p_search.add_argument("repo")
    p_search.add_argument("query", nargs="*")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--json", action="store_true")
    args = parser.parse_args(argv or ["--help"])
    try:
        if args.cmd == "import":
            meta = import_repo(args.repo, force=args.force, timeout=max(1.0, args.timeout))
            print(json.dumps(meta, indent=2) if args.json else "Imported GitHub dataset repo")
            if not args.json:
                _print_summary(meta)
            return 0
        if args.cmd == "search":
            rows = search_manifest(args.repo, " ".join(args.query), limit=max(1, min(args.limit, 100)))
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                for row in rows:
                    print(f"{row['path']}\t{row.get('format', '')}\t{row.get('size_bytes', 0)} bytes")
            return 0
        if args.cmd == "status":
            meta = load_manifest(args.repo)
            print(json.dumps(meta, indent=2) if args.json else "GitHub dataset repo cached")
            if not args.json:
                _print_summary(meta)
            return 0
        parser.print_help()
        return 1
    except (ValueError, DatasetRepoError, FileNotFoundError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"github dataset error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
