"""Route skills to Python first, fish/shell only when needed.

Replaces the ``skill_mode()`` fish gate: Python-native skills are available
on bash/zsh/PowerShell with no migration. Fish remains an optional backend
for mic/TTS/service loops.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arka.core.skill_backends import PythonBackend, ShellBackend, SkillBackend
from arka.core.skill_registry import SkillSpec


@dataclass
class CapabilityRouter:
    backends: list[SkillBackend] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.backends:
            self.backends = [PythonBackend(), ShellBackend()]

    def available_skills(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for backend in self.backends:
            if not backend.available():
                continue
            for name in backend.skill_names():
                if name in seen:
                    continue
                seen.add(name)
                out.append(name)
        return sorted(out)

    def backend_for(self, skill: str) -> SkillBackend | None:
        for backend in self.backends:
            if backend.available() and backend.can_run(skill):
                return backend
        return None

    def get(self, skill: str) -> SkillSpec | None:
        python = next((b for b in self.backends if isinstance(b, PythonBackend)), None)
        if python is None:
            return None
        return python.get(skill)

    def run(self, skill: str, argv: list[str] | None = None) -> int | None:
        backend = self.backend_for(skill)
        if backend is None:
            return None
        return backend.run(skill, argv)

    def python_skill_count(self) -> int:
        python = next((b for b in self.backends if isinstance(b, PythonBackend)), None)
        if python is None:
            return 0
        return len(python.skill_names())

    def has_shell(self) -> bool:
        return any(b.name == "shell" and b.available() for b in self.backends)


_ROUTER: CapabilityRouter | None = None


def default_router() -> CapabilityRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = CapabilityRouter()
    return _ROUTER


def available_skills() -> list[str]:
    return default_router().available_skills()


def run_capability(skill: str, argv: list[str] | None = None) -> int | None:
    return default_router().run(skill, argv)
