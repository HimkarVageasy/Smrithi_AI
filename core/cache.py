"""Stateless in-memory TTL cache backend (`AGENTS.md` §2.6 — zero local disk state)."""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from typing import Any, Protocol


class CacheBackend(Protocol):
    """Pluggable stateless cache contract (in-memory Phase 1; Firestore/Redis at scale)."""

    def get(self, key: str) -> Any | None:
        """Return cached value if present and unexpired, else None."""
        ...

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        """Store value with bounded TTL in seconds."""
        ...


class InMemoryTTLCache:
    """Bounded LRU + TTL RAM cache safe for ephemeral Cloud Run container instances."""

    def __init__(
        self,
        *,
        default_ttl_seconds: int = 300,
        max_entries: int = 256,
    ) -> None:
        if default_ttl_seconds <= 0:
            raise ValueError("default_ttl_seconds must be positive.")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive.")
        self._default_ttl = default_ttl_seconds
        self._max_entries = max_entries
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return payload

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        if ttl <= 0:
            return
        expires_at = time.monotonic() + ttl
        self._store[key] = (expires_at, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)


def build_default_cache() -> CacheBackend:
    """Construct stateless TTL cache from environment configuration."""
    raw_ttl = os.getenv("SMRITI_CACHE_TTL_SECONDS", "300").strip()
    ttl_val = int(raw_ttl) if raw_ttl.isdigit() and int(raw_ttl) > 0 else 300
    return InMemoryTTLCache(default_ttl_seconds=ttl_val)
