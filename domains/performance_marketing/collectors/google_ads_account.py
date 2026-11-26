"""Google Ads Account Connector — Read-Only SearchStream (dormant when GOOGLE_ADS_ENABLED=false)."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from core.cache import CacheBackend, build_default_cache
from core.runner import ConnectorUnavailableError
from domains.performance_marketing.math_engine import compute_cpc, compute_ctr_pct

GoogleAdsStreamCallable = Callable[[str, str], Awaitable[list[dict[str, Any]]]]


def _is_truthy(val: str | None) -> bool:
    return bool(val and val.strip().lower() in {"1", "true", "yes", "on"})


class GoogleAdsAccountCollector:
    """Read-Only Google Ads collector (Search/PMax/YouTube); dormant until enabled."""

    API_BASE_URL: str = "https://googleads.googleapis.com/v18"

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        customer_id: str | None = None,
        developer_token: str | None = None,
        access_token: str | None = None,
        cache: CacheBackend | None = None,
        stream_executor: GoogleAdsStreamCallable | None = None,
    ) -> None:
        self.is_enabled: bool = (
            enabled if enabled is not None else _is_truthy(os.getenv("GOOGLE_ADS_ENABLED"))
        )
        raw_cid = (customer_id or os.getenv("GOOGLE_ADS_CUSTOMER_ID", "")).replace("-", "").strip()
        self._customer_id = raw_cid
        self._developer_token = (
            developer_token or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
        ).strip()
        self._access_token = (access_token or os.getenv("GOOGLE_ADS_ACCESS_TOKEN", "")).strip()
        self._cache = cache or build_default_cache()
        self._stream_executor = stream_executor

    async def _run_gaql(self, gaql_query: str) -> list[dict[str, Any]]:
        if not self.is_enabled:
            raise ConnectorUnavailableError(
                "Google Ads connector disabled (GOOGLE_ADS_ENABLED=false)"
            )

        if self._stream_executor is not None:
            return await self._stream_executor(self._customer_id, gaql_query)

        if not (self._customer_id and self._developer_token and self._access_token):
            raise ConnectorUnavailableError("Google Ads credentials not configured")

        url = f"{self.API_BASE_URL}/customers/{self._customer_id}/googleAds:searchStream"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "developer-token": self._developer_token,
        }
        async with httpx.AsyncClient(timeout=7.0) as client:
            resp = await client.post(url, json={"query": gaql_query}, headers=headers)
            resp.raise_for_status()
            batches = resp.json()

        rows: list[dict[str, Any]] = []
        if isinstance(batches, list):
            for batch in batches:
                if isinstance(batch, dict):
                    rows.extend(batch.get("results", []))
        return rows

    async def fetch_live_campaigns_and_search_terms(
        self,
        product_keyword: str | None = None,
    ) -> dict[str, Any]:
        """Fetch live Search/PMax/YouTube CTR, CPC, Spend & Search Terms (zero ROAS/Revenue)."""
        kw_norm = (product_keyword or "").strip().lower()
        cache_key = f"gads_live:{self._customer_id}:{kw_norm or 'ALL'}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        campaign_gaql = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type,
            campaign_budget.amount_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.search_impression_share
        FROM campaign
        WHERE segments.date DURING LAST_7_DAYS
        """
        raw_rows = await self._run_gaql(campaign_gaql)

        campaigns: list[dict[str, Any]] = []
        for item in raw_rows:
            camp = item.get("campaign", {})
            budget = item.get("campaignBudget", {})
            metrics = item.get("metrics", {})
            name = str(camp.get("name") or "")
            if kw_norm and kw_norm not in name.lower():
                continue

            spend_inr = float(metrics.get("costMicros") or 0) / 1_000_000.0
            budget_inr = (
                float(budget.get("amountMicros") or 0) / 1_000_000.0
                if budget.get("amountMicros") is not None
                else None
            )
            impressions = int(metrics.get("impressions") or 0)
            clicks = int(metrics.get("clicks") or 0)

            campaigns.append(
                {
                    "campaign_name": name,
                    "status": str(camp.get("status") or "UNKNOWN"),
                    "channel_type": str(camp.get("advertisingChannelType") or ""),
                    "daily_budget_inr": round(budget_inr, 2) if budget_inr is not None else None,
                    "spend_inr": round(spend_inr, 2),
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr_pct": compute_ctr_pct(clicks, impressions),
                    "cpc_inr": compute_cpc(spend_inr, clicks),
                    "impression_share": metrics.get("searchImpressionShare"),
                }
            )

        campaigns.sort(key=lambda r: r["spend_inr"], reverse=True)
        bundle = {
            "customer_id": self._customer_id,
            "date_window_ist": "Last 7 Days IST (Live Google Ads Pulse)",
            "campaigns": campaigns[:15],
        }
        self._cache.set(cache_key, bundle)
        return bundle
