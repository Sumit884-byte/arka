"""Skill execution backends — in-process Python vs optional fish/shell."""

from __future__ import annotations

from typing import Protocol

from arka.core.python_skills import (
    FISH_ONLY_SKILLS,
    PYTHON_NATIVE_SKILLS,
    is_fish_only,
    is_python_native,
    resolve_python_name,
)
from arka.core.skill_registry import SkillSpec, ensure_builtins, registry


class SkillBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def can_run(self, skill: str) -> bool: ...

    def skill_names(self) -> list[str]: ...

    def run(self, skill: str, argv: list[str] | None = None) -> int | None: ...


class PythonBackend:
    """In-process skills via the lazy registry, with dispatch as adapter wrap."""

    name = "python"

    def available(self) -> bool:
        return True

    def can_run(self, skill: str) -> bool:
        if is_fish_only(skill):
            return False
        key = resolve_python_name(skill)
        if is_python_native(key):
            return True
        ensure_builtins()
        return registry.resolve(key) is not None

    def skill_names(self) -> list[str]:
        ensure_builtins()
        names = set(PYTHON_NATIVE_SKILLS)
        names.update(registry.list_names())
        return sorted(names)

    def get(self, skill: str) -> SkillSpec | None:
        ensure_builtins()
        return registry.get(resolve_python_name(skill))

    def run(self, skill: str, argv: list[str] | None = None) -> int | None:
        if not self.can_run(skill):
            return None
        key = resolve_python_name(skill)
        args = list(argv or [])
        ensure_builtins()
        spec = registry.get(key)
        if spec is not None:
            return spec.run(args)
        from arka.dispatch import run_skill

        line = key if not args else f"{key} {' '.join(args)}"
        return run_skill(line)


class ShellBackend:
    """Fish/config.fish subprocess fallback for shell-only skills."""

    name = "shell"

    def available(self) -> bool:
        from arka.platform_info import has_full_fish_agent

        return has_full_fish_agent()

    def can_run(self, skill: str) -> bool:
        return self.available()

    def skill_names(self) -> list[str]:
        if not self.available():
            return []
        return sorted(FISH_ONLY_SKILLS)

    def run(self, skill: str, argv: list[str] | None = None) -> int | None:
        if not self.available():
            return None
        from arka.fish_bridge import delegate_subcommand, delegate_to_fish

        args = list(argv or [])
        code = delegate_subcommand(skill.replace("_", "-"), args)
        if code is not None:
            return code
        return delegate_to_fish([skill, *args])
