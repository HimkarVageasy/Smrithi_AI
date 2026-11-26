"""Meta Ads Account Connector — locked strictly Read-Only to Account 774668588585301."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from core.cache import CacheBackend, build_default_cache
from core.runner import ConnectorUnavailableError
from domains.performance_marketing.math_engine import compute_cpc, compute_cpm, compute_ctr_pct

MetaGraphGetCallable = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class MetaAccountScopeViolation(PermissionError):
    """Raised if any code attempts to query an ad account other than 774668588585301."""


def reconcile_regional_spend_f3(
    regional_rows: list[dict[str, Any]],
    account_monthly_spend: float,
    *,
    tolerance_ratio: float = 0.01,
) -> tuple[list[dict[str, Any]], str | None]:
    """Enforce Rule F3: discard regional breakdown if sum != account monthly total."""
    if not regional_rows:
        return [], None
    regional_sum = sum(float(r.get("spend") or 0.0) for r in regional_rows)
    if account_monthly_spend <= 0:
        if regional_sum > 0:
            return [], "Regional spend sum mismatched zero account total; discarded per Rule F3."
        return regional_rows, None

    rel_diff = abs(regional_sum - account_monthly_spend) / account_monthly_spend
    if rel_diff > tolerance_ratio:
        return (
            [],
            f"Regional spend breakdown discarded per Rule F3: regional sum ({regional_sum:.0f}) "
            f"!= account monthly total ({account_monthly_spend:.0f}).",
        )
    return regional_rows, None


class MetaAdsAccountCollector:
    """Strictly Read-Only Meta Marketing API collector locked to 774668588585301."""

    ALLOWED_ACCOUNT_ID: str = "774668588585301"
    GRAPH_BASE_URL: str = "https://graph.facebook.com/v21.0"

    def __init__(
        self,
        *,
        account_id: str = ALLOWED_ACCOUNT_ID,
        access_token: str | None = None,
        cache: CacheBackend | None = None,
        graph_get: MetaGraphGetCallable | None = None,
    ) -> None:
        cleaned_acct = account_id.strip().removeprefix("act_")
        if cleaned_acct != self.ALLOWED_ACCOUNT_ID:
            raise MetaAccountScopeViolation(
                f"Meta account '{account_id}' is forbidden; locked strictly to "
                f"{self.ALLOWED_ACCOUNT_ID}."
            )
        self._account_id = self.ALLOWED_ACCOUNT_ID
        self._access_token = (access_token or os.getenv("META_ACCESS_TOKEN", "")).strip()
        self._cache = cache or build_default_cache()
        self._graph_get = graph_get

    async def _get_graph_edge(self, edge: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._graph_get is not None:
            return await self._graph_get(edge, params)

        if not self._access_token:
            raise ConnectorUnavailableError("META_ACCESS_TOKEN not configured")

        full_params = {**params, "access_token": self._access_token}
        url = f"{self.GRAPH_BASE_URL}/act_{self._account_id}/{edge.lstrip('/')}"
        async with httpx.AsyncClient(timeout=7.0) as client:
            resp = await client.get(url, params=full_params)
            resp.raise_for_status()
            return resp.json()

    async def fetch_live_ads_and_opportunity_score(
        self,
        family_keyword: str | None = None,
    ) -> dict[str, Any]:
        """Fetch live campaigns, active ad CTR/CPC/CPM, and Opportunity Score (zero ROAS/Rev)."""
        kw_norm = (family_keyword or "").strip().lower()
        cache_key = f"meta_live:{self._account_id}:{kw_norm or 'ALL'}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        campaigns_task = self._get_graph_edge(
            "campaigns",
            {
                "fields": "id,name,effective_status,daily_budget,objective",
                "limit": 50,
            },
        )
        insights_task = self._get_graph_edge(
            "insights",
            {
                "level": "ad",
                "date_preset": "last_7d",
                "fields": "ad_id,ad_name,campaign_name,spend,impressions,clicks",
                "limit": 50,
            },
        )
        recs_task = self._get_graph_edge(
            "recommendations",
            {"fields": "title,message,importance,opportunity_score_lift"},
        )

        camp_res, ins_res, rec_res = await asyncio.gather(
            campaigns_task, insights_task, recs_task, return_exceptions=True
        )
        if isinstance(camp_res, Exception):
            raise camp_res
        if isinstance(ins_res, Exception):
            raise ins_res

        raw_campaigns = camp_res.get("data", []) if isinstance(camp_res, dict) else []
        campaigns: list[dict[str, Any]] = []
        for c in raw_campaigns:
            c_name = str(c.get("name") or "")
            if kw_norm and kw_norm not in c_name.lower():
                continue
            # Meta daily_budget is returned in minor currency units (paise -> / 100)
            raw_budget = c.get("daily_budget")
            daily_budget_inr = round(float(raw_budget) / 100.0, 2) if raw_budget else None
            campaigns.append(
                {
                    "campaign_id": str(c.get("id") or ""),
                    "campaign_name": c_name,
                    "effective_status": str(c.get("effective_status") or "UNKNOWN"),
                    "daily_budget_inr": daily_budget_inr,
                    "objective": str(c.get("objective") or ""),
                }
            )

        raw_insights = ins_res.get("data", []) if isinstance(ins_res, dict) else []
        active_ads: list[dict[str, Any]] = []
        for ad in raw_insights:
            c_name = str(ad.get("campaign_name") or "")
            ad_name = str(ad.get("ad_name") or "")
            if kw_norm and kw_norm not in c_name.lower() and kw_norm not in ad_name.lower():
                continue
            spend = float(ad.get("spend") or 0.0)
            impressions = int(ad.get("impressions") or 0)
            clicks = int(ad.get("clicks") or 0)
            cpm_val = compute_cpm(spend, impressions) if spend > 0 and impressions > 0 else None
            active_ads.append(
                {
                    "ad_name": ad_name,
                    "campaign_name": c_name,
                    "spend_inr": round(spend, 2),
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr_pct": compute_ctr_pct(clicks, impressions),
                    "cpc_inr": compute_cpc(spend, clicks),
                    "cpm_inr": cpm_val,
                }
            )
        active_ads.sort(key=lambda r: r["spend_inr"], reverse=True)

        recommendations: list[dict[str, Any]] = []
        if isinstance(rec_res, dict):
            for rec in rec_res.get("data", [])[:5]:
                recommendations.append(
                    {
                        "title": str(rec.get("title") or ""),
                        "importance": str(rec.get("importance") or ""),
                        "score_lift": rec.get("opportunity_score_lift"),
                    }
                )

        bundle = {
            "account_id": self._account_id,
            "date_window_ist": "Last 7 Days IST (Live Delivery Pulse)",
            "campaigns": campaigns[:15],
            "active_ads": active_ads[:15],
            "recommendations": recommendations,
        }
        self._cache.set(cache_key, bundle)
        return bundle
