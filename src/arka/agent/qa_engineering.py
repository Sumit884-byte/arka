#!/usr/bin/env python3
"""QA Engineering — test strategy, checklists, coverage, triage, and bug reports."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from arka.agent.pr_check import (
        collect_diff,
        current_branch,
        detect_base,
        failed_run_logs,
        git_root,
        gh_available,
    )
    from arka.agent.repo_health import _project_root, _run, detect_checks
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def git_root() -> Path | None:
        return None

    def _project_root(explicit: str | None = None) -> Path:
        if explicit:
            return Path(explicit).expanduser().resolve()
        return Path.cwd().resolve()

    def detect_checks(root: Path) -> list:
        return []

    def _run(cmd, *, cwd=None, timeout=120):
        return 1, "", "unavailable"


_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"qa\s+(?:engineering|checklist|plan|report|triage|coverage)|"
    r"run\s+qa\b|"
    r"qa\s+(?:on|for)\b|"
    r"test\s+(?:strategy|plan|checklist)|"
    r"production[-\s]+ready\s+(?:constraints?|gate|checklist|qa)\b|"
    r"prod(?:uction)?\s+readiness\b|"
    r"extreme\s+(?:qa|test(?:ing)?|constraints?)\b|"
    r"gherkin\s+tests?\b|"
    r"mutation\s+testing\b|"
    r"quality\s+metrics\b|"
    r"triage\s+(?:test|ci|pytest|e2e)\b|"
    r"test\s+coverage\b|"
    r"bug\s+report\b|"
    r"exploratory\s+testing\b|"
    r"smoke\s+test\s+plan|"
    r"regression\s+(?:test\s+)?plan"
    r")\b"
)
_TEST_FAILURE_RE = re.compile(
    r"(?i)(FAILED|ERROR|AssertionError|pytest|playwright|jest|vitest|"
    r"Test\s+Suite|tests?\s+failed|exit\s+code\s+[1-9])"
)


@dataclass(frozen=True)
class TestLayer:
    name: str
    scope: str
    tools: tuple[str, ...]
    commands: tuple[str, ...]
    notes: str = ""


def wants_qa_engineering(text: str) -> bool:
    return bool(_TRIGGER_RE.search(text or ""))


def route_command(text: str) -> str:
    if not wants_qa_engineering(text):
        return ""
    clean = re.sub(r"\s+", " ", (text or "").strip())
    low = clean.lower()

    if re.search(r"(?i)\bqa_engineering\b", low):
        rest = re.sub(r"(?i)^(?:arka\s+)?qa_engineering\s*", "", clean).strip()
        return f"qa_engineering {rest}".strip() if rest else "qa_engineering plan"

    if re.search(
        r"(?i)\b(?:production[-\s]+ready\s+(?:constraints?|gate|checklist|qa)|prod(?:uction)?\s+readiness|"
        r"extreme\s+(?:qa|test(?:ing)?|constraints?)|gherkin\s+tests?|mutation\s+testing|quality\s+metrics)\b",
        low,
    ):
        feature = _extract_feature(clean)
        if feature:
            return f"qa_engineering extreme --feature {json.dumps(feature)}"
        return "qa_engineering extreme"
    if re.search(r"(?i)\b(?:triage|diagnos\w*)\b.*\b(?:test|ci|pytest|e2e|failures?)\b", low):
        return "qa_engineering triage"
    if re.search(r"(?i)\b(?:test|code)\s+coverage\b|\bcoverage\s+(?:report|analysis)\b", low):
        return "qa_engineering coverage"
    if re.search(r"(?i)\bbug\s+report\b", low):
        title = _extract_quoted_or_tail(clean, r"(?i)\bbug\s+report\s+(?:for\s+)?")
        return f"qa_engineering report --title {json.dumps(title or 'Bug report')}"
    if re.search(r"(?i)\bexploratory\s+testing\b", low):
        feature = _extract_feature(clean)
        if feature:
            return f"qa_engineering explore --feature {json.dumps(feature)}"
        return "qa_engineering explore"
    if re.search(r"(?i)\b(?:qa\s+)?checklist\b", low):
        feature = _extract_feature(clean)
        if feature:
            return f"qa_engineering checklist --feature {json.dumps(feature)}"
        return "qa_engineering checklist"
    if re.search(r"(?i)\b(?:test\s+)?plan\b|\btest\s+strategy\b|\brun\s+qa\b|\bqa\s+on\b", low):
        feature = _extract_feature(clean)
        if feature:
            return f"qa_engineering plan --feature {json.dumps(feature)}"
        return "qa_engineering plan"

    return "qa_engineering plan"


def _extract_feature(text: str) -> str:
    match = re.search(
        r"(?i)\b(?:for|on)\s+(?:feature\s+)?['\"]?([^'\"]+?)['\"]?(?:\s*$|\s+(?:in|with|and)\b)",
        text,
    )
    if match:
        value = match.group(1).strip(" :-")
        if value.lower() not in {"this", "that", "it", "repo", "project", "codebase"}:
            return value
    quoted = re.search(r"['\"]([^'\"]{3,})['\"]", text)
    if quoted:
        return quoted.group(1).strip()
    return ""


def _extract_quoted_or_tail(text: str, prefix_re: str) -> str:
    tail = re.sub(prefix_re, "", text).strip()
    quoted = re.search(r"['\"]([^'\"]+)['\"]", tail)
    if quoted:
        return quoted.group(1).strip()
    return tail.strip(" :-")[:120]


def _has_file(root: Path, pattern: str) -> bool:
    return any(root.glob(pattern))


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def detect_test_stack(root: Path) -> dict:
    pkg = _read_json(root / "package.json") if (root / "package.json").is_file() else None
    scripts = (pkg or {}).get("scripts") or {}
    deps = {
        **((pkg or {}).get("dependencies") or {}),
        **((pkg or {}).get("devDependencies") or {}),
    }

    frameworks: list[str] = []
    if _has_file(root, "pytest.ini") or _has_file(root, "pyproject.toml") or _has_dir(root, "tests"):
        frameworks.append("pytest")
    if _has_file(root, "playwright.config.*") or "@playwright/test" in deps:
        frameworks.append("playwright")
    if "jest" in deps or _has_file(root, "jest.config.*"):
        frameworks.append("jest")
    if "vitest" in deps or _has_file(root, "vitest.config.*"):
        frameworks.append("vitest")
    if (root / "Cargo.toml").is_file():
        frameworks.append("cargo")
    if (root / "go.mod").is_file():
        frameworks.append("go")

    smoke_cmds: list[str] = []
    regression_cmds: list[str] = []
    if "pytest" in frameworks:
        smoke_cmds.append("pytest -q --tb=line -x")
        regression_cmds.append("pytest -q")
    if "playwright" in frameworks:
        smoke_cmds.append("npx playwright test --grep @smoke")
        regression_cmds.append("npx playwright test")
    if scripts.get("test"):
        smoke_cmds.append("npm test")
    if (root / "Cargo.toml").is_file():
        smoke_cmds.append("cargo test --quiet")
    if (root / "go.mod").is_file():
        smoke_cmds.append("go test ./...")

    return {
        "path": str(root),
        "frameworks": frameworks,
        "npm_scripts": {k: v for k, v in scripts.items() if k in ("test", "lint", "e2e", "test:e2e")},
        "has_e2e_dir": _has_dir(root, "e2e") or _has_dir(root, "tests/e2e"),
        "has_integration_dir": _has_dir(root, "tests/integration") or _has_dir(root, "integration"),
        "smoke_commands": smoke_cmds,
        "regression_commands": regression_cmds,
        "browser_check": "browser_check <url>",
        "visual_diagnose": "visual_diagnose <screenshot.png>",
        "repo_health": "repo_health run --test",
    }


def _has_dir(root: Path, name: str) -> bool:
    return (root / name).is_dir()


def _changed_files(root: Path, base: str | None = None) -> list[str]:
    if git_root() is None:
        return []
    base_ref = detect_base(root, base)
    _, files = collect_diff(root, base_ref, stat_only=True)
    return files


def plan_payload(root: Path | str | None = None, *, feature: str | None = None) -> dict:
    path = _project_root(str(root) if root is not None else None)
    stack = detect_test_stack(path)
    checks = [c for c in detect_checks(path) if c.category == "test"]

    layers: list[dict] = [
        {
            "layer": "unit",
            "goal": "Validate isolated functions, classes, and modules.",
            "tools": [f for f in stack["frameworks"] if f in ("pytest", "jest", "vitest", "cargo", "go")],
            "commands": [c.name + ": " + " ".join(c.command) for c in checks[:3]],
            "focus": feature or "Changed modules and edge cases",
        },
        {
            "layer": "integration",
            "goal": "Verify module boundaries, APIs, and data flows.",
            "tools": ["pytest", "jest"] if stack["has_integration_dir"] else stack["frameworks"][:2],
            "commands": ["pytest tests/integration -q"] if stack["has_integration_dir"] else [],
            "focus": "Service boundaries, DB/API contracts, error propagation",
        },
        {
            "layer": "e2e",
            "goal": "Exercise critical user journeys end-to-end.",
            "tools": [f for f in stack["frameworks"] if f in ("playwright", "jest")],
            "commands": stack["regression_commands"][-1:] if "playwright" in stack["frameworks"] else [],
            "focus": "Primary flows for " + (feature or "the feature under test"),
        },
        {
            "layer": "smoke",
            "goal": "Fast pre-merge sanity checks.",
            "tools": stack["frameworks"][:2],
            "commands": stack["smoke_commands"][:3],
            "focus": "Happy path only; fail fast",
        },
        {
            "layer": "regression",
            "goal": "Catch regressions across the existing suite.",
            "tools": stack["frameworks"],
            "commands": stack["regression_commands"][:3] or [c.name for c in checks[:2]],
            "focus": "Full automated suite before release",
        },
    ]

    pointers = {
        "accessibility": "Use browser_check for console/render smoke; pair with visual_diagnose on screenshots.",
        "performance": "Watch CI duration trends; use repo_health run --test for quick perf of test suite.",
        "manual": "See qa_engineering explore for exploratory charter ideas.",
    }

    return {
        "path": str(path),
        "feature": feature or "",
        "stack": stack,
        "layers": layers,
        "pointers": pointers,
        "next_steps": [
            "qa_engineering checklist" + (f" --feature {feature!r}" if feature else ""),
            "repo_health run --test",
            "qa_engineering coverage",
        ],
    }


def extreme_payload(root: Path | str | None = None, *, feature: str | None = None) -> dict:
    """Return an opt-in, high-rigor production-readiness constraint pack."""
    path = _project_root(str(root) if root is not None else None)
    stack = detect_test_stack(path)
    subject = feature or "the changed behavior"
    constraint_groups = _production_constraint_groups(subject)
    return {
        "path": str(path),
        "feature": feature or "",
        "mode": "extreme_constraints",
        "principle": (
            "Use this when production readiness matters. Prefer evidence from executable checks, "
            "reviewable configs, and documented procedures; do not invent passing status, coverage "
            "numbers, security posture, SLOs, or quality metrics."
        ),
        "constraint_groups": constraint_groups,
        "constraints": [item for group in constraint_groups for item in group["constraints"]],
        "suggested_commands": _extreme_commands(stack),
        "definition_of_done": [
            "All relevant automated tests pass, with command names recorded.",
            "Coverage and mutation results are reported honestly, including unavailable tooling.",
            "Gherkin/acceptance scenarios cover at least happy path, main failure path, and one edge case.",
            "Manual QA procedure is reproducible by another developer.",
            "Security/privacy checks are complete or explicit exceptions are documented.",
            "Observability, rollback, and deployment smoke paths are documented and verified.",
            "No quality, performance, security, SLO, or readiness claim is made without evidence.",
        ],
    }


def _production_constraint_groups(subject: str) -> list[dict]:
    return [
        {
            "group": "Correctness and tests",
            "constraints": [
                {
                    "name": "Unit tests",
                    "requirement": f"Cover pure logic, edge cases, and regressions for {subject}.",
                    "evidence": "Focused unit-test command plus changed test files.",
                },
                {
                    "name": "Gherkin / acceptance tests",
                    "requirement": "Write Given/When/Then scenarios for user-visible behavior and business rules.",
                    "evidence": "Feature files or equivalent acceptance-test cases linked to the implementation.",
                },
                {
                    "name": "Integration and contract tests",
                    "requirement": "Verify API, database, queue, filesystem, and external-service boundaries.",
                    "evidence": "Integration/contract command output or documented mocked boundary.",
                },
                {
                    "name": "End-to-end and smoke tests",
                    "requirement": "Exercise critical user journeys and a fast deploy smoke path.",
                    "evidence": "E2E/smoke command output, URL/environment, screenshots or traces when UI-related.",
                },
                {
                    "name": "Regression and compatibility",
                    "requirement": "Retest adjacent flows and supported platforms/browsers/runtimes touched by the change.",
                    "evidence": "Regression matrix with pass/fail notes for each supported target.",
                },
            ],
        },
        {
            "group": "Quality gates",
            "constraints": [
                {
                    "name": "Test coverage",
                    "requirement": "Report line/branch coverage and changed-code coverage; avoid raw percentage theater.",
                    "evidence": "Coverage command output and uncovered high-risk paths.",
                },
                {
                    "name": "Mutation testing",
                    "requirement": "Run mutation testing for critical logic or list the smallest mutation target when unavailable.",
                    "evidence": "Mutation score/report, surviving mutants, or documented blocker.",
                },
                {
                    "name": "Static analysis and lint",
                    "requirement": "Run formatter/linter/type/security scanners that match the detected stack.",
                    "evidence": "Commands and outputs for lint, type check, dependency scan, and secret scan.",
                },
                {
                    "name": "Quality metrics",
                    "requirement": "Track defect risk, flaky tests, runtime budget, performance, accessibility, and error rates.",
                    "evidence": "Measured metrics or an explicit 'not measured' note with rationale.",
                },
            ],
        },
        {
            "group": "Security and privacy",
            "constraints": [
                {
                    "name": "Auth and authorization",
                    "requirement": "Verify role boundaries, ownership checks, session expiry, and denied paths.",
                    "evidence": "Tests or manual QA notes for allowed and forbidden actions.",
                },
                {
                    "name": "Input validation and abuse cases",
                    "requirement": "Test invalid input, malformed data, injection strings, rate limits, and oversized payloads.",
                    "evidence": "Negative tests or fuzz/property checks for high-risk parsers and endpoints.",
                },
                {
                    "name": "Secrets and data privacy",
                    "requirement": "Do not log, expose, snapshot, or commit tokens, PII, credentials, or trade-secret payload values.",
                    "evidence": "Secret scan plus log/output review; use schemas or redacted samples for sensitive data.",
                },
                {
                    "name": "Dependency and supply-chain safety",
                    "requirement": "Check dependency vulnerabilities, licenses, lockfiles, install scripts, and untrusted plugins.",
                    "evidence": "Dependency audit output and license/security exceptions if any.",
                },
            ],
        },
        {
            "group": "Reliability and operations",
            "constraints": [
                {
                    "name": "Error handling and recovery",
                    "requirement": "Handle retries, timeouts, partial failures, idempotency, cancellation, and graceful degradation.",
                    "evidence": "Failure-mode tests or chaos/manual scenarios for dependency outages.",
                },
                {
                    "name": "Observability",
                    "requirement": "Emit useful logs, metrics, traces, correlation IDs, and alerts for new failure modes.",
                    "evidence": "Dashboard/alert/query links or local telemetry verification notes.",
                },
                {
                    "name": "Performance and scalability",
                    "requirement": "Check latency, memory, CPU, concurrency, payload size, and algorithmic complexity.",
                    "evidence": "Benchmark/load-test output or justified small-scale measurement.",
                },
                {
                    "name": "Runbook and rollback",
                    "requirement": "Document deploy, rollback, feature-flag, migration, and incident steps.",
                    "evidence": "Runbook/checklist entry with owner, command, and safe fallback.",
                },
            ],
        },
        {
            "group": "Release readiness",
            "constraints": [
                {
                    "name": "Configuration and environments",
                    "requirement": "Validate required env vars, defaults, hosted/offline modes, and missing-credential fallbacks.",
                    "evidence": "Config validation output and examples with secrets redacted.",
                },
                {
                    "name": "Backward compatibility",
                    "requirement": "Preserve public CLI/API/schema behavior or document migrations and deprecations.",
                    "evidence": "Compatibility tests or migration notes.",
                },
                {
                    "name": "Documentation and user experience",
                    "requirement": "Update docs, examples, help text, error messages, and troubleshooting for the changed behavior.",
                    "evidence": "Changed docs/help output and a quick user-facing smoke check.",
                },
                {
                    "name": "Data migration and integrity",
                    "requirement": "Make migrations reversible or resumable; verify backups, idempotency, and data correctness.",
                    "evidence": "Migration dry run, rollback notes, or explicit 'no data migration' statement.",
                },
            ],
        },
    ]


def _extreme_commands(stack: dict) -> list[str]:
    frameworks = set(stack.get("frameworks") or [])
    commands: list[str] = []
    if "pytest" in frameworks:
        commands.extend(
            [
                "pytest -q",
                "pytest --cov --cov-branch",
                "mutmut run || cosmic-ray run",
                "behave || pytest-bdd",
            ]
        )
    if {"jest", "vitest"} & frameworks:
        commands.extend(["npm test", "npm test -- --coverage", "stryker run", "cucumber-js"])
    if "playwright" in frameworks:
        commands.append("npx playwright test")
    if "go" in frameworks:
        commands.extend(["go test ./...", "go test -cover ./...", "go-mutesting ./..."])
    if "cargo" in frameworks:
        commands.extend(["cargo test", "cargo tarpaulin", "cargo mutants"])
    return commands or [
        "repo_health run --test",
        "qa_engineering coverage",
        "qa_engineering checklist",
        "Document Gherkin scenarios and mutation-testing availability",
    ]


def checklist_payload(
    root: Path | str | None = None,
    *,
    feature: str | None = None,
    base: str | None = None,
) -> dict:
    path = _project_root(str(root) if root is not None else None)
    changed = _changed_files(path, base)
    stack = detect_test_stack(path)
    subject = feature or (", ".join(changed[:5]) if changed else path.name)

    automated = [
        "Run smoke suite: " + (stack["smoke_commands"][0] if stack["smoke_commands"] else "repo_health run --test"),
        "Run full regression before merge: " + (stack["regression_commands"][0] if stack["regression_commands"] else "pytest -q"),
        "Check coverage delta: qa_engineering coverage",
    ]
    if changed:
        automated.append(f"Add/update tests for changed files ({len(changed)} file(s))")

    manual = [
        "Verify happy path for: " + subject,
        "Exercise invalid inputs, empty states, and permission errors",
        "Confirm error messages are actionable",
        "Retest adjacent flows that share code with changed files",
    ]
    if stack["frameworks"]:
        manual.append("Run exploratory session (qa_engineering explore) on untested paths")

    non_functional = [
        "Accessibility: keyboard navigation, focus order, labels (browser_check + screenshot review)",
        "Performance: page load / API latency on changed endpoints",
        "Security: auth boundaries on new routes or handlers",
        "Observability: logs/metrics for new failure modes",
    ]

    pr_items = [
        "All CI checks green (pr_check ci)",
        "Test plan documented in PR description",
        "No skipped tests without justification",
        "Rollback / feature-flag plan noted if risky",
    ]

    return {
        "path": str(path),
        "feature": feature or "",
        "changed_files": changed,
        "checklist": {
            "automated": automated,
            "manual": manual,
            "non_functional": non_functional,
            "pr_merge": pr_items,
        },
    }


def triage_payload(root: Path | str | None = None, *, base: str | None = None) -> dict:
    path = _project_root(str(root) if root is not None else None)
    if git_root() is None:
        return {"ok": False, "error": "Not inside a git repository.", "path": str(path)}
    if not gh_available():
        return {
            "ok": False,
            "error": "GitHub CLI not available. Run: gh auth login",
            "path": str(path),
            "fallback": "Run tests locally: repo_health run --test",
        }

    base_ref = detect_base(path, base)
    branch = current_branch(path)
    stat, files = collect_diff(path, base_ref, stat_only=True)
    logs, run = failed_run_logs(path, None, branch=branch)
    test_lines = [ln for ln in (logs or "").splitlines() if _TEST_FAILURE_RE.search(ln)]
    excerpt = "\n".join(test_lines[:40]) if test_lines else (logs or "")[:4000]

    likely_test_failure = bool(test_lines) or bool(re.search(r"(?i)\b(test|pytest|playwright|jest)\b", logs or ""))

    return {
        "ok": likely_test_failure or bool(logs),
        "path": str(path),
        "branch": branch,
        "base": base_ref,
        "changed_files": files,
        "workflow": (run or {}).get("workflowName"),
        "run_title": (run or {}).get("displayTitle"),
        "run_url": (run or {}).get("url"),
        "likely_test_failure": likely_test_failure,
        "log_excerpt": excerpt,
        "diff_stat": stat[:2000],
        "recommended_actions": [
            "Reproduce locally with the failing command from CI logs",
            "qa_engineering coverage — check if new code lacks tests",
            "pr_check explain — full CI diagnosis",
            "qa_engineering report --from-failure — draft bug report",
        ],
    }


def coverage_payload(root: Path | str | None = None) -> dict:
    path = _project_root(str(root) if root is not None else None)
    stack = detect_test_stack(path)
    commands: list[list[str]] = []

    if "pytest" in stack["frameworks"]:
        commands.append(["pytest", "--cov=.", "--cov-report=term-missing", "-q", "--tb=no"])
    pkg = _read_json(path / "package.json") if (path / "package.json").is_file() else None
    scripts = (pkg or {}).get("scripts") or {}
    if scripts.get("test") and "coverage" in json.dumps(pkg or {}).lower():
        commands.append(["npm", "test", "--", "--coverage"])

    if not commands:
        checks = [c for c in detect_checks(path) if c.category == "test"]
        if checks:
            commands.append(list(checks[0].command))

    results: list[dict] = []
    for cmd in commands[:2]:
        code, out, err = _run(cmd, cwd=path, timeout=600)
        combined = (out + err).strip()
        pct_match = re.search(r"(\d{1,3})%", combined)
        results.append(
            {
                "command": cmd,
                "exit_code": code,
                "coverage_percent": pct_match.group(1) if pct_match else None,
                "preview": "\n".join(combined.splitlines()[-15:]),
            }
        )

    return {
        "path": str(path),
        "frameworks": stack["frameworks"],
        "results": results,
        "ok": all(r["exit_code"] == 0 for r in results) if results else False,
        "note": "Install pytest-cov for Python coverage" if "pytest" in stack["frameworks"] else "",
    }


def report_payload(
    *,
    title: str = "Bug report",
    steps: str = "",
    expected: str = "",
    actual: str = "",
    severity: str = "medium",
    from_failure: bool = False,
    root: Path | str | None = None,
) -> dict:
    path = _project_root(str(root) if root is not None else None)
    environment = {
        "project": path.name,
        "path": str(path),
        "branch": current_branch(path) if git_root() else "",
    }

    if from_failure:
        triage = triage_payload(path)
        if triage.get("log_excerpt"):
            actual = actual or triage["log_excerpt"][:2000]
        if triage.get("run_title"):
            title = title if title != "Bug report" else f"CI failure: {triage['run_title']}"

    body = "\n".join(
        [
            f"# {title}",
            "",
            "## Summary",
            actual or "Describe the defect in one paragraph.",
            "",
            "## Environment",
            f"- Project: {environment['project']}",
            f"- Path: {environment['path']}",
            f"- Branch: {environment['branch'] or 'n/a'}",
            f"- Severity: {severity}",
            "",
            "## Steps to reproduce",
            steps or "1. …\n2. …\n3. …",
            "",
            "## Expected result",
            expected or "What should happen.",
            "",
            "## Actual result",
            actual or "What happened instead.",
            "",
            "## Evidence",
            "- Logs / screenshots",
            "- Related PR or commit",
            "",
            "## Suggested fix / notes",
            "- ",
        ]
    )

    return {"title": title, "severity": severity, "markdown": body, "environment": environment}


def explore_payload(*, feature: str | None = None) -> dict:
    subject = feature or "the feature under test"
    charter = {
        "mission": f"Explore {subject} for unexpected behavior, usability issues, and missing validations.",
        "time_box": "45–90 minutes",
        "areas": [
            "Happy path with realistic data",
            "Boundary values and empty/null inputs",
            "Concurrent or repeated actions",
            "Recovery after network/API errors",
            "Permissions and role differences",
            "Mobile/responsive layout if UI",
        ],
        "heuristics": [
            "CRUD — create, read, update, delete variations",
            "SFDPOT — Structure, Function, Data, Platform, Operations, Time",
            "Recent changes — files touched in this branch",
        ],
        "artifacts": [
            "Session notes with severity tags",
            "Screenshots for visual issues → visual_diagnose",
            "Bug reports → qa_engineering report",
        ],
        "tools": [
            "browser_check <url> — smoke + console errors",
            "visual_diagnose <screenshot> — UI defect hints",
            "repo_health run --test — automated baseline",
        ],
    }
    return {"feature": feature or "", "charter": charter}


def plan_text(payload: dict) -> str:
    lines = [f"QA test plan: {payload.get('feature') or Path(payload['path']).name}", ""]
    for layer in payload.get("layers") or []:
        lines.append(f"## {layer['layer'].title()} — {layer['goal']}")
        if layer.get("tools"):
            lines.append(f"Tools: {', '.join(layer['tools'])}")
        if layer.get("commands"):
            lines.append("Commands:")
            for cmd in layer["commands"]:
                lines.append(f"  - {cmd}")
        lines.append(f"Focus: {layer.get('focus', '')}")
        lines.append("")
    pointers = payload.get("pointers") or {}
    if pointers:
        lines.append("Pointers:")
        for key, val in pointers.items():
            lines.append(f"  - {key}: {val}")
    return "\n".join(lines).strip()


def extreme_text(payload: dict) -> str:
    lines = [f"Extreme production-readiness constraints: {payload.get('feature') or Path(payload['path']).name}", ""]
    lines.append(payload["principle"])
    lines.append("")
    lines.append("Required constraints:")
    groups = payload.get("constraint_groups") or [{"group": "General", "constraints": payload.get("constraints") or []}]
    for group in groups:
        lines.append(f"## {group['group']}")
        for item in group.get("constraints") or []:
            lines.append(f"- {item['name']}: {item['requirement']}")
            lines.append(f"  Evidence: {item['evidence']}")
        lines.append("")
    lines.append("Suggested commands:")
    for cmd in payload.get("suggested_commands") or []:
        lines.append(f"  - {cmd}")
    lines.append("")
    lines.append("Definition of done:")
    for item in payload.get("definition_of_done") or []:
        lines.append(f"  [ ] {item}")
    return "\n".join(lines).strip()


def checklist_text(payload: dict) -> str:
    lines = [f"QA checklist: {payload.get('feature') or Path(payload['path']).name}", ""]
    if payload.get("changed_files"):
        lines.append(f"Changed files ({len(payload['changed_files'])}):")
        for name in payload["changed_files"][:12]:
            lines.append(f"  - {name}")
        lines.append("")
    for section, items in (payload.get("checklist") or {}).items():
        lines.append(section.replace("_", " ").title() + ":")
        for item in items:
            lines.append(f"  [ ] {item}")
        lines.append("")
    return "\n".join(lines).strip()


def triage_text(payload: dict) -> str:
    if payload.get("error"):
        return payload["error"]
    lines = [
        "Test failure triage",
        f"Branch: {payload.get('branch', '?')} vs {payload.get('base', '?')}",
    ]
    if payload.get("workflow"):
        lines.append(f"Workflow: {payload['workflow']} — {payload.get('run_title', '')}")
    if payload.get("run_url"):
        lines.append(f"Run: {payload['run_url']}")
    lines.append("")
    if payload.get("likely_test_failure"):
        lines.append("Likely test-related failure detected in CI logs.")
    else:
        lines.append("CI logs captured; verify whether failure is test-related.")
    lines.append("")
    excerpt = payload.get("log_excerpt") or ""
    if excerpt:
        lines.append("Log excerpt:")
        lines.append(excerpt[:3500])
    lines.append("")
    lines.append("Recommended:")
    for action in payload.get("recommended_actions") or []:
        lines.append(f"  - {action}")
    return "\n".join(lines).strip()


def coverage_text(payload: dict) -> str:
    lines = [f"Coverage analysis: {Path(payload['path']).name}", ""]
    if not payload.get("results"):
        lines.append("No coverage runner detected. Try: pip install pytest-cov && pytest --cov")
        return "\n".join(lines)
    for row in payload["results"]:
        cmd = " ".join(row["command"])
        pct = row.get("coverage_percent")
        mark = "✓" if row["exit_code"] == 0 else "✗"
        suffix = f" ({pct}%)" if pct else ""
        lines.append(f"{mark} {cmd}{suffix}")
        preview = row.get("preview") or ""
        if preview:
            for pline in preview.splitlines():
                lines.append(f"  {pline[:160]}")
        lines.append("")
    if payload.get("note"):
        lines.append(payload["note"])
    return "\n".join(lines).strip()


def cmd_plan(args: argparse.Namespace) -> int:
    payload = plan_payload(args.path, feature=args.feature or None)
    print(plan_text(payload) if not args.json else json.dumps(payload, indent=2))
    return 0


def cmd_extreme(args: argparse.Namespace) -> int:
    payload = extreme_payload(args.path, feature=args.feature or None)
    print(extreme_text(payload) if not args.json else json.dumps(payload, indent=2))
    return 0


def cmd_checklist(args: argparse.Namespace) -> int:
    payload = checklist_payload(args.path, feature=args.feature or None, base=args.base or None)
    print(checklist_text(payload) if not args.json else json.dumps(payload, indent=2))
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    payload = triage_payload(args.path, base=args.base or None)
    print(triage_text(payload) if not args.json else json.dumps(payload, indent=2))
    return 0 if payload.get("ok", True) else 1


def cmd_coverage(args: argparse.Namespace) -> int:
    payload = coverage_payload(args.path)
    print(coverage_text(payload) if not args.json else json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


def cmd_report(args: argparse.Namespace) -> int:
    payload = report_payload(
        title=args.title or "Bug report",
        steps=args.steps or "",
        expected=args.expected or "",
        actual=args.actual or "",
        severity=args.severity or "medium",
        from_failure=args.from_failure,
        root=args.path,
    )
    print(payload["markdown"] if not args.json else json.dumps(payload, indent=2))
    return 0


def cmd_explore(args: argparse.Namespace) -> int:
    payload = explore_payload(feature=args.feature or None)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    charter = payload["charter"]
    lines = [
        f"Exploratory testing charter: {payload.get('feature') or 'current feature'}",
        "",
        f"Mission: {charter['mission']}",
        f"Time box: {charter['time_box']}",
        "",
        "Areas to explore:",
    ]
    for area in charter["areas"]:
        lines.append(f"  - {area}")
    lines.extend(["", "Heuristics:"])
    for item in charter["heuristics"]:
        lines.append(f"  - {item}")
    lines.extend(["", "Tools:"])
    for tool in charter["tools"]:
        lines.append(f"  - {tool}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(
        description="QA Engineering — test strategy, checklists, coverage, triage, bug reports",
    )
    sub = parser.add_subparsers(dest="cmd")

    for name, handler in (
        ("plan", cmd_plan),
        ("extreme", cmd_extreme),
        ("checklist", cmd_checklist),
        ("triage", cmd_triage),
        ("coverage", cmd_coverage),
        ("report", cmd_report),
        ("explore", cmd_explore),
    ):
        p = sub.add_parser(name, help=handler.__doc__ or name)
        p.add_argument("path", nargs="?", default=None, help="Project root (default: git root / cwd)")
        p.add_argument("--feature", default="", help="Feature or area under test")
        p.add_argument("--json", action="store_true", help="Emit JSON payload")
        p.set_defaults(func=handler)

    p_checklist = sub.choices["checklist"]
    p_checklist.add_argument("--base", "-b", default="", help="Base branch for changed files")

    p_triage = sub.choices["triage"]
    p_triage.add_argument("--base", "-b", default="", help="Base branch")

    p_report = sub.choices["report"]
    p_report.add_argument("--title", default="Bug report")
    p_report.add_argument("--steps", default="")
    p_report.add_argument("--expected", default="")
    p_report.add_argument("--actual", default="")
    p_report.add_argument("--severity", default="medium", choices=["low", "medium", "high", "critical"])
    p_report.add_argument("--from-failure", action="store_true", help="Seed report from latest CI test failure")

    p_route = sub.add_parser("route", help="Map NL to qa_engineering command")
    p_route.add_argument("text", nargs="+")

    args = parser.parse_args(argv)
    if args.cmd == "route":
        line = route_command(" ".join(args.text))
        if line:
            print(line)
            return 0
        return 1
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
