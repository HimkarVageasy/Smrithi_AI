"""Offline unit tests for Meta Ads, dormant Google Ads, and end-to-end Live Diagnostic."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.app import create_app
from domains.base import DomainRegistry
from domains.performance_marketing.collectors.bigquery_poc import (
    BigQueryPocCollector,
    QueryParamTuple,
)
from domains.performance_marketing.collectors.google_ads_account import GoogleAdsAccountCollector
from domains.performance_marketing.collectors.meta_ads_account import (
    MetaAccountScopeViolation,
    MetaAdsAccountCollector,
    reconcile_regional_spend_f3,
)
from domains.performance_marketing.collectors.mixpanel_live import (
    MixpanelLiveCollector,
    PaidChannelFilter,
)
from domains.performance_marketing.plugin import PerformanceMarketingPlugin


def test_meta_account_strictly_locked_to_774668588585301() -> None:
    with pytest.raises(MetaAccountScopeViolation):
        MetaAdsAccountCollector(account_id="1234567890")


def test_meta_rule_f3_regional_spend_reconciliation() -> None:
    rows = [{"region": "Delhi", "spend": 40_000}, {"region": "Maharashtra", "spend": 60_000}]
    kept, note = reconcile_regional_spend_f3(rows, account_monthly_spend=100_000)
    assert len(kept) == 2 and note is None

    discarded, mismatch_note = reconcile_regional_spend_f3(rows, account_monthly_spend=140_000)
    assert discarded == []
    assert mismatch_note is not None and "Rule F3" in mismatch_note


@pytest.mark.asyncio
async def test_meta_and_google_collectors_compute_python_delivery_metrics() -> None:
    async def _fake_meta_graph(edge: str, params: dict[str, Any]) -> dict[str, Any]:
        if edge == "campaigns":
            return {
                "data": [
                    {
                        "id": "c1",
                        "name": "Meta_Nebulizer_Scale",
                        "effective_status": "ACTIVE",
                        "daily_budget": "500000",  # Rs 5,000 in paise
                        "objective": "OUTCOME_SALES",
                    }
                ]
            }
        if edge == "insights":
            return {
                "data": [
                    {
                        "ad_id": "a1",
                        "ad_name": "SV_CoughAK",
                        "campaign_name": "Meta_Nebulizer_Scale",
                        "spend": "25000",
                        "impressions": "100000",
                        "clicks": "4480",
                    }
                ]
            }
        return {"data": [{"title": "Consolidate ad sets", "opportunity_score_lift": 6}]}

    meta = MetaAdsAccountCollector(graph_get=_fake_meta_graph)
    bundle = await meta.fetch_live_ads_and_opportunity_score("nebulizer")
    assert bundle["campaigns"][0]["daily_budget_inr"] == 5000.0
    ad = bundle["active_ads"][0]
    assert ad["ad_name"] == "SV_CoughAK"
    assert ad["ctr_pct"] == 4.48
    assert ad["cpm_inr"] == 250.0

    # Dormant by default
    g_dormant = GoogleAdsAccountCollector()
    assert g_dormant.is_enabled is False

    # Active when enabled=True
    async def _fake_gaql(cid: str, query: str) -> list[dict[str, Any]]:
        return [
            {
                "campaign": {
                    "id": "g1",
                    "name": "Search_Nebulizer_Exact",
                    "status": "ENABLED",
                    "advertisingChannelType": "SEARCH",
                },
                "campaignBudget": {"amountMicros": "3000000000"},
                "metrics": {
                    "impressions": "20000",
                    "clicks": "1200",
                    "costMicros": "18000000000",
                    "searchImpressionShare": 0.72,
                },
            }
        ]

    g_active = GoogleAdsAccountCollector(
        enabled=True, customer_id="123-456-7890", stream_executor=_fake_gaql
    )
    g_bundle = await g_active.fetch_live_campaigns_and_search_terms("nebulizer")
    assert g_bundle["campaigns"][0]["spend_inr"] == 18000.0
    assert g_bundle["campaigns"][0]["ctr_pct"] == 6.0
    assert g_bundle["campaigns"][0]["cpc_inr"] == 15.0


def _mock_bq_for_live() -> BigQueryPocCollector:
    async def _exec(sql: str, params: Sequence[QueryParamTuple]) -> list[dict[str, Any]]:
        if "ge_account_monthly" in sql.lower():
            return [
                {
                    "month": "2026-10-01",
                    "month_name": "Oct 2026",
                    "settle_state": "mostly settled",
                    "is_provisional": False,
                    "performance_spend": 3_610_177.0,
                    "net_revenue": 5_427_212.0,
                    "net_orders": 4253,
                }
            ]
        return [
            {
                "order_date": "2026-11-24",
                "gross_orders": 120,
                "net_orders": 90,
                "net_revenue": 135000.0,
            }
        ]

    return BigQueryPocCollector(query_executor=_exec)


def test_live_diagnostic_end_to_end_online_and_graceful_degradation() -> None:
    bq = _mock_bq_for_live()

    async def _mp_step(
        step: str, start: date, end: date, sku: str | None, channel: PaidChannelFilter
    ) -> int:
        return 4500 if step == MixpanelLiveCollector.STEP_PRODUCT_VIEW else 450

    async def _meta_edge(edge: str, params: dict[str, Any]) -> dict[str, Any]:
        if edge == "campaigns":
            return {"data": [{"id": "1", "name": "C1", "effective_status": "ACTIVE"}]}
        if edge == "insights":
            return {
                "data": [
                    {
                        "ad_name": "SI_NewPrice1299",
                        "campaign_name": "C1",
                        "spend": "12000",
                        "impressions": "50000",
                        "clicks": "1000",
                    }
                ]
            }
        return {"data": []}

    registry = DomainRegistry()
    registry.register(
        PerformanceMarketingPlugin(
            bq_collector=bq,
            mixpanel_collector=MixpanelLiveCollector(step_fetcher=_mp_step),
            meta_collector=MetaAdsAccountCollector(graph_get=_meta_edge),
            google_collector=GoogleAdsAccountCollector(enabled=False),
        ),
        is_default=True,
    )
    client = TestClient(create_app(registry=registry))

    ok_resp = client.post(
        "/v1/query",
        json={"question": "Show live Meta ads CTR and Mixpanel checkout funnel diagnostic"},
    )
    assert ok_resp.status_code == 200
    ok_body = ok_resp.json()
    assert ok_body["degraded_sources"] == []
    assert "Cross-source conversion" in ok_body["answer_markdown"]
    assert "`SI_NewPrice1299`" in ok_body["answer_markdown"]

    # Unconfigured Mixpanel & Meta -> graceful degradation, BigQuery still succeeds!
    deg_reg = DomainRegistry()
    deg_reg.register(
        PerformanceMarketingPlugin(
            bq_collector=bq,
            mixpanel_collector=MixpanelLiveCollector(project_id="", username="", secret=""),
            meta_collector=MetaAdsAccountCollector(access_token=""),
            google_collector=GoogleAdsAccountCollector(enabled=False),
        ),
        is_default=True,
    )
    deg_client = TestClient(create_app(registry=deg_reg))
    deg_resp = deg_client.post(
        "/v1/query",
        json={"question": "Show live Meta ads CTR and Mixpanel checkout funnel diagnostic"},
    )
    assert deg_resp.status_code == 200
    deg_body = deg_resp.json()
    assert len(deg_body["degraded_sources"]) == 2
    assert "Warehouse Financial Truth" in deg_body["answer_markdown"]
    assert "Graceful Degradation" in deg_body["answer_markdown"]
