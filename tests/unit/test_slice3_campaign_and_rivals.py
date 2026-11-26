"""Offline unit tests for Slice 3: Golden Scenarios #3, #4, #5, and #6."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.app import create_app
from domains.base import DomainRegistry
from domains.performance_marketing.campaign_planner import (
    compute_campaign_strategy,
    extract_campaign_intake,
)
from domains.performance_marketing.collectors.bigquery_poc import (
    BigQueryPocCollector,
    QueryParamTuple,
)
from domains.performance_marketing.collectors.google_ad_transparency import (
    GoogleAdTransparencyCollector,
)
from domains.performance_marketing.collectors.google_ads_account import GoogleAdsAccountCollector
from domains.performance_marketing.collectors.meta_ad_library import MetaAdLibraryCollector
from domains.performance_marketing.collectors.meta_ads_account import MetaAdsAccountCollector
from domains.performance_marketing.collectors.mixpanel_live import (
    MixpanelLiveCollector,
    PaidChannelFilter,
)
from domains.performance_marketing.plugin import PerformanceMarketingPlugin


def _build_slice3_plugin(*, google_enabled: bool = False) -> PerformanceMarketingPlugin:
    async def _bq_exec(sql: str, params: Sequence[QueryParamTuple]) -> list[dict[str, Any]]:
        low = sql.lower()
        if "ge_family_monthly" in low:
            return [
                {
                    "month": "2026-08-01", "settle_state": "closed",
                    "product_family": "nebulizer", "spend": 50_000.0,
                    "net_revenue": 90_000.0, "net_orders": 60,
                },
                {
                    "month": "2026-09-01", "settle_state": "closed",
                    "product_family": "nebulizer", "spend": 55_000.0,
                    "net_revenue": 110_000.0, "net_orders": 70,
                },
                {
                    "month": "2026-10-01", "settle_state": "mostly settled",
                    "product_family": "nebulizer", "spend": 63_000.0,
                    "net_revenue": 126_000.0, "net_orders": 84,
                },
                {
                    "month": "2026-11-01", "settle_state": "provisional",
                    "product_family": "nebulizer", "spend": 40_000.0,
                    "net_revenue": 100_000.0, "net_orders": 65,
                },
            ]
        if "ge_account_closed_months" in low:
            return [
                {
                    "month": "2026-10-01",
                    "settle_state": "mostly settled",
                    "performance_spend": 3_610_177.0,
                    "net_revenue": 5_427_212.0,
                    "net_orders": 4253,
                }
            ]
        if "ge_product_demand_monthly" in low:
            return [
                {
                    "month": "2026-10-01", "catalogue_product": "Nebulizer",
                    "net_orders": 210, "gross_orders": 240, "net_revenue": 315_000.0,
                }
            ]
        return []

    async def _mp_step(
        step: str, start: date, end: date, sku: str | None, channel: PaidChannelFilter
    ) -> int:
        if step == MixpanelLiveCollector.STEP_PRODUCT_VIEW:
            return 12_000
        if step == MixpanelLiveCollector.STEP_BEGIN_CHECKOUT:
            return 1_500
        return 900

    async def _meta_live(edge: str, params: dict[str, Any]) -> dict[str, Any]:
        if edge == "campaigns":
            return {"data": [{"id": "1", "name": "Meta_Nebulizer", "effective_status": "ACTIVE"}]}
        if edge == "insights":
            return {
                "data": [
                    {
                        "ad_name": "SV_CoughAK", "campaign_name": "Meta_Nebulizer",
                        "spend": "18000", "impressions": "80000", "clicks": "3584",
                    }
                ]
            }
        return {"data": []}

    async def _meta_archive(params: dict[str, Any]) -> dict[str, Any]:
        # Generate 65 mock rival ads -> collector must cap at <= 50 (Rule F2)
        return {
            "data": [
                {
                    "page_name": f"RivalBrand_{i % 3}",
                    "media_type": "video" if i % 2 == 0 else "image",
                    "ad_creative_bodies": ["Fast winter steam & nebulizer relief at home"],
                    "ad_creative_link_titles": ["Portable Mesh Nebulizer"],
                }
                for i in range(65)
            ]
        }

    async def _google_transp(kw: str, region: str) -> list[dict[str, Any]]:
        return [
            {"advertiser": "Omron Healthcare", "format": "SEARCH", "headline": "Quiet Nebulizer"},
            {"advertiser": "Dr Trust", "format": "YOUTUBE", "headline": "Home Respiratory Care"},
        ]

    return PerformanceMarketingPlugin(
        bq_collector=BigQueryPocCollector(query_executor=_bq_exec),
        mixpanel_collector=MixpanelLiveCollector(step_fetcher=_mp_step),
        meta_collector=MetaAdsAccountCollector(graph_get=_meta_live),
        google_collector=GoogleAdsAccountCollector(enabled=google_enabled),
        meta_library_collector=MetaAdLibraryCollector(archive_fetcher=_meta_archive),
        google_transparency_collector=GoogleAdTransparencyCollector(
            enabled=google_enabled, fetcher=_google_transp
        ),
    )


def test_golden_3_and_5_winter_nebulizer_3l_plan_and_need_to_run_intent() -> None:
    reg = DomainRegistry()
    reg.register(_build_slice3_plugin(google_enabled=False), is_default=True)
    client = TestClient(create_app(registry=reg))

    for prompt in (
        "Plan a winter campaign for Nebulizer with Rs 3,00,000 for air quality season",
        "Need to run a winter campaign for Nebulizer with Rs 3,00,000",
    ):
        resp = client.post("/v1/query", json={"question": prompt})
        assert resp.status_code == 200
        md = resp.json()["answer_markdown"]

        # Exact 4.76x scale-up multiple (Rs 3,00,000 / Rs 63,000 Oct closed spend)
        assert "4.76x" in md
        assert "Rs 3,00,000" in md
        assert "100% Sum" in md
        assert "[Source: BigQuery" in md
        assert "[Source: Mixpanel" in md
        assert "from a sample of up to 50 active ads" in md
        assert "Please Confirm Before Execution" in md

    # Verify external premise tag on first prompt
    first_md = client.post(
        "/v1/query",
        json={"question": "Plan a winter campaign for Nebulizer with Rs 3,00,000 for air quality"},
    ).json()["answer_markdown"]
    assert "your premise, not our data" in first_md


def test_golden_4_unrealistic_6x_roas_feasibility_pushback() -> None:
    reg = DomainRegistry()
    reg.register(_build_slice3_plugin(google_enabled=False), is_default=True)
    client = TestClient(create_app(registry=reg))

    resp = client.post(
        "/v1/query",
        json={
            "question": "Plan a winter campaign for Nebulizer with Rs 3,00,000 targeting 6.0x ROAS"
        },
    )
    assert resp.status_code == 200
    md = resp.json()["answer_markdown"]
    assert "FEASIBILITY PUSHBACK" in md
    assert "6.00x" in md


def test_golden_6_rival_ad_library_audit_caps_50_and_never_ranks() -> None:
    reg = DomainRegistry()
    reg.register(_build_slice3_plugin(google_enabled=True), is_default=True)
    client = TestClient(create_app(registry=reg))

    resp = client.post(
        "/v1/query",
        json={
            "question": (
                "Audit active competitor ads for Nebulizer across Meta Ad Library "
                "and Google Ads Transparency"
            )
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    md = body["answer_markdown"]
    assert "50 active ads found" in md
    assert "from a sample of up to 50 active ads" in md
    assert "Google Ads Transparency Snapshot" in md


@pytest.mark.parametrize("odd_budget", [137_779, 300_000, 999_999])
@pytest.mark.parametrize("google_on", [False, True])
def test_budget_phasing_sums_strictly_to_exact_rupee_for_any_budget(
    odd_budget: int,
    google_on: bool,
) -> None:
    intake = extract_campaign_intake(
        f"Plan a campaign for Nebulizer with Rs {odd_budget}",
        today_ist=date(2026, 11, 26),
        matched_product="nebulizer",
    )
    strat = compute_campaign_strategy(
        intake,
        family_rows=[],
        closed_account_rows=[],
        today_ist=date(2026, 11, 26),
        google_ads_enabled=google_on,
    )
    plan = strat["phased_plan"]
    allocated = sum(r.amount_inr for r in plan.rows if r.funnel_stage != "A/B Test Arm")
    assert allocated == odd_budget
