"""Discover repository scripts used for testing or verification — no hardcoded names."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_TEST_STEM_RE = re.compile(
    r"(?i)(?:^|[_-])(test|verify|smoke|e2e|spec|validation|validate)(?:[_-]|$|\.)"
)
_CHECK_STEM_RE = re.compile(r"(?i)(?:^|[_-])(check|audit|lint)(?:[_-]|$|\.)")
_OPS_STEM_RE = re.compile(
    r"(?i)(?:^|[_-])(sync|publish|refetch|install|deploy|organize|restructure|"
    r"fetch|release|loop|bootstrap|migrate|format|generate)(?:[_-]|$|\.)"
)
_VERIFY_DOC_RE = re.compile(
    r"(?i)\b(verif(?:y|ication)?|test(?:ing)?|smoke|e2e|regression|"
    r"reliabil(?:ity)?|sanity|qa)\b"
)
_CHECK_DOC_RE = re.compile(
    r"(?i)\b(check(?:s|ing)?|validat(?:e|ion)|audit|lint|ensure|broken\s+link)\b"
)
_OPS_DOC_RE = re.compile(
    r"(?i)\b(sync(?:ing)?|publish(?:ing)?|install(?:ing)?|deploy(?:ing)?|"
    r"release(?:ing)?|build wheel|refetch|restructur(?:e|ing)|organiz(?:e|ing))\b"
)
_SHELL_PYTEST_RE = re.compile(r"(?i)\b(pytest|python\s+-m\s+pytest|npm\s+test|cargo\s+test)\b")


@dataclass(frozen=True)
class ScriptArgument:
    name: str
    default: str | None
    action: str | None
    help_text: str


@dataclass
class ScriptProbe:
    path: Path
    stem: str
    suffix: str
    docstring: str = ""
    argparse_description: str = ""
    test_function_count: int = 0
    has_pytest_import: bool = False
    has_unittest_import: bool = False
    has_main_guard: bool = False
    positional_args: list[ScriptArgument] = field(default_factory=list)
    optional_flags: list[ScriptArgument] = field(default_factory=list)
    shell_invokes_tests: bool = False
    score: int = 0
    category: str | None = None
    reasons: list[str] = field(default_factory=list)


def _read_head(path: Path, *, limit: int = 16_384) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _parse_python_probe(path: Path, source: str) -> ScriptProbe:
    probe = ScriptProbe(path=path, stem=path.stem, suffix=path.suffix)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return probe

    if tree.body and isinstance(tree.body[0], ast.Expr):
        doc = _literal_str(tree.body[0].value)
        if doc:
            probe.docstring = doc.strip()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = (alias.name or "").split(".")[0]
                if base == "pytest":
                    probe.has_pytest_import = True
                if base == "unittest":
                    probe.has_unittest_import = True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.split(".")[0] == "pytest":
                probe.has_pytest_import = True
            if mod.split(".")[0] == "unittest":
                probe.has_unittest_import = True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                probe.test_function_count += 1
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr != "add_argument":
                continue
            arg = _extract_add_argument(node)
            if arg is None:
                continue
            if arg.name.startswith("-"):
                probe.optional_flags.append(arg)
            else:
                probe.positional_args.append(arg)
        elif isinstance(node, ast.If):
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
            ):
                probe.has_main_guard = True

    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Attribute) and call.func.attr == "ArgumentParser":
            for kw in call.keywords:
                if kw.arg == "description":
                    desc = _literal_str(kw.value)
                    if desc:
                        probe.argparse_description = desc.strip()
    return probe


def _extract_add_argument(call: ast.Call) -> ScriptArgument | None:
    name = ""
    default: str | None = None
    action: str | None = None
    help_text = ""

    if call.args:
        first = _literal_str(call.args[0])
        if first:
            name = first

    for kw in call.keywords:
        if kw.arg in {"default", "const"}:
            if isinstance(kw.value, ast.Constant):
                default = str(kw.value.value)
        elif kw.arg == "action":
            action = _literal_str(kw.value)
        elif kw.arg == "help":
            help_text = _literal_str(kw.value) or ""

    if not name and call.args:
        first = call.args[0]
        if isinstance(first, ast.Constant):
            name = str(first.value)

    if not name:
        return None
    return ScriptArgument(name=name, default=default, action=action, help_text=help_text)


def _parse_shell_probe(path: Path, source: str) -> ScriptProbe:
    probe = ScriptProbe(path=path, stem=path.stem, suffix=path.suffix)
    lines = source.splitlines()
    if lines and lines[0].startswith("#!"):
        probe.docstring = lines[0]
    for line in lines[:40]:
        stripped = line.strip()
        if stripped.startswith("#") and len(stripped) > 2:
            probe.docstring += "\n" + stripped.lstrip("#").strip()
    probe.shell_invokes_tests = bool(_SHELL_PYTEST_RE.search(source))
    probe.has_main_guard = True
    return probe


def probe_script(path: Path) -> ScriptProbe:
    path = path.expanduser().resolve()
    source = _read_head(path)
    if path.suffix == ".py":
        probe = _parse_python_probe(path, source)
    elif path.suffix in {".sh", ".bash"}:
        probe = _parse_shell_probe(path, source)
    else:
        probe = ScriptProbe(path=path, stem=path.stem, suffix=path.suffix)

    _score_probe(probe)
    return probe


def _score_probe(probe: ScriptProbe) -> None:
    score = 0
    reasons: list[str] = []
    stem = probe.stem
    doc_blob = " ".join(
        part for part in (probe.docstring, probe.argparse_description) if part
    )

    if _TEST_STEM_RE.search(stem):
        score += 4
        reasons.append("filename suggests verification/testing")
    if _CHECK_STEM_RE.search(stem):
        score += 3
        reasons.append("filename suggests checking/validation")
    check_flag = next((flag for flag in probe.optional_flags if flag.name == "--check"), None)
    validation_check = False
    if check_flag:
        help_blob = (check_flag.help_text or "").lower()
        if "fail" in help_blob or "would change" in help_blob or "valid" in help_blob:
            score += 3
            validation_check = True
            reasons.append("supports --check validation mode")

    if _OPS_STEM_RE.search(stem) and not validation_check:
        score -= 4
        reasons.append("filename suggests maintenance/ops (not a test runner)")
    elif _OPS_STEM_RE.search(stem) and validation_check:
        reasons.append("maintenance filename, but exposes read-only --check validation")

    if doc_blob:
        if _VERIFY_DOC_RE.search(doc_blob):
            score += 2
            reasons.append("docstring/description mentions verification/testing")
        if _CHECK_DOC_RE.search(doc_blob):
            score += 2
            reasons.append("docstring/description mentions checking/validation")
        if _OPS_DOC_RE.search(doc_blob) and not _VERIFY_DOC_RE.search(doc_blob):
            score -= 3
            reasons.append("docstring/description suggests maintenance work")

    if probe.test_function_count:
        score += min(probe.test_function_count * 2, 8)
        reasons.append(f"defines {probe.test_function_count} test_* function(s)")
    if probe.has_pytest_import:
        score += 2
        reasons.append("imports pytest")
    if probe.has_unittest_import and probe.test_function_count:
        score += 2
        reasons.append("uses unittest-style tests")

    if probe.shell_invokes_tests:
        score += 3
        reasons.append("shell script invokes a test runner")

    if probe.suffix == ".py" and probe.has_main_guard and score > 0:
        score += 1
        reasons.append("runnable Python entrypoint")

    category: str | None = None
    if score >= 4:
        if probe.test_function_count or probe.has_pytest_import or _TEST_STEM_RE.search(stem):
            category = "test"
        elif _CHECK_STEM_RE.search(stem) or check_flag or _CHECK_DOC_RE.search(doc_blob):
            category = "lint"
        else:
            category = "test"
    elif score >= 3 and (
        _CHECK_STEM_RE.search(stem) or check_flag or _CHECK_DOC_RE.search(doc_blob)
    ):
        category = "lint"

    probe.score = score
    probe.category = category
    probe.reasons = reasons


def _pick_default_positional(probe: ScriptProbe, repo: Path) -> list[str]:
    args: list[str] = []
    for pos in probe.positional_args:
        if pos.name.startswith("-"):
            continue
        default = pos.default
        if default is None:
            continue
        candidate = repo / default
        if candidate.exists():
            args.append(default)
            break
    return args


def _pick_validation_flags(probe: ScriptProbe) -> list[str]:
    flags: list[str] = []
    for flag in probe.optional_flags:
        if flag.name != "--check":
            continue
        help_blob = (flag.help_text or "").lower()
        if flag.action == "store_true" and (
            "fail" in help_blob or "would change" in help_blob or "valid" in help_blob
        ):
            flags.append("--check")
    return flags


def build_script_command(probe: ScriptProbe, repo: Path) -> list[str]:
    repo = repo.expanduser().resolve()
    rel = probe.path.resolve().relative_to(repo).as_posix()
    if probe.suffix == ".py":
        command = [sys.executable, rel]
    elif probe.suffix in {".sh", ".bash"}:
        command = ["bash", rel]
    else:
        command = [str(probe.path)]

    command.extend(_pick_validation_flags(probe))
    command.extend(_pick_default_positional(probe, repo))
    return command


def iter_script_candidates(root: Path) -> list[Path]:
    root = root.expanduser().resolve()
    candidates: list[Path] = []
    scripts_dir = root / "scripts"
    if scripts_dir.is_dir():
        for path in sorted(scripts_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".py", ".sh", ".bash"}:
                candidates.append(path)
    return candidates


def discover_verification_scripts(root: Path) -> list[ScriptProbe]:
    """Return scored script probes that look like test or verification runners."""
    root = root.expanduser().resolve()
    discovered: list[ScriptProbe] = []
    for path in iter_script_candidates(root):
        probe = probe_script(path)
        if probe.category:
            discovered.append(probe)
    discovered.sort(key=lambda item: (-item.score, item.path.name))
    return discovered


@dataclass(frozen=True)
class DiscoveredCheck:
    name: str
    command: list[str]
    category: str
    reasons: tuple[str, ...] = ()


def discover_script_checks(root: Path) -> list[DiscoveredCheck]:
    """Convert discovered verification scripts into runnable check descriptors."""
    checks: list[DiscoveredCheck] = []
    for probe in discover_verification_scripts(root):
        checks.append(
            DiscoveredCheck(
                name=f"script:{probe.path.name}",
                command=build_script_command(probe, root),
                category=probe.category or "test",
                reasons=tuple(probe.reasons),
            )
        )
    return checks


def format_script_discovery_text(root: Path) -> str:
    probes = discover_verification_scripts(root)
    if not probes:
        return ""

    lines = ["Verification scripts (discovered from scripts/):"]
    for probe in probes:
        rel = probe.path.relative_to(root.expanduser().resolve()).as_posix()
        cmd = " ".join(build_script_command(probe, root))
        reason = probe.reasons[0] if probe.reasons else "heuristic match"
        lines.append(f"  - {rel} [{probe.category}] — {reason}")
        lines.append(f"      {cmd}")
    return "\n".join(lines)


def discovery_hint(root: Path) -> str:
    """One-line hint for goal agents about discovered verification scripts."""
    probes = discover_verification_scripts(root)
    if not probes:
        return ""
    names = [probe.path.name for probe in probes[:4]]
    suffix = "…" if len(probes) > 4 else ""
    return (
        "- Discovered verification scripts in scripts/: "
        + ", ".join(names)
        + suffix
        + " (repo_health scan shows commands and why each matched)."
    )
