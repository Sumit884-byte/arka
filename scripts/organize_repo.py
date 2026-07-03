#!/usr/bin/env python3
"""Move runtime assets under src/arka/ and entry shims into bin/."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "arka"
BIN = ROOT / "bin"
FISH = SRC / "fish"


def merge_dir(src: Path, dest: Path) -> None:
    if not src.is_dir():
        return
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            merge_dir(item, target)
        elif not target.exists():
            shutil.copy2(item, target)


def relocate() -> None:
    BIN.mkdir(exist_ok=True)
    (FISH / "scripts").mkdir(parents=True, exist_ok=True)
    (SRC / "requirements").mkdir(parents=True, exist_ok=True)
    (SRC / "skills" / "examples").mkdir(parents=True, exist_ok=True)
    (SRC / "pdf" / "privategpt").mkdir(parents=True, exist_ok=True)

    cfg = ROOT / "config.fish"
    fish_cfg = FISH / "config.fish"
    if fish_cfg.is_file():
        pass
    elif cfg.is_file() and len(cfg.read_text(encoding="utf-8")) > 500:
        shutil.move(str(cfg), str(fish_cfg))

    stub = (
        "# Arka Fish — sources canonical config from the package tree\n"
        "set -l _arka_cfg (path dirname (status filename))/src/arka/fish/config.fish\n"
        "if not test -f \"$_arka_cfg\"\n"
        "    set _arka_cfg (path dirname (status filename))/src/arka/bundled/config.fish\n"
        "end\n"
        "if test -f \"$_arka_cfg\"\n"
        "    source \"$_arka_cfg\"\n"
        "else\n"
        "    echo \"Arka config missing — run: python scripts/sync_bundled.py\" >&2\n"
        "end\n"
    )
    (ROOT / "config.fish").write_text(stub, encoding="utf-8")

    for name in ("completions", "conf.d", "functions"):
        src = ROOT / name
        if src.is_dir():
            merge_dir(src, FISH / name)
            shutil.rmtree(src)

    for sh in ("arka_boot.sh", "arka_voice_hf.sh", "termux-boot-arka.sh"):
        src = ROOT / sh
        if src.is_file():
            shutil.move(str(src), str(FISH / "scripts" / sh))

    for req, dest_name in (
        ("arka_chat_requirements.txt", "chat.txt"),
        ("arka_turboquant_requirements.txt", "turboquant.txt"),
    ):
        src = ROOT / req
        if src.is_file():
            shutil.move(str(src), str(SRC / "requirements" / dest_name))

    env_ex = ROOT / ".env.example"
    if env_ex.is_file():
        shutil.copy2(env_ex, SRC / "env.example")

    merge_dir(ROOT / "aie", SRC / "aie")
    if (ROOT / "aie").is_dir():
        shutil.rmtree(ROOT / "aie")

    pg = ROOT / "privategpt" / "settings.override.yaml"
    if pg.is_file():
        shutil.copy2(pg, SRC / "pdf" / "privategpt" / "settings.override.yaml")
    if (ROOT / "privategpt").is_dir():
        shutil.rmtree(ROOT / "privategpt")

    merge_dir(ROOT / "skills", SRC / "skills" / "examples")
    if (ROOT / "skills").is_dir():
        shutil.rmtree(ROOT / "skills")

    html = ROOT / "spotify-dom.html"
    if html.is_file():
        shutil.move(str(html), str(SRC / "integrations" / "spotify-dom.html"))

    for py in list(ROOT.glob("arka_*.py")) + [
        ROOT / n
        for n in (
            "edge_speak.py",
            "indic_tts.py",
            "sarvam_speak.py",
            "sarvam_stt.py",
            "spotify_dom.py",
            "web_answer.py",
        )
    ]:
        if py.is_file() and py.stat().st_size < 512:
            dest = BIN / py.name
            if not dest.exists():
                shutil.move(str(py), str(dest))


FISH_HELPERS = '''
function _arka_bin --description "Python entry shims (internal)"
    if test -d "$_ARKA_ROOT/bin"
        echo "$_ARKA_ROOT/bin"
        return
    end
    echo "$_ARKA_ROOT"
end

function _arka_py_script --description "Resolve python entry script (internal)"
    set -l name $argv[1]
    set -l dir (_arka_bin)
    if test -f "$dir/$name"
        echo "$dir/$name"
        return
    end
    if test -f "$_ARKA_ROOT/$name"
        echo "$_ARKA_ROOT/$name"
    end
end

function _arka_shell_script --description "Resolve shell runtime script (internal)"
    set -l name $argv[1]
    for candidate in \\
            "$_ARKA_ROOT/src/arka/fish/scripts/$name" \\
            "$_ARKA_ROOT/fish/scripts/$name" \\
            "$_ARKA_ROOT/scripts/$name" \\
            "$_ARKA_ROOT/$name"
        if test -f "$candidate"
            echo "$candidate"
            return
        end
    end
end

function _arka_requirements --description "Chat requirements path (internal)"
    for candidate in \\
            "$_ARKA_ROOT/src/arka/requirements/chat.txt" \\
            "$_ARKA_ROOT/requirements/chat.txt" \\
            "$_ARKA_ROOT/arka_chat_requirements.txt"
        if test -f "$candidate"
            echo "$candidate"
            return
        end
    end
end

'''


def patch_config(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "_arka_py_script" not in text:
        text = text.replace("set -g _ARKA_ROOT (_arka_root)", FISH_HELPERS + "set -g _ARKA_ROOT (_arka_root)")

    text = text.replace(
        '    if test -f "$here/arka_chat.py"\n        echo $here\n        return\n    end',
        '    if test -f "$here/bin/arka_chat.py"\n        echo $here\n        return\n    end\n'
        '    if test -f "$here/arka_chat.py"\n        echo $here\n        return\n    end',
    )

    def py_script(match: re.Match[str]) -> str:
        name = match.group(1)
        return f"(_arka_py_script {name})"

    text = re.sub(r"\$_ARKA_ROOT/((?:arka_[a-z_]+|edge_speak|indic_tts|sarvam_[a-z]+|web_answer|spotify_dom)\.py)", py_script, text)
    text = text.replace("bash $_ARKA_ROOT/arka_boot.sh", "bash (_arka_shell_script arka_boot.sh)")
    text = text.replace("$_ARKA_ROOT/arka_boot.sh", "(_arka_shell_script arka_boot.sh)")
    text = text.replace("$_ARKA_ROOT/arka_chat_requirements.txt", "(_arka_requirements)")
    text = text.replace('if test -f "$_ARKA_ROOT/arka_platform.py"', 'if test -f (_arka_py_script arka_platform.py)')
    text = text.replace('if test -f "$_ARKA_ROOT/bin/arka_platform.py"', 'if test -f (_arka_py_script arka_platform.py)')

    while "(_arka_py_script (_arka_py_script" in text:
        text = text.replace("(_arka_py_script (_arka_py_script ", "(_arka_py_script ")

    text = text.replace(
        'if test -f "(_arka_py_script arka_platform.py)"',
        'if test -f (_arka_py_script arka_platform.py)',
    )
    text = text.replace(
        '$py "(_arka_py_script arka_platform.py)"',
        '$py (_arka_py_script arka_platform.py)',
    )

    path.write_text(text, encoding="utf-8")


def main() -> int:
    relocate()
    fish_cfg = FISH / "config.fish"
    if fish_cfg.is_file():
        patch_config(fish_cfg)
    print("Done: src/arka/{fish,aie,requirements,...}, bin/ shims, root config stub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
