"""Domain-agnostic parallel task runner with strict <=8s timeouts and circuit breakers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

MAX_CONNECTOR_TIMEOUT_SECONDS: float = 8.0


class ConnectorUnavailableError(RuntimeError):
    """Raised by a non-critical live connector when credentials or upstream are unavailable."""


@dataclass(frozen=True)
class CollectorTask:
    """Specification of a single concurrent data-collection unit."""

    name: str
    coro_factory: Callable[[], Awaitable[Any]]
    critical: bool = False
    timeout_seconds: float = MAX_CONNECTOR_TIMEOUT_SECONDS


@dataclass
class ParallelRunResult:
    """Aggregated results, per-task latencies, and non-critical degraded sources."""

    results: dict[str, Any] = field(default_factory=dict)
    degraded_sources: list[str] = field(default_factory=list)
    durations_ms: dict[str, int] = field(default_factory=dict)


async def _run_single_task(
    task: CollectorTask,
) -> tuple[str, Any, int, Exception | None]:
    effective_timeout = min(max(0.05, task.timeout_seconds), MAX_CONNECTOR_TIMEOUT_SECONDS)
    started_ns = time.perf_counter_ns()
    try:
        value = await asyncio.wait_for(task.coro_factory(), timeout=effective_timeout)
        elapsed_ms = max(0, (time.perf_counter_ns() - started_ns) // 1_000_000)
        return task.name, value, elapsed_ms, None
    except Exception as exc:
        elapsed_ms = max(0, (time.perf_counter_ns() - started_ns) // 1_000_000)
        return task.name, None, elapsed_ms, exc


async def run_with_timeouts(tasks: Sequence[CollectorTask]) -> ParallelRunResult:
    """Execute independent collector coroutines concurrently via asyncio.gather."""
    if not tasks:
        return ParallelRunResult()

    outcomes = await asyncio.gather(*(_run_single_task(t) for t in tasks))
    task_by_name = {t.name: t for t in tasks}
    bundle = ParallelRunResult()

    for name, value, elapsed_ms, exc in outcomes:
        bundle.durations_ms[name] = elapsed_ms
        if exc is None:
            bundle.results[name] = value
            continue

        spec = task_by_name[name]
        if spec.critical:
            raise exc

        bundle.results[name] = None
        if isinstance(exc, TimeoutError):
            bundle.degraded_sources.append(f"{name} (timed out > {spec.timeout_seconds:.1f}s)")
        elif isinstance(exc, ConnectorUnavailableError):
            bundle.degraded_sources.append(f"{name} ({exc})")
        else:
            bundle.degraded_sources.append(f"{name} ({type(exc).__name__})")

    return bundle
