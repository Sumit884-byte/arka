"""Create a reproducible, secret-free judge demo package."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka judge-demo")
    parser.add_argument("command", choices=("init", "check"), nargs="?", default="init")
    parser.add_argument("path", nargs="?", default=".arka-demo")
    args = parser.parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    manifest = {"name": "Arka judge demo", "version": "1", "credentials": "none", "data": "synthetic only", "supported_platforms": ["macOS 12+", "Linux (glibc)", "Windows  WSL2"], "installation": ["python3 -m venv .venv", ". .venv/bin/activate (Windows: .venv\\Scripts\\activate)", "pip install arka-agent", "copy demo.env.example to the environment"], "commands": ["arka help", "arka workspace .", "arka mcp-auto list", "arka edge status"], "safety": ["no production credentials", "no external writes", "sandbox or local-only model recommended"]}
    if args.command == "check":
        required = ["README.md", "manifest.json", "demo.env.example"]
        missing = [name for name in required if not (root / name).is_file()]
        print(f"demo\t{'ready' if not missing else 'incomplete'}")
        for name in missing:
            print(f"missing\t{name}")
        return 0 if not missing else 1
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (root / "demo.env.example").write_text("ARKA_MODEL_POLICY=local-only\nARKA_GROUNDED_MODE=1\nARKA_PRODUCTION_MODE=1\n", encoding="utf-8")
    (root / "README.md").write_text("# Arka judge demo\n\n## Supported platforms\n\n- macOS 12+\n- Linux with glibc\n- Windows through WSL2\n\n## Install\n\n```bash\npython3 -m venv .venv\n. .venv/bin/activate\npip install arka-agent\n```\n\nWindows PowerShell: `.venv\\Scripts\\Activate.ps1`. Copy `demo.env.example` to your environment, then run the commands in `manifest.json`. No repository rebuild or credentials are required.\n\nThis package uses synthetic data and is safe for evaluation.\n", encoding="utf-8")
    print(f"created\t{root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
