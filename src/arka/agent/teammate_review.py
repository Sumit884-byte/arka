"""Workspace-aware AI teammate review, focused on cross-service regressions."""

from __future__ import annotations
import argparse
import json
import subprocess
from pathlib import Path
from arka.agent.workspace import discover


def report(root: Path) -> dict:
    diff = subprocess.run(
        ["git", "diff", "--stat", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    changed = []
    for line in diff.stdout.splitlines():
        if " | " in line:
            changed.append(line.split(" | ", 1)[0].strip())
    services = discover(root)["services"]
    affected = [
        s
        for s in services
        if any(p == s["path"] or p.startswith(s["path"] + "/") for p in changed)
    ]
    findings = []
    if len(affected) > 1:
        findings.append(
            {
                "severity": "high",
                "title": "cross-service change",
                "detail": "Diff touches multiple discovered services; run each service's tests and contract checks.",
            }
        )
    if any(
        Path(p).name
        in {
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "go.mod",
            "Cargo.toml",
        }
        for p in changed
    ):
        findings.append(
            {
                "severity": "medium",
                "title": "dependency or build boundary changed",
                "detail": "Run lockfile, build, and deployment smoke checks for the affected service.",
            }
        )
    if not changed:
        findings.append(
            {
                "severity": "info",
                "title": "no committed diff detected",
                "detail": "Stage changes or compare a branch before relying on this review.",
            }
        )
    return {
        "changed": changed,
        "services": services,
        "affected_services": affected,
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka teammate-review")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    data = report(Path(args.path).expanduser().resolve())
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(
            f"changed_files\t{len(data['changed'])}\naffected_services\t{len(data['affected_services'])}"
        )
        for f in data["findings"]:
            print(f"{f['severity']}\t{f['title']}\t{f['detail']}")
    return 0
