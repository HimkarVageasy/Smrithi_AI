"""Offline unit tests for `<1s` Known Refusals, grain caveats, and settlement rules (`rules.py`)."""

from __future__ import annotations

import time
from datetime import date

import pytest

from domains.performance_marketing.rules import (
    check_marketing_known_refusal,
    classify_month_settlement,
    detect_grain_boundary_caveat,
)


@pytest.mark.parametrize(
    ("prompt", "expected_snippet"),
    [
        ("What is the ROAS of our brand awareness campaign?", "Brand Campaign ROAS"),
        ("Pull historical creative-level CPM from BigQuery warehouse", "Creative-Level Historical"),
        ("Pause all active ads in Meta right now", "Read-Only Guardrail"),
        ("Increase the daily budget on Nebulizer campaign", "Read-Only Guardrail"),
    ],
)
def test_hard_known_refusals_intercept_in_under_10ms(prompt: str, expected_snippet: str) -> None:
    started = time.perf_counter()
    refusal = check_marketing_known_refusal(prompt)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    assert refusal is not None
    assert expected_snippet in refusal
    assert elapsed_ms < 10.0


@pytest.mark.parametrize(
    ("prompt", "expected_kind", "expected_snippet"),
    [
        (
            "Show a Month-on-Month trend for the last 3 months (including the current month) "
            "for total Spend, Placed Orders, Delivered Orders, and Delivered ROAS by product.",
            "product_roas",
            "Catalogue Product / SKU-Level Spend & ROAS Not Computable",
        ),
        (
            "What is our SKU-level CAC for AENB200103?",
            "product_roas",
            "Ad-Family",
        ),
        (
            "Give me Delhi ROAS for October 2026",
            "city_roas",
            "City / State-Level ROAS & CAC Not Computable",
        ),
        (
            "What is our city-wise CAC across India?",
            "city_roas",
            "City Placed & Delivered Demand",
        ),
        (
            "What was yesterday's net ROAS?",
            "daily_net_roas",
            "Single-Day Net Delivered ROAS",
        ),
        (
            "Show DoD delivered CAC for this week",
            "daily_net_roas",
            "Monthly Account Net ROAS",
        ),
    ],
)
def test_grain_boundary_queries_allow_valid_tables_and_attach_caveat(
    prompt: str,
    expected_kind: str,
    expected_snippet: str,
) -> None:
    # Must NOT hard-block valid tables
    assert check_marketing_known_refusal(prompt) is None

    started = time.perf_counter()
    caveat = detect_grain_boundary_caveat(prompt)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    assert caveat is not None
    assert caveat.kind == expected_kind
    assert expected_snippet in caveat.explanation_markdown
    assert elapsed_ms < 10.0


@pytest.mark.parametrize(
    "valid_prompt",
    [
        "Need to run a winter campaign for Nebulizer with Rs 3,00,000",
        "Plan a Rs 3,00,000 campaign for Nebulizer in Delhi targeting 2.5x ROAS",
        "Show 3-month MoM account and ad-family ROAS trend",
        "What is Nebulizer ROAS over the last 3 closed months?",
        "Show daily spend and CTR DoD for Meta account",
    ],
)
def test_clean_queries_and_planning_prompts_have_neither_refusal_nor_caveat(
    valid_prompt: str,
) -> None:
    assert check_marketing_known_refusal(valid_prompt) is None
    assert detect_grain_boundary_caveat(valid_prompt) is None


def test_month_settlement_classification_rules() -> None:
    assert (
        classify_month_settlement(date(2026, 11, 1), today_ist=date(2026, 11, 25)) == "provisional"
    )
    assert (
        classify_month_settlement(date(2026, 10, 1), today_ist=date(2026, 11, 12)) == "settling"
    )
    assert (
        classify_month_settlement(date(2026, 10, 1), today_ist=date(2026, 11, 25))
        == "mostly settled; ratios can still move"
    )
    assert classify_month_settlement(date(2026, 9, 1), today_ist=date(2026, 11, 25)) == "closed"
