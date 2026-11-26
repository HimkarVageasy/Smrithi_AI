"""Google Ads Transparency Connector — public rival Search/YT/Display themes (zero rank claims)."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from core.cache import CacheBackend, build_default_cache
from core.runner import ConnectorUnavailableError

TransparencyFetcher = Callable[[str, str], Awaitable[list[dict[str, Any]]]]


class GoogleAdTransparencyCollector:
    """Read-Only rival Google Ads Transparency collector (dormant unless enabled/configured)."""

    HARD_CAVEAT: str = (
        "Public Google Ads Transparency data (IN) contains zero CPC, spend, or conversion "
        "metrics—active themes and formats are reported without performance ranking."
    )

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        endpoint_url: str | None = None,
        api_key: str | None = None,
        cache: CacheBackend | None = None,
        fetcher: TransparencyFetcher | None = None,
    ) -> None:
        raw_flag = os.getenv("GOOGLE_ADS_ENABLED", "false").strip().lower()
        self.is_enabled: bool = (
            enabled if enabled is not None else raw_flag in {"1", "true", "yes", "on"}
        )
        self._endpoint_url = (
            endpoint_url or os.getenv("GOOGLE_TRANSPARENCY_ENDPOINT", "")
        ).strip()
        self._api_key = (api_key or os.getenv("GOOGLE_TRANSPARENCY_API_KEY", "")).strip()
        self._cache = cache or build_default_cache()
        self._fetcher = fetcher

    async def search_active_rival_creatives(
        self,
        advertiser_or_keyword: str,
        region: str = "IN",
    ) -> dict[str, Any]:
        """Search public rival Search/YouTube/Display creatives (zero performance metrics)."""
        if not self.is_enabled and self._fetcher is None:
            raise ConnectorUnavailableError(
                "Google Ads Transparency disabled (GOOGLE_ADS_ENABLED=false)"
            )

        kw = advertiser_or_keyword.strip() or "health devices"
        cache_key = f"gads_transp:{region.upper()}:{kw.lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        if self._fetcher is not None:
            raw_items = await self._fetcher(kw, region.upper())
        else:
            if not (self._endpoint_url and self._api_key):
                raise ConnectorUnavailableError("Google Transparency endpoint not configured")
            async with httpx.AsyncClient(timeout=7.0) as client:
                resp = await client.get(
                    self._endpoint_url,
                    params={"q": kw, "region": region.upper(), "api_key": self._api_key},
                )
                resp.raise_for_status()
                raw_items = resp.json().get("creatives", [])

        capped = raw_items[:50]
        formats: Counter[str] = Counter()
        samples: list[dict[str, str]] = []
        for item in capped:
            fmt = str(item.get("format") or "TEXT / SEARCH")
            adv = str(item.get("advertiser") or "Unknown Advertiser")
            headline = str(item.get("headline") or item.get("title") or "").strip()
            formats[fmt] += 1
            if len(samples) < 8 and (headline or adv):
                samples.append(
                    {"advertiser": adv, "format": fmt, "headline": headline[:110]}
                )

        bundle = {
            "query": kw,
            "region": region.upper(),
            "sampled_count": len(capped),
            "format_mix": dict(formats),
            "sample_creatives": samples,
            "caveat": self.HARD_CAVEAT,
        }
        self._cache.set(cache_key, bundle)
        return bundle
