"""Default domain registry wiring so `core/` remains 100% domain-agnostic."""

from __future__ import annotations

from domains.base import DomainRegistry
from domains.performance_marketing.plugin import PerformanceMarketingPlugin


def build_default_registry() -> DomainRegistry:
    """Instantiate and register all enabled business domain plugins."""
    registry = DomainRegistry()
    registry.register(PerformanceMarketingPlugin(), is_default=True)
    return registry
