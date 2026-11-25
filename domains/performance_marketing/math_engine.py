"""Deterministic Python math engine for Performance Marketing (`AGENTS.md` §2.1 & §3)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

DirectionLabel = Literal["up", "down", "flat"]
TimeGrain = Literal["DoD", "WoW", "MoM", "YoY"]


class MathIntegrityError(ValueError):
    """Raised when an input violates mathematical or accounting invariants."""


@dataclass(frozen=True)
class PeriodDelta:
    """Verified arithmetic comparison between two time windows."""

    grain: TimeGrain
    current_value: float
    previous_value: float
    absolute_change: float
    pct_change: float | None
    direction: DirectionLabel


def compute_net_roas(
    sum_delivered_revenue: float,
    sum_perf_spend: float,
    *,
    includes_brand_spend: bool = False,
) -> float | None:
    """Compute SUM(delivered_revenue) / SUM(performance_spend); never average ratios."""
    if includes_brand_spend:
        raise MathIntegrityError("Brand awareness spend must never enter Net ROAS denominator.")
    if sum_delivered_revenue < 0 or sum_perf_spend < 0:
        raise MathIntegrityError("Revenue and performance spend must be non-negative.")
    if sum_perf_spend == 0:
        return None
    return round(sum_delivered_revenue / sum_perf_spend, 4)


def compute_net_cac(
    sum_perf_spend: float,
    sum_delivered_orders: int,
    *,
    includes_brand_spend: bool = False,
) -> float | None:
    """Compute SUM(performance_spend) / SUM(delivered_orders); never average ratios."""
    if includes_brand_spend:
        raise MathIntegrityError("Brand awareness spend must never enter Net CAC numerator.")
    if sum_perf_spend < 0 or sum_delivered_orders < 0:
        raise MathIntegrityError("Performance spend and delivered orders must be non-negative.")
    if sum_delivered_orders == 0:
        return None
    return round(sum_perf_spend / sum_delivered_orders, 2)


def compute_cpm(sum_spend: float, sum_impressions: int) -> float | None:
    """Compute SUM(spend) / SUM(impressions) * 1000 and assert CPM >= 1.0 (Rule #9)."""
    if sum_spend < 0 or sum_impressions < 0:
        raise MathIntegrityError("Spend and impressions must be non-negative.")
    if sum_impressions == 0 or sum_spend == 0:
        return None
    cpm = (sum_spend / sum_impressions) * 1000.0
    if cpm < 1.0:
        raise MathIntegrityError(
            f"Computed CPM ({cpm:.4f}) < 1.0; check missing * 1000 or corrupt impression units."
        )
    return round(cpm, 2)


def compute_ctr_pct(sum_clicks: int, sum_impressions: int) -> float | None:
    """Compute click-through rate percentage (0..100 scale)."""
    if sum_clicks < 0 or sum_impressions < 0:
        raise MathIntegrityError("Clicks and impressions must be non-negative.")
    if sum_impressions == 0:
        return None
    return round((sum_clicks / sum_impressions) * 100.0, 2)


def compute_cpc(sum_spend: float, sum_clicks: int) -> float | None:
    """Compute cost per click in INR."""
    if sum_spend < 0 or sum_clicks < 0:
        raise MathIntegrityError("Spend and clicks must be non-negative.")
    if sum_clicks == 0:
        return None
    return round(sum_spend / sum_clicks, 2)


def compute_period_delta(
    current_value: float,
    previous_value: float,
    *,
    grain: TimeGrain,
    flat_threshold_pct: float = 5.0,
) -> PeriodDelta:
    """Compute exact delta, % change, and <5% 'flat' classification."""
    abs_change = round(current_value - previous_value, 4)
    if previous_value == 0:
        direction: DirectionLabel = (
            "flat" if current_value == 0 else ("up" if current_value > 0 else "down")
        )
        return PeriodDelta(
            grain=grain,
            current_value=current_value,
            previous_value=previous_value,
            absolute_change=abs_change,
            pct_change=None,
            direction=direction,
        )

    pct = ((current_value - previous_value) / abs(previous_value)) * 100.0
    rounded_pct = round(pct, 2)
    if abs(pct) < flat_threshold_pct:
        direction = "flat"
    elif pct > 0:
        direction = "up"
    else:
        direction = "down"

    return PeriodDelta(
        grain=grain,
        current_value=current_value,
        previous_value=previous_value,
        absolute_change=abs_change,
        pct_change=rounded_pct,
        direction=direction,
    )


def build_reversal_aware_summary(
    metric_label: str,
    closed_month_values: Sequence[float],
    *,
    flat_threshold_pct: float = 5.0,
) -> str:
    """Build <25-word trend sentence stating both multi-month trend & latest-month reversal."""
    if len(closed_month_values) < 2:
        return f"{metric_label} has insufficient closed months for trend comparison."

    overall = compute_period_delta(
        closed_month_values[-1],
        closed_month_values[0],
        grain="MoM",
        flat_threshold_pct=flat_threshold_pct,
    )
    latest = compute_period_delta(
        closed_month_values[-1],
        closed_month_values[-2],
        grain="MoM",
        flat_threshold_pct=flat_threshold_pct,
    )

    if len(closed_month_values) >= 3:
        prior_leg = compute_period_delta(
            closed_month_values[-2],
            closed_month_values[0],
            grain="MoM",
            flat_threshold_pct=flat_threshold_pct,
        )
        if (
            prior_leg.direction in {"up", "down"}
            and latest.direction in {"up", "down"}
            and prior_leg.direction != latest.direction
        ):
            latest_pct_str = f"{abs(latest.pct_change or 0):.1f}%"
            return (
                f"{metric_label} trended {prior_leg.direction} earlier, then reversed "
                f"{latest.direction} {latest_pct_str} MoM in the latest closed month."
            )

    if overall.direction == "flat":
        return f"{metric_label} held flat ({overall.pct_change or 0:+.1f}%) across closed months."
    return (
        f"{metric_label} moved {overall.direction} {abs(overall.pct_change or 0):.1f}% "
        f"across closed months ({latest.pct_change or 0:+.1f}% latest MoM)."
    )


def filter_part_month_rows(
    daily_rows: Sequence[dict[str, Any]],
    *,
    date_key: str,
    cutoff_day: int,
) -> list[dict[str, Any]]:
    """Enforce Part-Month Rule: keep only day 1..cutoff_day in every compared month."""
    if not 1 <= cutoff_day <= 31:
        raise MathIntegrityError(f"Invalid part-month cutoff_day={cutoff_day}; expected 1..31.")

    matched: list[dict[str, Any]] = []
    for row in daily_rows:
        raw_dt = row[date_key]
        dt_val = date.fromisoformat(raw_dt) if isinstance(raw_dt, str) else raw_dt
        if dt_val.day <= cutoff_day:
            matched.append(row)
    return matched


def format_inr(amount: float | int, *, prefix: str = "Rs ") -> str:
    """Format INR with Indian lakh/crore grouping (e.g. Rs 3,00,000)."""
    sign = "-" if amount < 0 else ""
    rounded = int(round(abs(amount)))
    digits = str(rounded)
    if len(digits) <= 3:
        grouped = digits
    else:
        last_three = digits[-3:]
        leading = digits[:-3]
        pairs: list[str] = []
        while len(leading) > 2:
            pairs.append(leading[-2:])
            leading = leading[:-2]
        if leading:
            pairs.append(leading)
        grouped = ",".join(reversed(pairs)) + "," + last_three
    return f"{sign}{prefix}{grouped}"
