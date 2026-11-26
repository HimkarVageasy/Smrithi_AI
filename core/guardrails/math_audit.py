"""Domain-agnostic numerical & cross-table reconciliation auditor (`LOW_LEVEL_DESIGN.md` §6.2)."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

_logger = logging.getLogger("smriti.guardrails.math_audit")


@dataclass(frozen=True)
class ReconciliationResult:
    """Outcome of a deterministic numerical or cross-source sanity check."""

    ok: bool
    reason: str | None = None


def audit_window_subset_bound(
    subset_value: float,
    enclosing_total: float,
    *,
    tolerance: float = 0.0,
) -> ReconciliationResult:
    """Verify a narrower sub-window or subset never exceeds its enclosing total."""
    if subset_value < 0 or enclosing_total < 0:
        return ReconciliationResult(ok=False, reason="negative count/amount encountered")
    if subset_value > enclosing_total + tolerance:
        return ReconciliationResult(
            ok=False,
            reason=f"subset ({subset_value:g}) exceeds enclosing bound ({enclosing_total:g})",
        )
    return ReconciliationResult(ok=True)


def audit_funnel_monotonicity(ordered_steps: Sequence[int | None]) -> ReconciliationResult:
    """Verify each present funnel step is <= the preceding step."""
    prev_val: int | None = None
    for idx, step_val in enumerate(ordered_steps, start=1):
        if step_val is None:
            continue
        if step_val < 0:
            return ReconciliationResult(ok=False, reason=f"step {idx} is negative ({step_val})")
        if prev_val is not None and step_val > prev_val:
            return ReconciliationResult(
                ok=False,
                reason=f"step {idx} ({step_val:,}) exceeds prior step ({prev_val:,})",
            )
        prev_val = step_val
    return ReconciliationResult(ok=True)


def audit_additive_total(
    parts: Sequence[float],
    reported_total: float,
    *,
    abs_tolerance: float = 2.0,
) -> ReconciliationResult:
    """Verify component values sum to the reported total within rounding tolerance."""
    computed_sum = sum(parts)
    diff = abs(computed_sum - reported_total)
    if diff > abs_tolerance:
        return ReconciliationResult(
            ok=False,
            reason=f"parts sum ({computed_sum:.2f}) != reported total ({reported_total:.2f})",
        )
    return ReconciliationResult(ok=True)


def audit_rate_bounds(
    value: float | None,
    *,
    min_value: float = 0.0,
    max_value: float | None = None,
) -> ReconciliationResult:
    """Verify computed rate or metric falls within valid domain bounds."""
    if value is None:
        return ReconciliationResult(ok=True)
    if value < min_value:
        return ReconciliationResult(
            ok=False,
            reason=f"value ({value:.4f}) below minimum ({min_value:.4f})",
        )
    if max_value is not None and value > max_value:
        return ReconciliationResult(
            ok=False,
            reason=f"value ({value:.4f}) exceeds maximum ({max_value:.4f})",
        )
    return ReconciliationResult(ok=True)


def emit_reconciliation_warning(*, check_name: str, reason: str, trace_id: str) -> None:
    """Emit structured Cloud Logging WARNING payload when reconciliation trips in prod."""
    payload = {
        "severity": "WARNING",
        "event": "RECONCILIATION_MISMATCH",
        "check": check_name,
        "reason": reason,
        "trace_id": trace_id,
    }
    _logger.warning(json.dumps(payload))
