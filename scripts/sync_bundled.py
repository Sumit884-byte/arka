#!/usr/bin/env python3
"""Assemble pip wheel runtime bundle from src/arka/ tree."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "arka"
BUNDLED = SRC / "bundled"
BIN = ROOT / "bin"


def copy_file(src: Path, dest: Path) -> bool:
    if not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def copy_tree(src: Path, dest: Path) -> int:
    if not src.is_dir():
        return 0
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return sum(1 for _ in dest.rglob("*"))


def main() -> int:
    if BUNDLED.exists():
        shutil.rmtree(BUNDLED)
    BUNDLED.mkdir(parents=True)

    n = 0
    # Fish router + shell helpers (flat names for pip install ARKA_HOME)
    for name in ("config.fish",):
        if copy_file(SRC / "fish" / name, BUNDLED / name):
            n += 1
    for sh in ("arka_boot.sh", "arka_voice_hf.sh", "termux-boot-arka.sh"):
        if copy_file(SRC / "fish" / "scripts" / sh, BUNDLED / sh):
            n += 1

    # Python entry shims
    for shim in BIN.glob("*.py"):
        if copy_file(shim, BUNDLED / shim.name):
            n += 1

    # Legacy flat names still referenced in docs
    chat_req = SRC / "requirements" / "chat.txt"
    if copy_file(chat_req, BUNDLED / "arka_chat_requirements.txt"):
        n += 1
    tq_req = SRC / "requirements" / "turboquant.txt"
    if copy_file(tq_req, BUNDLED / "arka_turboquant_requirements.txt"):
        n += 1

    for src, dest in (
        (SRC / "env.example", BUNDLED / ".env.example"),
        (ROOT / ".env.example", BUNDLED / ".env.example"),
    ):
        if copy_file(src, dest):
            n += 1
            break

    for name in ("edge_speak.py", "indic_tts.py", "sarvam_speak.py", "sarvam_stt.py", "web_answer.py", "spotify_dom.py"):
        if copy_file(BIN / name, BUNDLED / name):
            n += 1

    n += copy_tree(SRC / "aie", BUNDLED / "aie")
    n += copy_tree(SRC / "pdf" / "privategpt", BUNDLED / "privategpt")

    wa = ROOT / "whatsapp"
    if wa.is_dir():
        n += copy_tree(wa, BUNDLED / "whatsapp")

    print(f"Synced {n} assets → {BUNDLED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
