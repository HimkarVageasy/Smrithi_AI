"""Pluggable multi-domain contract and registry (`DomainPlugin`)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core.schemas import SmritiQueryResponse


@runtime_checkable
class DomainPlugin(Protocol):
    """Standard interface implemented by every business domain pack."""

    domain_id: str

    def check_known_refusal(self, parsed_intent: dict[str, Any]) -> str | None:
        """Return immediate <1s polite refusal + valid alternative if query hits a Known Refusal."""
        ...

    async def collect_parallel(self, parsed_intent: dict[str, Any]) -> dict[str, Any]:
        """Dispatch domain connectors concurrently with per-connector timeouts."""
        ...

    def compute_verified_metrics(
        self,
        parsed_intent: dict[str, Any],
        raw_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        """Pure Python arithmetic: ratios, deltas, feasibility checks, and budget allocations."""
        ...

    async def render_response(self, verified_payload: dict[str, Any]) -> SmritiQueryResponse:
        """Render verified numbers into executive Markdown with mandatory citations."""
        ...


class DomainRegistry:
    """In-memory registry mapping domain IDs to active DomainPlugin instances."""

    def __init__(self) -> None:
        self._plugins: dict[str, DomainPlugin] = {}
        self._default_domain_id: str | None = None

    def register(self, plugin: DomainPlugin, *, is_default: bool = False) -> None:
        domain_id = plugin.domain_id.strip()
        if not domain_id:
            raise ValueError("DomainPlugin.domain_id must be a non-empty string.")
        self._plugins[domain_id] = plugin
        if is_default or self._default_domain_id is None:
            self._default_domain_id = domain_id

    @property
    def default_domain_id(self) -> str | None:
        return self._default_domain_id

    def list_domains(self) -> list[str]:
        return sorted(self._plugins.keys())

    def resolve(
        self,
        requested_domain: str | None,
        *,
        fallback_default: str | None = None,
    ) -> DomainPlugin:
        target = (requested_domain or fallback_default or self._default_domain_id or "").strip()
        if not target or target not in self._plugins:
            available = ", ".join(self.list_domains()) or "none"
            raise KeyError(f"Unknown domain '{target}'. Available domains: {available}")
        return self._plugins[target]
