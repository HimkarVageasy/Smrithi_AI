"""Meta Ad Library Connector — public rival creatives in India (<=50 sample, zero rank claims)."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from core.cache import CacheBackend, build_default_cache
from core.runner import ConnectorUnavailableError

AdArchiveFetcher = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _classify_format(raw_ad: dict[str, Any]) -> str:
    videos = raw_ad.get("ad_creative_link_captions") or []
    bodies = raw_ad.get("ad_creative_bodies") or []
    titles = raw_ad.get("ad_creative_link_titles") or []
    media_hint = str(raw_ad.get("media_type") or raw_ad.get("publisher_platforms") or "").lower()
    if "video" in media_hint or "reel" in media_hint:
        return "Video / Reels"
    if isinstance(titles, list) and len(titles) > 1:
        return "Carousel / Multi-Card"
    if videos or bodies:
        return "Static / Feed"
    return "Unspecified Creative"


class MetaAdLibraryCollector:
    """Read-Only Meta Ad Library (`ads_archive`) sampler enforcing Rule F2 (<=50 ads, zero rank)."""

    MAX_SAMPLE: int = 50
    ARCHIVE_URL: str = "https://graph.facebook.com/v21.0/ads_archive"
    RULE_F2_CAVEAT: str = (
        "From a sample of up to 50 active ads in Meta Ad Library (IN); public archive contains "
        "zero spend, impression, or conversion metrics—rival ads are never ranked by performance."
    )

    def __init__(
        self,
        *,
        access_token: str | None = None,
        cache: CacheBackend | None = None,
        archive_fetcher: AdArchiveFetcher | None = None,
    ) -> None:
        self._access_token = (access_token or os.getenv("META_ACCESS_TOKEN", "")).strip()
        self._cache = cache or build_default_cache()
        self._archive_fetcher = archive_fetcher

    async def search_active_rival_ads(
        self,
        query_terms: list[str],
        country: str = "IN",
    ) -> dict[str, Any]:
        """Fetch up to 50 active public ads for category terms and summarize formats/hooks."""
        cleaned_terms = [t.strip() for t in query_terms if t.strip()]
        search_str = " ".join(cleaned_terms) or "senior care health devices"
        cache_key = f"meta_ad_lib:{country.upper()}:{search_str.lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        params: dict[str, Any] = {
            "search_terms": search_str,
            "ad_reached_countries": f'["{country.upper()}"]',
            "ad_active_status": "ACTIVE",
            "ad_type": "ALL",
            "fields": (
                "page_name,ad_creative_bodies,ad_creative_link_titles,"
                "ad_creative_link_captions,publisher_platforms,ad_delivery_start_time"
            ),
            "limit": self.MAX_SAMPLE,
        }

        if self._archive_fetcher is not None:
            raw_payload = await self._archive_fetcher(params)
        else:
            if not self._access_token:
                raise ConnectorUnavailableError("META_ACCESS_TOKEN not configured for Ad Library")
            async with httpx.AsyncClient(timeout=7.0) as client:
                resp = await client.get(
                    self.ARCHIVE_URL,
                    params={**params, "access_token": self._access_token},
                )
                resp.raise_for_status()
                raw_payload = resp.json()

        raw_ads = (raw_payload.get("data") or [])[: self.MAX_SAMPLE]
        format_counts: Counter[str] = Counter()
        advertiser_counts: Counter[str] = Counter()
        sample_creatives: list[dict[str, Any]] = []

        for ad in raw_ads:
            page_name = str(ad.get("page_name") or "Unknown Advertiser")
            fmt = _classify_format(ad)
            format_counts[fmt] += 1
            advertiser_counts[page_name] += 1

            bodies = ad.get("ad_creative_bodies") or []
            titles = ad.get("ad_creative_link_titles") or []
            hook_text = str(bodies[0] if bodies else (titles[0] if titles else "")).strip()
            if len(sample_creatives) < 8 and (hook_text or page_name):
                sample_creatives.append(
                    {
                        "advertiser": page_name,
                        "format": fmt,
                        "headline": str(titles[0]).strip()[:90] if titles else "",
                        "hook_snippet": hook_text[:140],
                    }
                )

        bundle = {
            "search_terms": search_str,
            "country": country.upper(),
            "sampled_count": len(raw_ads),
            "max_sample_cap": self.MAX_SAMPLE,
            "format_mix": dict(format_counts),
            "top_active_advertisers": dict(advertiser_counts.most_common(6)),
            "sample_creatives": sample_creatives,
            "caveat": self.RULE_F2_CAVEAT,
        }
        self._cache.set(cache_key, bundle)
        return bundle
