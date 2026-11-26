"""Offline unit tests for `core/runner.py` parallel timeouts & `core/cache.py` TTL cache."""

from __future__ import annotations

import asyncio
import time

import pytest

from core.cache import InMemoryTTLCache
from core.runner import CollectorTask, ConnectorUnavailableError, run_with_timeouts


def test_in_memory_ttl_cache_hit_expiry_and_eviction() -> None:
    cache = InMemoryTTLCache(default_ttl_seconds=60, max_entries=2)
    cache.set("k1", {"v": 1})
    cache.set("k2", {"v": 2})
    assert cache.get("k1") == {"v": 1}  # Refreshes k1 LRU order

    cache.set("k3", {"v": 3})  # Evicts k2 (least recently used)
    assert cache.get("k2") is None
    assert cache.get("k1") == {"v": 1}
    assert cache.get("k3") == {"v": 3}

    # Short TTL expiration
    cache.set("short", "val", ttl_seconds=1)
    assert cache.get("short") == "val"


@pytest.mark.asyncio
async def test_parallel_runner_executes_concurrently_and_degrades_gracefully() -> None:
    async def _fast_ok(val: str) -> str:
        await asyncio.sleep(0.05)
        return val

    async def _slow_timeout() -> str:
        await asyncio.sleep(0.5)
        return "late"

    async def _missing_creds() -> str:
        raise ConnectorUnavailableError("token missing")

    started = time.perf_counter()
    res = await run_with_timeouts(
        [
            CollectorTask(name="bq", coro_factory=lambda: _fast_ok("bq_data"), critical=True),
            CollectorTask(name="fast2", coro_factory=lambda: _fast_ok("ok2"), critical=False),
            CollectorTask(
                name="slow_api",
                coro_factory=_slow_timeout,
                critical=False,
                timeout_seconds=0.08,
            ),
            CollectorTask(name="unconfigured_api", coro_factory=_missing_creds, critical=False),
        ]
    )
    elapsed = time.perf_counter() - started

    # Parallel execution finishes near max(0.05, 0.08)s rather than sequential sum
    assert elapsed < 0.25
    assert res.results["bq"] == "bq_data"
    assert res.results["fast2"] == "ok2"
    assert res.results["slow_api"] is None
    assert res.results["unconfigured_api"] is None
    assert len(res.degraded_sources) == 2
    assert any("slow_api" in s and "timed out" in s for s in res.degraded_sources)
    assert any("unconfigured_api" in s and "token missing" in s for s in res.degraded_sources)


@pytest.mark.asyncio
async def test_parallel_runner_propagates_critical_task_failure() -> None:
    async def _critical_boom() -> None:
        raise RuntimeError("warehouse unreachable")

    with pytest.raises(RuntimeError, match="warehouse unreachable"):
        await run_with_timeouts(
            [CollectorTask(name="bq", coro_factory=_critical_boom, critical=True)]
        )
