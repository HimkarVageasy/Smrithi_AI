"""Sanitized Open-Web Competitor Benchmark Collector (`web_competitor.py`)."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from core.cache import CacheBackend, build_default_cache
from core.guardrails.output_audit import scrub_pii_text
from core.runner import ConnectorUnavailableError

WebSearchCallable = Callable[[str], Awaitable[list[dict[str, str]]]]


class WebCompetitorCollector:
    """Read-Only Google Programmable Search collector for public rival offer/pricing context."""

    SEARCH_URL: str = "https://www.googleapis.com/customsearch/v1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cx: str | None = None,
        cache: CacheBackend | None = None,
        search_fn: WebSearchCallable | None = None,
    ) -> None:
        self._api_key = (api_key or os.getenv("GOOGLE_SEARCH_API_KEY", "")).strip()
        self._cx = (cx or os.getenv("GOOGLE_SEARCH_CX", "")).strip()
        self._cache = cache or build_default_cache()
        self._search_fn = search_fn

    @property
    def is_configured(self) -> bool:
        return bool(self._search_fn is not None or (self._api_key and self._cx))

    async def fetch_market_context(self, product_query: str) -> dict[str, Any]:
        """Fetch sanitized public category/offer snippets (zero fabricated performance claims)."""
        query = f"{product_query.strip()} India senior care price offer"
        cache_key = f"web_comp:{query.lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        if self._search_fn is not None:
            raw_items = await self._search_fn(query)
        else:
            if not (self._api_key and self._cx):
                raise ConnectorUnavailableError("Google Custom Search key/cx not configured")
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(
                    self.SEARCH_URL,
                    params={"key": self._api_key, "cx": self._cx, "q": query, "num": 5},
                )
                resp.raise_for_status()
                raw_items = resp.json().get("items", [])

        snippets: list[dict[str, str]] = []
        for item in raw_items[:5]:
            title = scrub_pii_text(str(item.get("title") or "").strip())[:100]
            snippet = scrub_pii_text(str(item.get("snippet") or "").strip())[:160]
            link = str(item.get("link") or "").strip()
            if title or snippet:
                snippets.append({"title": title, "snippet": snippet, "url": link})

        bundle = {
            "query": query,
            "snippets": snippets,
            "note": "Public web offer/price context only; contains no internal conversion data.",
        }
        self._cache.set(cache_key, bundle)
        return bundle
