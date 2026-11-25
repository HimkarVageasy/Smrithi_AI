"""Unit tests for core and performance_marketing Pydantic v2 schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.schemas import SmritiQueryRequest
from domains.performance_marketing.schemas import BudgetPhaseRow, PhasedBudgetPlan


def test_query_request_rejects_single_char_question() -> None:
    with pytest.raises(ValidationError):
        SmritiQueryRequest(question="a")


def test_phased_budget_plan_enforces_exact_100_percent_sum() -> None:
    plan = PhasedBudgetPlan(
        total_budget_inr=300_000,
        scale_multiple_vs_last_closed=4.76,
        rows=[
            BudgetPhaseRow(
                phase_name="Phase 1 — Validation",
                channel="Meta Ads",
                funnel_stage="Prospecting (80%)",
                amount_inr=168_000,
                daily_run_rate_inr=12_000,
                date_range="1 Dec – 14 Dec 2026",
                scale_condition="Hold CPC <= Rs 18 and CTR >= 1.5%",
            ),
            BudgetPhaseRow(
                phase_name="Phase 1 — Validation",
                channel="Meta Ads",
                funnel_stage="Retargeting (20%)",
                amount_inr=42_000,
                daily_run_rate_inr=3_000,
                date_range="1 Dec – 14 Dec 2026",
                scale_condition="7-day product viewers + checkout starters",
            ),
            BudgetPhaseRow(
                phase_name="Phase 2 — High-Intent Capture",
                channel="Google Ads",
                funnel_stage="Prospecting (80%)",
                amount_inr=72_000,
                daily_run_rate_inr=2_400,
                date_range="1 Dec – 30 Dec 2026",
                scale_condition="Exact/Phrase respiratory search terms",
            ),
            BudgetPhaseRow(
                phase_name="Phase 2 — High-Intent Capture",
                channel="Google Ads",
                funnel_stage="Retargeting (20%)",
                amount_inr=18_000,
                daily_run_rate_inr=600,
                date_range="1 Dec – 30 Dec 2026",
                scale_condition="Returning non-purchasers",
            ),
            BudgetPhaseRow(
                phase_name="14-Day Creative Holdout",
                channel="Meta Ads",
                funnel_stage="A/B Test Arm",
                amount_inr=30_000,
                daily_run_rate_inr=2_143,
                date_range="1 Dec – 14 Dec 2026",
                scale_condition="Carved inside Phase 1 prospecting (non-additive)",
            ),
        ],
    )
    assert plan.total_budget_inr == 300_000


def test_phased_budget_plan_rejects_mismatched_allocation() -> None:
    with pytest.raises(ValidationError, match="Allocated Rs 250000 != Total Budget Rs 300000"):
        PhasedBudgetPlan(
            total_budget_inr=300_000,
            scale_multiple_vs_last_closed=4.76,
            rows=[
                BudgetPhaseRow(
                    phase_name="Phase 1",
                    channel="Meta Ads",
                    funnel_stage="Prospecting (80%)",
                    amount_inr=250_000,
                    daily_run_rate_inr=8_333,
                    date_range="1 Dec – 30 Dec 2026",
                    scale_condition="Baseline",
                )
            ],
        )
