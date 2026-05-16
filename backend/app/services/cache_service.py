from __future__ import annotations

import copy
import time
from collections.abc import Callable
from threading import RLock
from typing import TypeVar

T = TypeVar("T")

_cache: dict[str, tuple[float, object]] = {}
_lock = RLock()


def get_or_set(key: str, ttl_seconds: int, factory: Callable[[], T]) -> T:
    now = time.monotonic()
    with _lock:
        item = _cache.get(key)
        if item and item[0] > now:
            return copy.deepcopy(item[1])  # type: ignore[return-value]

    value = factory()
    with _lock:
        _cache[key] = (now + ttl_seconds, copy.deepcopy(value))
    return value


def invalidate_client(client_id: int | None = None) -> None:
    with _lock:
        if client_id is None:
            _cache.clear()
            return
        prefix = f"client:{client_id}:"
        for key in list(_cache):
            if key.startswith(prefix):
                _cache.pop(key, None)
