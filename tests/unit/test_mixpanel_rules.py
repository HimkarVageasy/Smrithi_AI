"""Offline unit tests for Mixpanel M1..M6 rules & date cutoffs (`LOW_LEVEL_DESIGN.md` §7)."""

from __future__ import annotations

from datetime import date

import pytest

from domains.performance_marketing.collectors.mixpanel_live import (
    MixpanelLiveCollector,
    MixpanelRuleViolation,
    PaidChannelFilter,
    compute_cross_source_cvr,
)


@pytest.mark.parametrize(
    "forbidden_event",
    ["Purchase", "Order Placed", "product_purchase", "mp_order_complete", "Revenue"],
)
def test_blocks_forbidden_purchase_and_revenue_events(forbidden_event: str) -> None:
    collector = MixpanelLiveCollector(project_id="1", username="u", secret="s")
    with pytest.raises(MixpanelRuleViolation, match="forbidden"):
        collector.assert_event_allowed(forbidden_event)


@pytest.mark.asyncio
async def test_clips_start_date_to_2026_02_24_and_splits_checkout_cutoff_2026_09_18() -> None:
    calls: list[tuple[str, date, date, str | None]] = []

    async def _fake_fetcher(
        step: str,
        start: date,
        end: date,
        sku: str | None,
        channel: PaidChannelFilter,
    ) -> int:
        calls.append((step, start, end, sku))
        if step == MixpanelLiveCollector.STEP_PRODUCT_VIEW:
            return 500
        if step == MixpanelLiveCollector.STEP_BEGIN_CHECKOUT:
            return 100
        return 60

    collector = MixpanelLiveCollector(step_fetcher=_fake_fetcher)
    # Request spans BOTH 2026-02-24 min start AND 2026-09-18 checkout cutoff across 2 SKUs
    res = await collector.fetch_3step_funnel(
        ["AENB200103", "AENB200104"],
        start=date(2026, 2, 1),
        end=date(2026, 10, 15),
    )

    # 2 SKUs x 3 steps = 6 parallel 1-SKU-per-call fetches (Rule M4)
    assert len(calls) == 6
    assert res["product_page_views"] == 1000
    assert res["begin_checkout"] == 200
    assert res["payment_options_reached"] == 120
    assert res["view_to_checkout_rate"] == "20.00%"
    assert res["checkout_to_payment_rate"] == "60.00%"

    # Verify Product Page View clipped to 2026-02-24, while checkout steps started 2026-09-19!
    view_starts = {c[1] for c in calls if c[0] == MixpanelLiveCollector.STEP_PRODUCT_VIEW}
    chk_starts = {c[1] for c in calls if c[0] == MixpanelLiveCollector.STEP_BEGIN_CHECKOUT}
    assert view_starts == {date(2026, 2, 24)}
    assert chk_starts == {date(2026, 9, 19)}
    assert len(res["notes"]) == 2


@pytest.mark.asyncio
async def test_zero_sessions_never_prints_zero_percent() -> None:
    async def _zero_fetcher(
        step: str, start: date, end: date, sku: str | None, channel: PaidChannelFilter
    ) -> int:
        return 0

    collector = MixpanelLiveCollector(step_fetcher=_zero_fetcher)
    res = await collector.fetch_3step_funnel([], date(2026, 10, 1), date(2026, 10, 28))
    assert res["view_to_checkout_rate"] == "No sessions recorded in period"
    assert res["checkout_to_payment_rate"] == "No sessions recorded in period"


def test_cross_source_cvr_m6_labeling() -> None:
    cvr = compute_cross_source_cvr(bq_delivered_orders=50, mixpanel_paid_sessions=2_000)
    assert "Cross-source conversion" in cvr["label"]
    assert cvr["cvr_pct"] == 2.5

    zero = compute_cross_source_cvr(bq_delivered_orders=5, mixpanel_paid_sessions=0)
    assert zero["cvr_pct"] is None
    assert zero["display"] == "No sessions recorded in period"
