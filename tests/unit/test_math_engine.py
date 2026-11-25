"""Offline unit tests for deterministic Python math engine (`math_engine.py`)."""

from __future__ import annotations

import pytest

from domains.performance_marketing.math_engine import (
    MathIntegrityError,
    build_reversal_aware_summary,
    compute_cpc,
    compute_cpm,
    compute_ctr_pct,
    compute_net_cac,
    compute_net_roas,
    compute_period_delta,
    filter_part_month_rows,
    format_inr,
)


def test_sum_over_sum_roas_never_averages_row_ratios() -> None:
    # Month 1: Rev 10,000 / Spend 2,000 = 5.0x
    # Month 2: Rev 100,000 / Spend 100,000 = 1.0x
    # Wrong naive average = 3.0x; True SUM/SUM = 110,000 / 102,000 = 1.0784x
    true_roas = compute_net_roas(10_000 + 100_000, 2_000 + 100_000)
    assert true_roas == 1.0784


def test_brand_spend_strictly_rejected_in_roas_and_cac() -> None:
    with pytest.raises(MathIntegrityError, match="Brand awareness spend"):
        compute_net_roas(500_000, 200_000, includes_brand_spend=True)

    with pytest.raises(MathIntegrityError, match="Brand awareness spend"):
        compute_net_cac(200_000, 250, includes_brand_spend=True)


def test_cpm_formula_and_rule9_lower_bound() -> None:
    assert compute_cpm(25_000, 100_000) == 250.0
    # Missing * 1000 bug simulation (e.g. spend=5, impressions=10,000 -> 0.5 < 1.0)
    with pytest.raises(MathIntegrityError, match="CPM"):
        compute_cpm(5.0, 10_000)


def test_ctr_and_cpc_zero_safe() -> None:
    assert compute_ctr_pct(1_500, 100_000) == 1.5
    assert compute_ctr_pct(0, 0) is None
    assert compute_cpc(18_000, 1_000) == 18.0
    assert compute_cpc(18_000, 0) is None


def test_period_delta_enforces_under_5_percent_flat_rule() -> None:
    flat_delta = compute_period_delta(104.2, 100.0, grain="MoM")
    assert flat_delta.direction == "flat"
    assert flat_delta.pct_change == 4.2

    up_delta = compute_period_delta(112.0, 100.0, grain="WoW")
    assert up_delta.direction == "up"
    assert up_delta.pct_change == 12.0

    down_delta = compute_period_delta(85.0, 100.0, grain="DoD")
    assert down_delta.direction == "down"
    assert down_delta.pct_change == -15.0


def test_reversal_aware_summary_under_25_words() -> None:
    # Rose Aug -> Sep (2.0 -> 2.6), then reversed down in Oct (2.6 -> 2.1)
    sentence = build_reversal_aware_summary("Net ROAS", [2.0, 2.6, 2.1])
    assert "up" in sentence and "reversed down" in sentence
    assert len(sentence.split()) < 25


def test_part_month_day_clipping() -> None:
    rows = [
        {"dt": "2026-10-05", "spend": 1000},
        {"dt": "2026-10-15", "spend": 1200},
        {"dt": "2026-10-25", "spend": 1500},
        {"dt": "2026-11-10", "spend": 1100},
    ]
    clipped = filter_part_month_rows(rows, date_key="dt", cutoff_day=15)
    assert len(clipped) == 3
    assert all(r["dt"] != "2026-10-25" for r in clipped)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "Rs 0"),
        (950, "Rs 950"),
        (12_500, "Rs 12,500"),
        (300_000, "Rs 3,00,000"),
        (12_34_567, "Rs 12,34,567"),
        (1_00_00_000, "Rs 1,00,00,000"),
        (-1_20_000, "-Rs 1,20,000"),
    ],
)
def test_indian_rupee_formatting(amount: int, expected: str) -> None:
    assert format_inr(amount) == expected
