"""Offline unit tests for `<1s` Known Refusals & settlement rules (`rules.py`)."""

from __future__ import annotations

import time
from datetime import date

import pytest

from domains.performance_marketing.rules import (
    check_marketing_known_refusal,
    classify_month_settlement,
)


@pytest.mark.parametrize(
    ("prompt", "expected_snippet"),
    [
        ("Show me delivered ROAS by product for last 3 months", "Product/SKU-Level ROAS"),
        ("What is our SKU-level CAC for AENB200103?", "Product/SKU-Level ROAS"),
        ("Give me Delhi ROAS for October 2026", "City/State-Level ROAS"),
        ("What is our city-wise CAC across India?", "City/State-Level ROAS"),
        ("What was yesterday's net ROAS?", "Daily Net ROAS"),
        ("Show DoD delivered CAC for this week", "Daily Net ROAS"),
        ("What is the ROAS of our brand awareness campaign?", "Brand Campaign ROAS"),
        ("Pull historical creative-level CPM from BigQuery warehouse", "Creative-Level Historical"),
        ("Pause all active ads in Meta right now", "Read-Only Guardrail"),
        ("Increase the daily budget on Nebulizer campaign", "Read-Only Guardrail"),
    ],
)
def test_known_refusals_intercept_in_under_10ms(prompt: str, expected_snippet: str) -> None:
    started = time.perf_counter()
    refusal = check_marketing_known_refusal(prompt)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    assert refusal is not None
    assert expected_snippet in refusal
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
def test_valid_queries_and_planning_prompts_are_not_falsely_refused(valid_prompt: str) -> None:
    assert check_marketing_known_refusal(valid_prompt) is None


def test_month_settlement_classification_rules() -> None:
    # Current month is always provisional
    assert (
        classify_month_settlement(date(2026, 11, 1), today_ist=date(2026, 11, 25)) == "provisional"
    )
    # Previous month before 20th -> settling
    assert (
        classify_month_settlement(date(2026, 10, 1), today_ist=date(2026, 11, 12)) == "settling"
    )
    # Previous month on/after 20th -> mostly settled; ratios can still move
    assert (
        classify_month_settlement(date(2026, 10, 1), today_ist=date(2026, 11, 25))
        == "mostly settled; ratios can still move"
    )
    # 2+ months back -> closed
    assert classify_month_settlement(date(2026, 9, 1), today_ist=date(2026, 11, 25)) == "closed"
