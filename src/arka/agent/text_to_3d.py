"""Text-to-3D skill with free/non-trial providers first."""

from __future__ import annotations

import argparse
import shlex
import sys


def route_command(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return ""
    import re

    if not re.search(r"(?i)\b(?:text[- ]?to[- ]?3d|generate|create|make|turn|convert)\b", clean):
        return ""
    if not re.search(r"(?i)\b(?:text[- ]?to[- ]?3d|model\s+from\s+text|from\s+text|hugging\s*face|free\s+providers?)\b", clean):
        return ""
    prompt = re.sub(r"(?i)\b(?:using|with)\s+(?:hugging\s*face|hf|free\s+providers?|free)\b", "", clean).strip()
    prompt = re.sub(r"(?i)^(?:arka\s+)?(?:text[-_ ]?to[-_ ]?3d|generate|create|make|turn|convert)\s+", "", prompt).strip()
    prompt = re.sub(r"(?i)^(?:a|an|the)\s+", "", prompt).strip()
    if not prompt:
        prompt = clean
    return "text_to_3d generate " + shlex.quote(prompt)


def _provider_summary() -> str:
    from arka.media.compose_3d_backends import auto_backend_order, backend_catalog

    lines = [
        "Default provider policy: free/non-trial first.",
        "Auto order: " + ", ".join(auto_backend_order()),
        "Trial/paid APIs are skipped unless ARKA_3D_ALLOW_TRIAL_PROVIDERS=1 or explicitly selected.",
        "",
        "Backends:",
    ]
    for info in backend_catalog():
        icon = "✓" if info.available else "○"
        lines.append(f"  {icon} {info.slug:<10} {info.label} — {info.detail}")
    return "\n".join(lines)


def generate(prompt: str, *, backend: str = "auto", fmt: str = "glb", name: str = "") -> int:
    from arka.media.compose_3d import main as compose_main

    argv = ["compose", prompt, "--backend", backend, "--format", fmt]
    if name:
        argv.extend(["--name", name])
    return compose_main(argv)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka text_to_3d",
        description="Generate 3D models from text using free/non-trial providers by default",
    )
    sub = parser.add_subparsers(dest="cmd")

    gen = sub.add_parser("generate", help="Generate a model from text")
    gen.add_argument("prompt", nargs="+")
    gen.add_argument("--backend", default="auto", help="auto, shap-e, hf-shap-e, openscad, llm, tripo, meshy")
    gen.add_argument("-f", "--format", default="glb", choices=("obj", "stl", "glb", "all"))
    gen.add_argument("--name", default="")

    sub.add_parser("providers", help="Show provider order and availability")

    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))
    if args.cmd == "providers":
        print(_provider_summary())
        return 0
    if args.cmd == "generate":
        return generate(" ".join(args.prompt), backend=args.backend, fmt=args.format, name=args.name)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
