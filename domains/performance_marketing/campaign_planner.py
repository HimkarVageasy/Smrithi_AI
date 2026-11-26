"""Deterministic Campaign Strategist, Feasibility Pushback & 100%-Sum Phased Budget Engine."""

from __future__ import annotations

from datetime import date
from statistics import median
from typing import Any

from core.guardrails.math_audit import audit_additive_total
from domains.performance_marketing.intake_extractor import extract_campaign_intake
from domains.performance_marketing.math_engine import compute_net_cac, compute_net_roas
from domains.performance_marketing.rules import classify_month_settlement
from domains.performance_marketing.schemas import (
    BudgetPhaseRow,
    CampaignPlanIntake,
    PhasedBudgetPlan,
)

__all__ = ["compute_campaign_strategy", "extract_campaign_intake"]


def _split_80_20(phase_budget: int) -> tuple[int, int]:
    prospecting = int(round(phase_budget * 0.80))
    retargeting = phase_budget - prospecting
    return prospecting, retargeting


def _build_phased_plan(
    budget_inr: int,
    *,
    scale_multiple: float | None,
    google_ads_enabled: bool,
) -> PhasedBudgetPlan:
    rows: list[BudgetPhaseRow] = []

    if google_ads_enabled:
        meta_total = int(round(budget_inr * 0.70))
        google_total = budget_inr - meta_total
        p1 = int(round(meta_total * 0.30))
        p2 = int(round(meta_total * 0.35))
        p3 = meta_total - p1 - p2
        meta_phases = [
            ("Phase 1 — Hook Validation", p1, 10, "Days 1–10", "Hold CTR >= 1.5% & CPC <= P50"),
            ("Phase 2 — Winner Consolidation", p2, 10, "Days 11–20", "Checkout rate >= sitewide"),
            ("Phase 3 — Peak Scale", p3, 10, "Days 21–30", "Hold blended CAC <= target band"),
        ]
        for p_name, amt, days, d_range, cond in meta_phases:
            prosp, retarg = _split_80_20(amt)
            rows.append(
                BudgetPhaseRow(
                    phase_name=p_name, channel="Meta Ads", funnel_stage="Prospecting (80%)",
                    amount_inr=prosp, daily_run_rate_inr=max(1, round(prosp / days)),
                    date_range=d_range, scale_condition=cond,
                )
            )
            rows.append(
                BudgetPhaseRow(
                    phase_name=p_name, channel="Meta Ads", funnel_stage="Retargeting (20%)",
                    amount_inr=retarg, daily_run_rate_inr=max(1, round(retarg / days)),
                    date_range=d_range, scale_condition="7d viewers + checkout abandoners",
                )
            )
        g_prosp, g_retarg = _split_80_20(google_total)
        rows.append(
            BudgetPhaseRow(
                phase_name="Always-On High-Intent Capture", channel="Google Ads",
                funnel_stage="Prospecting (80%)", amount_inr=g_prosp,
                daily_run_rate_inr=max(1, round(g_prosp / 30)), date_range="Days 1–30",
                scale_condition="Exact/Phrase category search terms",
            )
        )
        rows.append(
            BudgetPhaseRow(
                phase_name="Always-On High-Intent Capture", channel="Google Ads",
                funnel_stage="Retargeting (20%)", amount_inr=g_retarg,
                daily_run_rate_inr=max(1, round(g_retarg / 30)), date_range="Days 1–30",
                scale_condition="Returning site visitors",
            )
        )
    else:
        p1 = int(round(budget_inr * 0.25))
        p2 = int(round(budget_inr * 0.35))
        p3 = budget_inr - p1 - p2
        meta_only_phases = [
            (
                "Phase 1 — Creative & Hook Validation",
                p1, 10, "Days 1–10", "CTR >= 1.5% & CPC check",
            ),
            ("Phase 2 — Guided Ramp", p2, 10, "Days 11–20", "Mixpanel checkout >= baseline"),
            ("Phase 3 — Peak Scale", p3, 10, "Days 21–30", "Placed-order CAC within P75 band"),
        ]
        for p_name, amt, days, d_range, cond in meta_only_phases:
            prosp, retarg = _split_80_20(amt)
            rows.append(
                BudgetPhaseRow(
                    phase_name=p_name, channel="Meta Ads", funnel_stage="Prospecting (80%)",
                    amount_inr=prosp, daily_run_rate_inr=max(1, round(prosp / days)),
                    date_range=d_range, scale_condition=cond,
                )
            )
            rows.append(
                BudgetPhaseRow(
                    phase_name=p_name, channel="Meta Ads", funnel_stage="Retargeting (20%)",
                    amount_inr=retarg, daily_run_rate_inr=max(1, round(retarg / days)),
                    date_range=d_range, scale_condition="7d product viewers + checkout starters",
                )
            )

    ab_arm = max(1_000, int(round(budget_inr * 0.10)))
    rows.append(
        BudgetPhaseRow(
            phase_name="14-Day Creative Holdout (Carved Inside Phase 1)",
            channel="Meta Ads",
            funnel_stage="A/B Test Arm",
            amount_inr=ab_arm,
            daily_run_rate_inr=max(1, round(ab_arm / 14)),
            date_range="Days 1–14",
            scale_condition="50/50 split: Problem-Hook Reels vs Doctor/Demo Static (non-additive)",
        )
    )

    plan = PhasedBudgetPlan(
        total_budget_inr=budget_inr,
        scale_multiple_vs_last_closed=scale_multiple,
        rows=rows,
    )
    allocated_parts = [float(r.amount_inr) for r in plan.rows if r.funnel_stage != "A/B Test Arm"]
    chk = audit_additive_total(allocated_parts, float(budget_inr), abs_tolerance=0.0)
    if not chk.ok:
        raise ValueError(f"Budget audit failed: {chk.reason}")
    return plan


