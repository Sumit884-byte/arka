"""Typed in-process skill registry — lazy loading, entry points, subprocess fallback."""

from __future__ import annotations

import importlib
import inspect
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

SkillHandler = Callable[[list[str]], int]
LazyLoader = Callable[[], SkillHandler]

ENTRYPOINT_GROUP = "arka.skills"


@dataclass
class SkillSpec:
    name: str
    handler: SkillHandler | None = None
    loader: LazyLoader | None = None
    import_path: str = ""
    aliases: tuple[str, ...] = ()
    origin: str = "builtin"  # builtin | entrypoint | eager

    def run(self, argv: list[str] | None = None) -> int:
        handler = self.handler
        if handler is None and self.loader is not None:
            handler = self.loader()
            self.handler = handler
        if handler is None:
            raise RuntimeError(f"skill {self.name} has no handler")
        return int(_adapt_handler(handler)(list(argv or [])))


@dataclass
class SkillRegistry:
    _by_name: dict[str, SkillSpec] = field(default_factory=dict)
    _entrypoints_loaded: bool = False

    def register(
        self,
        name: str,
        handler: SkillHandler,
        *,
        aliases: tuple[str, ...] | list[str] = (),
    ) -> None:
        key = _norm(name)
        spec = SkillSpec(name=key, handler=handler, origin="eager", aliases=_norm_aliases(aliases))
        self._by_name[key] = spec
        for alias in spec.aliases:
            self._by_name[alias] = spec

    def register_lazy(
        self,
        name: str,
        import_path: str,
        *,
        attr: str = "main",
        aliases: tuple[str, ...] | list[str] = (),
    ) -> None:
        key = _norm(name)
        path = import_path if ":" in import_path else f"{import_path}:{attr}"

        def _load() -> SkillHandler:
            mod_path, _, sym = path.partition(":")
            mod = importlib.import_module(mod_path)
            fn = getattr(mod, sym or "main")
            if not callable(fn):
                raise TypeError(f"{path} is not callable")
            return fn  # type: ignore[return-value]

        spec = SkillSpec(name=key, loader=_load, import_path=path, origin="builtin", aliases=_norm_aliases(aliases))
        self._by_name[key] = spec
        for alias in spec.aliases:
            self._by_name[alias] = spec

    def resolve(self, name: str) -> SkillSpec | None:
        self._ensure_entrypoints()
        return self._by_name.get(_norm(name))

    def get(self, name: str) -> SkillSpec | None:
        """Alias for resolve — PythonBackend calls registry.get(name).run(args)."""
        return self.resolve(name)

    def list_names(self) -> list[str]:
        self._ensure_entrypoints()
        seen: set[str] = set()
        out: list[str] = []
        for spec in self._by_name.values():
            if spec.name in seen:
                continue
            seen.add(spec.name)
            out.append(spec.name)
        return sorted(out)

    def run(self, name: str, argv: list[str] | None = None) -> int | None:
        """Run a registered skill. Returns None when name is not registered."""
        spec = self.get(name)
        if spec is None:
            return None
        return spec.run(argv)

    def _ensure_entrypoints(self) -> None:
        if self._entrypoints_loaded:
            return
        self._entrypoints_loaded = True
        try:
            from importlib.metadata import entry_points
        except ImportError:
            return
        eps = entry_points()
        group: Any
        if hasattr(eps, "select"):
            group = eps.select(group=ENTRYPOINT_GROUP)
        else:
            group = eps.get(ENTRYPOINT_GROUP, ())
        for ep in group:
            key = _norm(ep.name)
            if key in self._by_name:
                continue
            path = ep.value

            def _load(path: str = path) -> SkillHandler:
                mod_path, _, sym = path.partition(":")
                mod = importlib.import_module(mod_path)
                fn = getattr(mod, sym or "main")
                if not callable(fn):
                    raise TypeError(f"{path} is not callable")
                return fn  # type: ignore[return-value]

            spec = SkillSpec(name=key, loader=_load, import_path=path, origin="entrypoint")
            self._by_name[key] = spec


def _adapt_handler(fn: Callable[..., Any]) -> SkillHandler:
    """Wrap ``main`` / ``main(argv)`` so registry.run always passes argv."""

    def handler(argv: list[str]) -> int:
        try:
            sig = inspect.signature(fn)
            positional = [
                p
                for p in sig.parameters.values()
                if p.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            ]
        except (TypeError, ValueError):
            return int(fn(argv) or 0)
        if positional:
            return int(fn(argv) or 0)
        return int(fn() or 0)

    return handler


def _norm(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_")


def _norm_aliases(aliases: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_norm(a) for a in aliases if (a or "").strip()))


registry = SkillRegistry()


def register(name: str, handler: SkillHandler, *, aliases: tuple[str, ...] | list[str] = ()) -> None:
    registry.register(name, handler, aliases=aliases)


def register_lazy(
    name: str,
    import_path: str,
    *,
    attr: str = "main",
    aliases: tuple[str, ...] | list[str] = (),
) -> None:
    registry.register_lazy(name, import_path, attr=attr, aliases=aliases)


def run(name: str, argv: list[str] | None = None) -> int | None:
    return registry.run(name, argv)


def resolve(name: str) -> SkillSpec | None:
    return registry.resolve(name)


def get(name: str) -> SkillSpec | None:
    return registry.get(name)


def list_registered() -> list[str]:
    return registry.list_names()


def ensure_builtins() -> None:
    """Register built-in lazy skills once per process."""
    mod = sys.modules.get(__name__)
    flag = "_BUILTINS_REGISTERED"
    if mod is not None and getattr(mod, flag, False):
        return
    from arka.core import skill_registry_builtins

    skill_registry_builtins.register_all(registry)
    if mod is not None:
        setattr(mod, flag, True)
