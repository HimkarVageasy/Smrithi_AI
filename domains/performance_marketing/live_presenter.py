"""Presenter for Slice 2 Live Funnel & Ad Diagnostic (`BigQuery + Mixpanel + Meta/Google`)."""

from __future__ import annotations

from datetime import date
from typing import Any

from core.guardrails.math_audit import (
    audit_funnel_monotonicity,
    audit_window_subset_bound,
    emit_reconciliation_warning,
)
from core.guardrails.output_audit import audit_rendered_markdown
from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.collectors.mixpanel_live import compute_cross_source_cvr
from domains.performance_marketing.kpi_presenter import (
    BANNED_CAUSAL_WORDS,
    _fmt_cac,
    _fmt_roas,
    _month_label,
    _window_label_from_months,
)
from domains.performance_marketing.math_engine import compute_net_cac, compute_net_roas, format_inr
from domains.performance_marketing.rules import classify_month_settlement


def _fmt_opt_inr(val: float | None) -> str:
    return f"Rs {val:,.2f}" if val is not None else "N/A"


def _fmt_opt_pct(val: float | None) -> str:
    return f"{val:.2f}%" if val is not None else "N/A"


def render_live_diagnostic_report(
    *,
    account_rows: list[dict[str, Any]],
    recent_daily_orders: list[dict[str, Any]],
    mixpanel_bundle: dict[str, Any] | None,
    meta_bundle: dict[str, Any] | None,
    google_bundle: dict[str, Any] | None,
    degraded_sources: list[str],
    product_family: str | None,
    today_ist: date,
    trace_id: str,
) -> SmritiQueryResponse:
    """Combine BigQuery financial truth + Mixpanel 3-step funnel + live Meta/Google delivery."""
    citations: list[Citation] = []
    sections: list[str] = []

    # 1. Warehouse Financial Truth (BigQuery)
    recent_acct = account_rows[-2:] if account_rows else []
    if recent_acct:
        a_win = _window_label_from_months([str(r["month"]) for r in recent_acct])
        a_cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.ge_account_monthly",
            date_window_ist=a_win,
            row_count=len(recent_acct),
            note="Sole source of truth for Net Delivered Revenue, Orders, ROAS, and CAC.",
        )
        citations.append(a_cite)
        bq_lines = [
            "#### 1. Warehouse Financial Truth (`BigQuery`)",
            "| Month | Status | Perf Spend | Delivered Orders | Net Revenue | Net ROAS | Net CAC |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for r in recent_acct:
            st = classify_month_settlement(
                date.fromisoformat(str(r["month"])[:10]),
                today_ist=today_ist,
                warehouse_status=r.get("settle_state"),
            )
            perf = float(r.get("performance_spend") or 0.0)
            rev = float(r.get("net_revenue") or 0.0)
            ords = int(r.get("net_orders") or 0)
            bq_lines.append(
                f"| {_month_label(str(r['month']), r.get('month_name'))} | `{st}` | "
                f"{format_inr(perf)} | {ords:,} | {format_inr(rev)} | "
                f"{_fmt_roas(compute_net_roas(rev, perf))} | "
                f"{_fmt_cac(compute_net_cac(perf, ords))} |"
            )
        bq_lines.append(f"\n[Source: BigQuery {a_cite.object_name} · {a_win}]")
        sections.append("\n".join(bq_lines))

    # 2. Mixpanel Live 3-Step Funnel + Cross-Source CVR (M1..M6)
    if mixpanel_bundle is not None:
        mp_win = str(mixpanel_bundle["effective_window_ist"])
        mp_notes = "; ".join(mixpanel_bundle.get("notes") or []) or None
        mp_cite = Citation(
            source="Mixpanel",
            object_name="3-Step Paid Funnel (products -> begin_checkout -> payment_options)",
            date_window_ist=mp_win,
            row_count=3,
            note=mp_notes,
        )
        citations.append(mp_cite)

        views = int(mixpanel_bundle.get("product_page_views") or 0)
        chk = mixpanel_bundle.get("begin_checkout")
        pay = mixpanel_bundle.get("payment_options_reached")
        bq_28d_delivered = sum(int(r.get("net_orders") or 0) for r in recent_daily_orders)

        funnel_check = audit_funnel_monotonicity([views, chk, pay])
        cvr_mismatch_reason: str | None = None
        if len(recent_acct) >= 2:
            two_month_bound = sum(int(r.get("net_orders") or 0) for r in recent_acct)
            sub_check = audit_window_subset_bound(bq_28d_delivered, two_month_bound)
            if not sub_check.ok:
                cvr_mismatch_reason = sub_check.reason
        if cvr_mismatch_reason is None and chk is not None and chk > 0:
            chk_bound = audit_window_subset_bound(bq_28d_delivered, chk)
            if not chk_bound.ok:
                cvr_mismatch_reason = chk_bound.reason

        if cvr_mismatch_reason is not None:
            emit_reconciliation_warning(
                check_name="cross_source_cvr_subset_bound",
                reason=cvr_mismatch_reason,
                trace_id=trace_id,
            )
            cvr_bullet = (
                "- **Cross-source conversion:** `[Reconciliation Warning: source scope "
                f"mismatch detected — ratio withheld ({cvr_mismatch_reason})]`"
            )
        else:
            cross_cvr = compute_cross_source_cvr(bq_28d_delivered, views)
            cvr_bullet = f"- **{cross_cvr['label']}:** `{cross_cvr['display']}`"

        mp_lines = [
            "#### 2. Website 3-Step Paid Funnel (`Mixpanel Live`)",
            "| Funnel Step | Unique Paid Sessions | Progression Rate |",
            "|---|---:|---|",
            (
                f"| 1. Product Page View (`Page Viewed` · `page_variant=\"products\"`) | "
                f"{views:,} | — |"
            ),
            (
                f"| 2. Checkout Start (`mp_begin_checkout`) | "
                f"{f'{chk:,}' if chk is not None else 'N/A'} | "
                f"{mixpanel_bundle['view_to_checkout_rate']} |"
            ),
            (
                f"| 3. Payment Options (`mp_navigation_payment_options`) | "
                f"{f'{pay:,}' if pay is not None else 'N/A'} | "
                f"{mixpanel_bundle['checkout_to_payment_rate']} |"
            ),
            f"\n{cvr_bullet}",
        ]
        if not funnel_check.ok and funnel_check.reason:
            emit_reconciliation_warning(
                check_name="mixpanel_funnel_monotonicity",
                reason=funnel_check.reason,
                trace_id=trace_id,
            )
            mp_lines.append(
                f"- *Reconciliation Warning:* Funnel monotonicity alert ({funnel_check.reason})."
            )
        for note in mixpanel_bundle.get("notes") or []:
            mp_lines.append(f"- *Cutoff Note:* {note}")
        mp_lines.append(f"\n[Source: Mixpanel {mp_cite.object_name} · {mp_win}]")
        sections.append("\n".join(mp_lines))

    # 3. Live Meta Ads Account Pulse (774668588585301)
    if meta_bundle is not None:
        meta_win = str(meta_bundle["date_window_ist"])
        acct_id = str(meta_bundle["account_id"])
        meta_cite = Citation(
            source="Meta Ads Account",
            object_name=f"Account {acct_id} (Live Ads & Opportunity Score)",
            date_window_ist=meta_win,
            row_count=len(meta_bundle.get("active_ads") or []),
            note="Real-time delivery pulse only; never used for Net ROAS or Net CAC.",
        )
        citations.append(meta_cite)
        meta_lines = [
            f"#### 3. Live Meta Ads Delivery Pulse (`Account {acct_id}`)",
            "| Active Ad | Campaign | 7d Spend | CTR | CPC | CPM |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for ad in (meta_bundle.get("active_ads") or [])[:8]:
            meta_lines.append(
                f"| `{ad['ad_name']}` | {ad['campaign_name']} | "
                f"{format_inr(ad['spend_inr'])} | {_fmt_opt_pct(ad['ctr_pct'])} | "
                f"{_fmt_opt_inr(ad['cpc_inr'])} | {_fmt_opt_inr(ad['cpm_inr'])} |"
            )
        recs = meta_bundle.get("recommendations") or []
        if recs:
            top_rec = recs[0]
            lift = f" (+{top_rec['score_lift']} pts)" if top_rec.get("score_lift") else ""
            meta_lines.append(
                f"\n- **Meta Opportunity Recommendation:** {top_rec['title']}{lift}"
            )
        meta_lines.append(f"\n[Source: Meta Ads Account {acct_id} · {meta_win}]")
        sections.append("\n".join(meta_lines))

    # 4. Live Google Ads Pulse (only when enabled & returned)
    if google_bundle is not None:
        g_win = str(google_bundle["date_window_ist"])
        g_cite = Citation(
            source="Google Ads Account",
            object_name=f"Customer {google_bundle['customer_id']} (SearchStream)",
            date_window_ist=g_win,
            row_count=len(google_bundle.get("campaigns") or []),
        )
        citations.append(g_cite)
        g_lines = [
            "#### 4. Live Google Ads Delivery Pulse",
            "| Campaign | Channel | Status | 7d Spend | CTR | CPC |",
            "|---|---|---|---:|---:|---:|",
        ]
        for c in (google_bundle.get("campaigns") or [])[:8]:
            g_lines.append(
                f"| {c['campaign_name']} | `{c['channel_type']}` | `{c['status']}` | "
                f"{format_inr(c['spend_inr'])} | {_fmt_opt_pct(c['ctr_pct'])} | "
                f"{_fmt_opt_inr(c['cpc_inr'])} |"
            )
        g_lines.append(f"\n[Source: Google Ads Account {g_cite.object_name} · {g_win}]")
        sections.append("\n".join(g_lines))

    if degraded_sources:
        deg_items = "\n".join(f"- `{src}`" for src in degraded_sources)
        sections.append(
            "#### Live Connector Availability Note (Graceful Degradation)\n"
            "Warehouse truth succeeded; the following non-critical live connectors were "
            f"unavailable or timed out:\n{deg_items}"
        )

    scope_lbl = f"Family `{product_family}`" if product_family else "All Active Campaigns"
    md = audit_rendered_markdown("\n\n".join(sections), banned_words=BANNED_CAUSAL_WORDS)
    return SmritiQueryResponse(
        headline=f"Live Funnel & Ad Diagnostic · {scope_lbl}",
        answer_markdown=md,
        citations=citations,
        degraded_sources=degraded_sources,
        latency_ms=0,
        trace_id=trace_id,
    )
