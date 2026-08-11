"""Process-scoped fetch deduplication — TTL cache plus in-flight singleflight."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def fetch_dedup_enabled() -> bool:
    return os.environ.get("ARKA_FETCH_DEDUP", "1").strip().lower() not in {"0", "false", "no", "off"}


class _Inflight:
    __slots__ = ("event", "result", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class FetchDedupCache:
    """TTL cache with singleflight for concurrent identical fetches."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._inflight: dict[str, _Inflight] = {}

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._inflight.clear()

    def get_or_fetch(
        self,
        key: str,
        fetch: Callable[[], T],
        *,
        ttl: float,
        force: bool = False,
    ) -> T:
        if not fetch_dedup_enabled():
            return fetch()

        now = time.time()
        leader: _Inflight | None = None
        waiter: _Inflight | None = None

        with self._lock:
            if not force:
                hit = self._cache.get(key)
                if hit is not None and now - hit[0] < ttl:
                    return hit[1]
            existing = self._inflight.get(key)
            if existing is not None:
                waiter = existing
            else:
                leader = _Inflight()
                self._inflight[key] = leader

        if waiter is not None:
            waiter.event.wait()
            if waiter.error is not None:
                raise waiter.error
            return waiter.result

        assert leader is not None
        try:
            result = fetch()
        except BaseException as exc:
            with self._lock:
                inflight = self._inflight.pop(key, None)
                if inflight is not None:
                    inflight.error = exc
                    inflight.event.set()
            raise

        stamped = time.time()
        with self._lock:
            if ttl > 0:
                self._cache[key] = (stamped, result)
            inflight = self._inflight.pop(key, None)
            if inflight is not None:
                inflight.result = result
                inflight.event.set()
        return result

    def singleflight(self, key: str, fetch: Callable[[], T]) -> T:
        """Coalesce concurrent fetches without retaining results."""
        return self.get_or_fetch(key, fetch, ttl=0, force=False)


_registry: dict[str, FetchDedupCache] = {}
_registry_lock = threading.Lock()


def get_cache(name: str = "default") -> FetchDedupCache:
    with _registry_lock:
        cache = _registry.get(name)
        if cache is None:
            cache = FetchDedupCache()
            _registry[name] = cache
        return cache


def reset_caches() -> None:
    with _registry_lock:
        for cache in _registry.values():
            cache.clear()
