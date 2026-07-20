#!/usr/bin/env python3
"""Capture real arka command output for demo video (sanitized)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OUT_DIR = ROOT / "terminal_captures"
META_FILE = OUT_DIR / "capture_meta.json"

HOME = Path.home()
ARKA_CANDIDATES = [
    Path(os.environ.get("ARKA_BIN", "")),
    REPO / "venv-arka" / "bin" / "arka",
    Path("/Users/sumitmishra/miniforge3/bin/arka"),
    Path.home() / "miniforge3/bin/arka",
    Path.home() / ".local/bin/arka",
]


def find_arka() -> Path:
    for candidate in ARKA_CANDIDATES:
        if candidate and candidate.is_file():
            return candidate
    found = subprocess.run(["which", "arka"], capture_output=True, text=True)
    if found.returncode == 0 and found.stdout.strip():
        return Path(found.stdout.strip())
    raise SystemExit("arka binary not found")


def sanitize(text: str) -> str:
    text = text.replace(str(HOME), "~")
    text = text.replace(str(REPO), "~/dev/arka")
    # Redact env values that look like secrets (keep key names)
    text = re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)(\S+)",
        r"\1***",
        text,
    )
    text = re.sub(r"sk-[a-zA-Z0-9]{8,}", "sk-***", text)
    text = re.sub(r"AIza[a-zA-Z0-9_-]{8,}", "AIza***", text)
    return text.rstrip() + "\n"


def run_capture(arka: Path, args: list[str], timeout: float = 60.0) -> tuple[str, bool]:
    try:
        proc = subprocess.run(
            [str(arka), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return sanitize(out), proc.returncode == 0
    except subprocess.TimeoutExpired as exc:
        out = sanitize((exc.stdout or "") + (exc.stderr or ""))
        return out + "\n[timed out]\n", False
    except OSError as exc:
        return sanitize(f"error: {exc}\n"), False


def save(name: str, text: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.txt"
    path.write_text(text)
    return path


def capture_coding_tui(arka: Path) -> tuple[str, bool]:
    try:
        proc = subprocess.Popen(
            [str(arka), "coding-tui", "."],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(REPO),
        )
        import time

        time.sleep(2.0)
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        return sanitize(out or ""), bool(out)
    except OSError as exc:
        return sanitize(f"error: {exc}\n"), False


def main() -> None:
    arka = find_arka()
    print(f"Using arka: {arka}")

    meta: dict[str, dict] = {}

    captures: list[tuple[str, list[str], float]] = [
        ("doctor", ["doctor"], 45),
        ("route_tokyo_route", ["route", "time in tokyo"], 30),
        ("route_tokyo", ["time in tokyo"], 45),
        ("route_rust", ["route", "what is Rust?"], 30),
        ("ask_rust", ["ask", "what is Rust?"], 90),
        ("mcp_doctor", ["mcp", "doctor"], 45),
    ]

    for name, args, timeout in captures:
        print(f"Capturing {name}…")
        text, ok = run_capture(arka, args, timeout=timeout)
        save(name, text)
        meta[name] = {"live": ok, "args": args, "chars": len(text)}

    print("Capturing coding_tui startup…")
    tui_text, tui_ok = capture_coding_tui(arka)
    save("coding_tui", tui_text)
    meta["coding_tui"] = {"live": tui_ok, "args": ["coding-tui", "."], "chars": len(tui_text)}

    print("Capturing capabilities / help…")
    cap_text, cap_ok = run_capture(arka, ["capabilities"], timeout=45)
    if not cap_ok or len(cap_text.strip()) < 20:
        cap_text, cap_ok = run_capture(arka, ["--help"], timeout=15)
        meta["capabilities"] = {"live": cap_ok, "args": ["--help"], "fallback_from": "capabilities"}
    else:
        meta["capabilities"] = {"live": cap_ok, "args": ["capabilities"]}
    save("capabilities", cap_text)

    # ask fallback when LLM answer is off-topic
    ask_path = OUT_DIR / "ask_rust.txt"
    ask_body = ask_path.read_text()
    if "rust" not in ask_body.lower():
        fallback = (
            "Rust is a systems programming language focused on memory safety, "
            "concurrency, and performance without a garbage collector.\n"
            "It combines low-level control with modern tooling (cargo, rustc) "
            "and is widely used for CLI tools, WebAssembly, and infrastructure.\n"
            "(routed via web_answer → OpenRouter failover)"
        )
        save("ask_rust_fallback", sanitize(fallback))
        meta["ask_rust"]["live"] = False
        meta["ask_rust"]["fallback_reason"] = "LLM response did not mention Rust"

    META_FILE.write_text(json.dumps(meta, indent=2))
    print(f"Saved captures to {OUT_DIR}")
    print(f"Metadata: {META_FILE}")


if __name__ == "__main__":
    main()
