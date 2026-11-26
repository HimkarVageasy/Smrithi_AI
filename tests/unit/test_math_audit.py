"""Offline unit tests for Gate #2 cross-table reconciliation auditor (`math_audit.py`)."""

from __future__ import annotations

import logging
from datetime import date

import pytest

from core.guardrails.math_audit import (
    audit_additive_total,
    audit_funnel_monotonicity,
    audit_rate_bounds,
    audit_window_subset_bound,
)
from domains.performance_marketing.live_presenter import render_live_diagnostic_report


def test_window_subset_and_funnel_monotonicity_primitives() -> None:
    assert audit_window_subset_bound(3_258, 7_124).ok is True
    bad_sub = audit_window_subset_bound(8_316, 7_124)
    assert bad_sub.ok is False and "8316" in (bad_sub.reason or "")

    assert audit_funnel_monotonicity([159_932, 16_994, 10_209]).ok is True
    bad_funnel = audit_funnel_monotonicity([10_000, 16_994, 10_209])
    assert bad_funnel.ok is False and "exceeds prior step" in (bad_funnel.reason or "")


def test_additive_total_and_rate_bounds() -> None:
    assert audit_additive_total([36_10_177.0, 6_36_930.0], 42_47_107.0).ok is True
    assert audit_additive_total([300_000.0, 50_000.0], 500_000.0).ok is False

    assert audit_rate_bounds(250.0, min_value=1.0).ok is True
    assert audit_rate_bounds(0.45, min_value=1.0).ok is False
    assert audit_rate_bounds(125.0, min_value=0.0, max_value=100.0).ok is False


def test_live_diagnostic_catches_8316_vs_7124_mismatch_and_withholds_bad_cvr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    account_rows = [
        {
            "month": "2026-10-01",
            "month_name": "October 2026",
            "settle_state": "mostly settled",
            "is_provisional": False,
            "performance_spend": 3_610_177.0,
            "net_revenue": 5_427_212.0,
            "net_orders": 4_253,
        },
        {
            "month": "2026-11-01",
            "month_name": "November 2026",
            "settle_state": "provisional",
            "is_provisional": True,
            "performance_spend": 2_036_550.0,
            "net_revenue": 3_582_695.0,
            "net_orders": 2_871,
        },
    ]
    mixpanel_bundle = {
        "effective_window_ist": "2026-10-29 – 2026-11-25 IST",
        "product_page_views": 159_932,
        "begin_checkout": 16_994,
        "payment_options_reached": 10_209,
        "view_to_checkout_rate": "10.63%",
        "checkout_to_payment_rate": "60.07%",
        "notes": [],
    }

    # Case 1: Unfiltered 8,316 (> Oct 4,253 + Nov 2,871 = 7,124) -> withheld + structured log!
    with caplog.at_level(logging.WARNING, logger="smriti.guardrails.math_audit"):
        bad_resp = render_live_diagnostic_report(
            account_rows=account_rows,
            recent_daily_orders=[{"order_date": "2026-11-24", "net_orders": 8_316}],
            mixpanel_bundle=mixpanel_bundle,
            meta_bundle=None,
            google_bundle=None,
            degraded_sources=[],
            product_family=None,
            today_ist=date(2026, 11, 26),
            trace_id="trace-audit-8316",
        )

    assert "5.20%" not in bad_resp.answer_markdown
    assert "Reconciliation Warning: source scope mismatch detected" in bad_resp.answer_markdown
    assert any(
        "RECONCILIATION_MISMATCH" in rec.message and "trace-audit-8316" in rec.message
        for rec in caplog.records
    )

    # Case 2: Reconciled 3,258 (<= 7,124 and <= 16,994) -> renders verified 2.04% CVR cleanly!
    ok_resp = render_live_diagnostic_report(
        account_rows=account_rows,
        recent_daily_orders=[{"order_date": "2026-11-24", "net_orders": 3_258}],
        mixpanel_bundle=mixpanel_bundle,
        meta_bundle=None,
        google_bundle=None,
        degraded_sources=[],
        product_family=None,
        today_ist=date(2026, 11, 26),
        trace_id="trace-ok-3258",
    )
    assert "2.04%" in ok_resp.answer_markdown
    assert "Reconciliation Warning" not in ok_resp.answer_markdown
