"""Auditable deployment command generation for popular hosting platforms."""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path

SUPPORTED_PLATFORMS = [
    "vercel",
    "netlify",
    "railway",
    "render",
    "huggingface",
    "cloudflare",
    "github-pages",
    "docker",
    "docker-compose",
    "cloud",
]

def detect_platform(root: Path) -> str:
    if (root / "vercel.json").is_file() or (root / ".vercel").is_dir():
        return "vercel"
    if (root / "netlify.toml").is_file():
        return "netlify"
    if (root / "railway.toml").is_file():
        return "railway"
    if (root / "render.yaml").is_file():
        return "render"
    if (root / "Dockerfile").is_file() or (root / "docker-compose.yml").is_file() or (root / "scripts" / "deploy_cloud.sh").is_file():
        return "cloud"
    if (root / "package.json").is_file():
        return "vercel"
    return "netlify"

def detect_all_platforms(root: Path) -> list[str]:
    platforms: list[str] = []
    if (root / "vercel.json").is_file() or (root / ".vercel").is_dir():
        platforms.append("vercel")
    if (root / "netlify.toml").is_file():
        platforms.append("netlify")
    if (root / "railway.toml").is_file():
        platforms.append("railway")
    if (root / "render.yaml").is_file():
        platforms.append("render")
    if (root / "Dockerfile").is_file() or (root / "docker-compose.yml").is_file() or (root / "scripts" / "deploy_cloud.sh").is_file():
        platforms.append("cloud")
    if (root / "wrangler.toml").is_file():
        platforms.append("cloudflare")
    if not platforms:
        if (root / "package.json").is_file():
            platforms.append("vercel")
        else:
            platforms.append("netlify")
    return list(dict.fromkeys(platforms))

def deployment_command(root: Path, platform: str, *, production: bool = False) -> list[str]:
    if platform == "vercel":
        return ["vercel", "--prod"] if production else ["vercel"]
    if platform == "netlify":
        return ["netlify", "deploy", "--prod"] if production else ["netlify", "deploy"]
    if platform == "railway":
        return ["railway", "up", "--ci"] if production else ["railway", "up", "--ci", "--detach"]
    if platform == "render":
        return ["render", "deploy"]
    if platform == "huggingface":
        return ["git", "push", "hf", "main"]
    if platform == "cloudflare":
        return ["wrangler", "deploy"]
    if platform == "github-pages":
        return ["git", "push", "origin", "gh-pages"]
    if platform in ("docker", "docker-compose", "cloud"):
        if (root / "scripts" / "deploy_cloud.sh").is_file():
            return ["./scripts/deploy_cloud.sh"]
        return ["docker", "compose", "up", "-d", "--build"]
    raise ValueError("unsupported deployment platform")

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Preview or run a guarded single or multi-platform deployment")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument(
        "--platform",
        choices=SUPPORTED_PLATFORMS + ["all"],
        help="Target single platform or 'all' for multi-platform deploy",
    )
    p.add_argument(
        "--platforms",
        help="Comma-separated list of target platforms (e.g. vercel,railway,cloud)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Deploy to all detected platforms matching workspace configuration",
    )
    p.add_argument("--production", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.path).expanduser().resolve()

    target_platforms: list[str] = []
    if args.all or args.platform == "all":
        target_platforms = detect_all_platforms(root)
    elif args.platforms:
        target_platforms = [part.strip().lower() for part in args.platforms.split(",") if part.strip()]
    elif args.platform:
        target_platforms = [args.platform]
    else:
        target_platforms = [detect_platform(root)]

    deployments: list[dict[str, object]] = []
    for platform in target_platforms:
        command = deployment_command(root, platform, production=args.production)
        available = shutil.which(command[0]) is not None or (command[0].startswith("./") and (root / command[0][2:]).is_file())
        deployments.append({
            "root": str(root),
            "platform": platform,
            "command": command,
            "available": available,
        })

    if len(deployments) == 1 and not (args.all or args.platforms or args.platform == "all"):
        payload = deployments[0]
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Platform: {payload['platform']}\nCommand: {' '.join(payload['command'])}\nCLI available: {'yes' if payload['available'] else 'no'}")
        if not args.yes:
            return 0
        if not payload["available"]:
            print(f"Install {payload['command'][0]} and authenticate before deploying.")
            return 1
        return subprocess.call(payload["command"], cwd=root)

    multi_payload = {
        "root": str(root),
        "total_platforms": len(deployments),
        "deployments": deployments,
    }
    if args.json:
        print(json.dumps(multi_payload, indent=2))
    else:
        print(f"Multi-Platform Deployment Plan ({len(deployments)} targets):")
        for dep in deployments:
            print(f"  • Platform: {dep['platform']}")
            print(f"    Command:  {' '.join(dep['command'])}")
            print(f"    Ready:    {'yes' if dep['available'] else 'no'}")
            print("---")
    if not args.yes:
        return 0

    exit_code = 0
    for dep in deployments:
        print(f"\n[Multi-Deploy] Running deployment for {dep['platform']}...")
        if not dep["available"]:
            print(f"Skipping {dep['platform']}: CLI tool '{dep['command'][0]}' not available.")
            exit_code = 1
            continue
        res = subprocess.call(dep["command"], cwd=root)
        if res != 0:
            print(f"Deployment failed for platform {dep['platform']} with exit code {res}")
            exit_code = res
        else:
            print(f"✓ Deployment successful for platform {dep['platform']}")
    return exit_code
