"""Exhaustive natural-language routing, entity synonym, INR budget, and section numbering tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.app import create_app
from core.router import extract_time_spec
from domains.base import DomainRegistry
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
from domains.performance_marketing.intake_extractor import extract_campaign_intake
from domains.performance_marketing.intent_parser import parse_marketing_query
from domains.performance_marketing.plugin import PerformanceMarketingPlugin
from domains.performance_marketing.rules import (
    check_marketing_known_refusal,
    detect_grain_boundary_caveat,
)


@pytest.mark.parametrize(
    ("prompt", "expected_family", "expected_catalogue", "expected_budget", "expected_city"),
    [
        (
            "plan an ad campaign for this winter for adult diaper pants "
            "with budget of rupees 4 lakhs",
            "diaper",
            "diaper",
            400_000,
            None,
        ),
        (
            "Plan a winter campaign for Nebuliser with four lakh rupees",
            "nebulizer",
            "nebulizer",
            400_000,
            None,
        ),
        (
            "How should we spend 2.5L on BP machines in Bengaluru next month?",
            "healthmonitors",
            "bp monitor",
            250_000,
            "BANGALORE",
        ),
        (
            "Propose a Meta ad strategy for mini massage gun "
            "with two and a half lakhs in Delhi NCR",
            "massagegun",
            "massage gun",
            250_000,
            "DELHI",
        ),
        (
            "We want to promote sugar sensors across India "
            "with 5,00,000 rupees targeting 2.0x ROAS",
            "glucosesensor",
            "cgm",
            500_000,
            None,
        ),
        (
            "Draft a festive campaign for walking canes in Gurugram, budget: 150000",
            "walking stick",
            "walking stick",
            150_000,
            "GURGAON",
        ),
        (
            "Create an ad campaign for cervical pillows with 75k budget and max CAC under Rs 600",
            "pillow",
            "pillow",
            75_000,
            None,
        ),
        (
            "Where should we invest rupees 1.2 crore for all products this Diwali?",
            "allproducts",
            None,
            12_000_000,
            None,
        ),
        (
            "Rs 3,50,000 for knee braces in Mumbai",
            "knee",
            "knee",
            350_000,
            "MUMBAI",
        ),
        (
            "Set a budget of fifty thousand rupees to launch a campaign for bunion correctors",
            "bunion",
            "bunion",
            50_000,
            None,
        ),
    ],
)
def test_diverse_campaign_planning_phrasings_route_and_extract_accurately(
    prompt: str,
    expected_family: str,
    expected_catalogue: str | None,
    expected_budget: int,
    expected_city: str | None,
) -> None:
    assert check_marketing_known_refusal(prompt) is None
    assert detect_grain_boundary_caveat(prompt) is None

    routed = parse_marketing_query(prompt)
    assert routed.focus == "campaign_plan"
    assert routed.product_family == expected_family
    assert routed.catalogue_product == expected_catalogue
    assert routed.city == expected_city

    intake = extract_campaign_intake(
        prompt,
        today_ist=date(2026, 11, 26),
        matched_product=routed.product_family,
        matched_city=routed.city,
    )
    assert intake.budget_inr == expected_budget
    assert intake.product_query == expected_family


@pytest.mark.parametrize(
    ("prompt", "expected_focus"),
    [
        ("What ads are Friends and Dignity running for adult diapers?", "competitor_intel"),
        ("Check Facebook Ad Library for rival nebuliser hooks", "competitor_intel"),
        ("Who else is advertising massage guns right now?", "competitor_intel"),
        ("Where are users dropping off in checkout on the website?", "live_diagnostic"),
        ("Check cart abandonment and product page views in Mixpanel", "live_diagnostic"),
        ("How are our running ads performing in Meta Ads Manager?", "live_diagnostic"),
        ("What is the ROAS for adult diaper pants over the last three months?", "family_focus"),
        ("Suggest why Nebulizer ROAS dropped last month", "family_focus"),
        ("Which ad families had spend above Rs 1 lakh last month?", "account_and_family_mom"),
        ("Show top-selling products by delivered orders", "product_or_city_demand"),
        ("Delivered orders by catalogue product for past 4 months", "product_or_city_demand"),
        ("Show orders for the last seven days", "daily_or_weekly_orders"),
        ("What is the ROAS for Nebulizer in Delhi?", "city_roas_hybrid"),
        ("Break down CAC by individual product SKU", "product_roas_hybrid"),
        ("Day-wise delivered ROAS for the last 7 days", "daily_roas_hybrid"),
    ],
)
def test_non_planning_natural_phrasings_route_without_false_positives(
    prompt: str,
    expected_focus: str,
) -> None:
    assert check_marketing_known_refusal(prompt) is None
    routed = parse_marketing_query(prompt)
    assert routed.focus == expected_focus


def test_catalogue_product_phrase_never_collides_with_catalogue_ad_family() -> None:
    routed = parse_marketing_query("Show delivered orders by catalogue product")
    assert routed.focus == "product_or_city_demand"
    assert routed.product_family is None


def test_word_number_time_window_extraction() -> None:
    spec_m = extract_time_spec("Show MoM trend for the last six closed months")
    assert spec_m.grain == "MoM"
    assert spec_m.window_count == 6

    spec_d = extract_time_spec("Show orders for the past ten days")
    assert spec_d.grain == "DoD"
    assert spec_d.window_count == 10


def test_diaper_4_lakh_e2e_plan_and_sequential_section_numbering_on_degradation() -> None:
    async def _bq_exec(sql: str, params: Sequence[QueryParamTuple]) -> list[dict[str, Any]]:
        low = sql.lower()
        if "ge_family_monthly" in low:
            return [
                {
                    "month": "2026-09-01",
                    "settle_state": "closed",
                    "product_family": "diaper",
                    "spend": 100_000.0,
                    "net_revenue": 190_000.0,
                    "net_orders": 380,
                },
                {
                    "month": "2026-10-01",
                    "settle_state": "mostly settled",
                    "product_family": "diaper",
                    "spend": 125_000.0,
                    "net_revenue": 225_000.0,
                    "net_orders": 450,
                },
            ]
        if "ge_product_demand_monthly" in low:
            return [
                {
                    "month": "2026-10-01",
                    "catalogue_product": "Diaper",
                    "net_orders": 1_181,
                    "gross_orders": 1_320,
                    "net_revenue": 578_328.0,
                }
            ]
        return []

    async def _mp_step(
        step: str, start: date, end: date, sku: str | None, channel: PaidChannelFilter
    ) -> int:
        return 10_000 if step == MixpanelLiveCollector.STEP_PRODUCT_VIEW else 1_200

    # Meta Live & Ad Library unconfigured so Section 5 is omitted -> headings must be 1..5!
    plugin = PerformanceMarketingPlugin(
        bq_collector=BigQueryPocCollector(query_executor=_bq_exec),
        mixpanel_collector=MixpanelLiveCollector(step_fetcher=_mp_step),
        meta_collector=MetaAdsAccountCollector(access_token=""),
        google_collector=GoogleAdsAccountCollector(enabled=False),
        meta_library_collector=MetaAdLibraryCollector(access_token=""),
        google_transparency_collector=GoogleAdTransparencyCollector(enabled=False),
    )
    reg = DomainRegistry()
    reg.register(plugin, is_default=True)
    client = TestClient(create_app(registry=reg))

    resp = client.post(
        "/v1/query",
        json={
            "question": (
                "plan an ad campaign for this winter for adult diaper pants "
                "with budget of rupees 4 lakhs"
            )
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "Campaign Brief · diaper · Rs 4,00,000" in body["headline"]
    md = body["answer_markdown"]
    assert "#### 1. Verdict & Intake Scope" in md
    assert "#### 2. Historical Warehouse Baseline" in md
    assert "#### 3. Website Funnel Health" in md
    assert "#### 4. Phased Channel & Funnel Budget Allocation" in md
    assert "#### 5. Key Risks & Confirmation Questions" in md
    assert "#### 6." not in md
    assert "Rs 4,00,000" in md
    assert "3.20x" in md  # 4,00,000 / 1,25,000 Oct diaper spend
