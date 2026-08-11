"""File watcher that debounces `dev test --changed` runs."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _snapshot(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if proc.returncode == 0:
            return hashlib.sha256((proc.stdout or "").encode()).hexdigest()
    except OSError:
        pass
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in {".git", "node_modules", ".venv", "venv"} for part in path.parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(f"{path.relative_to(root)}:{stat.st_mtime_ns}:{stat.st_size}".encode())
    return digest.hexdigest()


def _run_changed_tests(root: Path) -> int:
    from arka.agent.dev_tools import ci_text, run_ci

    payload = run_ci(root, changed_only=True)
    print(ci_text(root, changed_only=True))
    return 0 if payload["ok"] else 1


def watch_and_test(root: Path, *, debounce_sec: float = 2.0) -> int:
    root = root.expanduser().resolve()
    print(f"Watching {root} — debounce {debounce_sec}s (Ctrl+C to stop)", file=sys.stderr)
    last_sig = _snapshot(root)
    last_run = 0.0
    fswatch = shutil.which("fswatch")

    if fswatch:
        proc = subprocess.Popen([fswatch, "-1", "-r", str(root)], stdout=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        try:
            while True:
                proc.stdout.readline()
                now = time.time()
                sig = _snapshot(root)
                if sig != last_sig and now - last_run >= debounce_sec:
                    last_sig = sig
                    last_run = now
                    print("\n→ changes detected — running changed CI", file=sys.stderr)
                    _run_changed_tests(root)
        except KeyboardInterrupt:
            proc.terminate()
            return 0

    try:
        while True:
            time.sleep(max(0.5, debounce_sec / 2))
            sig = _snapshot(root)
            now = time.time()
            if sig != last_sig and now - last_run >= debounce_sec:
                last_sig = sig
                last_run = now
                print("\n→ changes detected — running changed CI", file=sys.stderr)
                _run_changed_tests(root)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="arka dev watch")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--debounce", type=float, default=2.0)
    args = parser.parse_args(argv)
    return watch_and_test(Path(args.path), debounce_sec=max(0.5, args.debounce))


if __name__ == "__main__":
    raise SystemExit(main())