def compute_campaign_strategy(
    intake: CampaignPlanIntake,
    *,
    family_rows: list[dict[str, Any]],
    closed_account_rows: list[dict[str, Any]],
    today_ist: date,
    google_ads_enabled: bool = False,
) -> dict[str, Any]:
    """Compute historical P50/P75 baseline, scale multiple, feasibility pushback, and Rs plan."""
    closed_fam = [
        r for r in family_rows
        if classify_month_settlement(
            date.fromisoformat(str(r["month"])[:10]),
            today_ist=today_ist,
            warehouse_status=r.get("settle_state"),
        ) != "provisional"
    ]

    roas_points: list[float] = []
    cac_points: list[float] = []
    last_closed_spend: float | None = None
    baseline_source = f"Ad-Family `{intake.product_query}` (`ge_family_monthly`)"

    if closed_fam:
        sorted_fam = sorted(closed_fam, key=lambda x: str(x["month"]))
        last_closed_spend = float(sorted_fam[-1].get("spend") or 0.0)
        for r in sorted_fam:
            rv = compute_net_roas(float(r.get("net_revenue") or 0.0), float(r.get("spend") or 0.0))
            cv = compute_net_cac(float(r.get("spend") or 0.0), int(r.get("net_orders") or 0))
            if rv is not None:
                roas_points.append(rv)
            if cv is not None:
                cac_points.append(cv)
    else:
        baseline_source = "Account Closed-Month Baseline (`ge_account_closed_months` fallback)"
        for r in closed_account_rows[-3:]:
            sp = float(r.get("performance_spend") or 0.0)
            rv = compute_net_roas(float(r.get("net_revenue") or 0.0), sp)
            cv = compute_net_cac(sp, int(r.get("net_orders") or 0))
            if rv is not None:
                roas_points.append(rv)
            if cv is not None:
                cac_points.append(cv)

    p50_roas = round(float(median(roas_points)), 2) if roas_points else 1.50
    sorted_roas = sorted(roas_points)
    p75_roas = (
        round(sorted_roas[min(len(sorted_roas) - 1, int(len(sorted_roas) * 0.75))], 2)
        if sorted_roas
        else 1.75
    )
    p50_cac = round(float(median(cac_points)), 2) if cac_points else 800.0

    scale_mult = (
        round(intake.budget_inr / last_closed_spend, 2)
        if (last_closed_spend and last_closed_spend > 0)
        else None
    )
    effective_target_roas = intake.target_roas if intake.target_roas is not None else p50_roas

    feasibility_ceiling = round(max(p75_roas * 1.25, p75_roas + 0.40), 2)
    is_feasible = True
    if intake.target_roas is not None and intake.target_roas > feasibility_ceiling:
        is_feasible = False
        verdict = (
            f"FEASIBILITY PUSHBACK — Target `{intake.target_roas:.2f}x` Net ROAS exceeds "
            f"historical closed-month P50 (`{p50_roas:.2f}x`) / P75 (`{p75_roas:.2f}x`). "
            f"Recommended realistic target band: `{p50_roas:.2f}x – {p75_roas:.2f}x`."
        )
    elif scale_mult is not None and scale_mult > 3.0:
        verdict = (
            f"CONDITIONAL GO — Planned budget is `{scale_mult:.2f}x` last closed-month family "
            f"spend; gated 3-phase ramp mandatory to protect `{effective_target_roas:.2f}x` ROAS."
        )
    else:
        verdict = (
            f"GO — Target `{effective_target_roas:.2f}x` Net ROAS aligns with closed-month "
            f"historical P50 (`{p50_roas:.2f}x`) / P75 (`{p75_roas:.2f}x`)."
        )

    phased_plan = _build_phased_plan(
        intake.budget_inr,
        scale_multiple=scale_mult,
        google_ads_enabled=google_ads_enabled,
    )
    return {
        "intake": intake,
        "baseline_source": baseline_source,
        "last_closed_spend_inr": last_closed_spend,
        "scale_multiple": scale_mult,
        "p50_roas": p50_roas,
        "p75_roas": p75_roas,
        "p50_cac_inr": p50_cac,
        "effective_target_roas": effective_target_roas,
        "is_target_feasible": is_feasible,
        "verdict": verdict,
        "phased_plan": phased_plan,
    }
