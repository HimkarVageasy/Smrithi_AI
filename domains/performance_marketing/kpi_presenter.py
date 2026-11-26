"""Deterministic KPI verifier & Markdown report builder for Performance Marketing."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from core.guardrails.math_audit import (
    audit_additive_total,
    audit_window_subset_bound,
    emit_reconciliation_warning,
)
from core.guardrails.output_audit import audit_rendered_markdown
from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.math_engine import (
    build_reversal_aware_summary,
    compute_net_cac,
    compute_net_roas,
    compute_period_delta,
    format_inr,
)
from domains.performance_marketing.rules import classify_month_settlement

BANNED_CAUSAL_WORDS: frozenset[str] = frozenset({"caused", "drove", "profitable"})


def _fmt_roas(val: float | None) -> str:
    return f"{val:.2f}x" if val is not None else "N/A"


def _fmt_cac(val: float | None) -> str:
    return format_inr(val) if val is not None else "N/A"


def _month_label(iso_month: str, month_name: str | None = None) -> str:
    if month_name and month_name.strip():
        return month_name.strip()
    dt = date.fromisoformat(iso_month[:10])
    return dt.strftime("%b %Y")


def _window_label_from_months(months: list[str]) -> str:
    if not months:
        return "No rows in window IST"
    sorted_m = sorted(months)
    first_lbl = date.fromisoformat(sorted_m[0][:10]).strftime("%b %Y")
    last_lbl = date.fromisoformat(sorted_m[-1][:10]).strftime("%b %Y")
    return f"{first_lbl} IST" if first_lbl == last_lbl else f"{first_lbl} – {last_lbl} IST"


def _build_catalogue_product_section(
    product_rows: list[dict[str, Any]],
) -> tuple[str, Citation | None]:
    if not product_rows:
        return "", None

    prod_agg: dict[str, dict[str, float]] = defaultdict(
        lambda: {"gross_orders": 0.0, "net_orders": 0.0, "net_rev": 0.0}
    )
    prod_months: list[str] = []
    for row in product_rows:
        prod_months.append(str(row["month"]))
        name = str(row.get("catalogue_product") or "Unclassified")
        prod_agg[name]["gross_orders"] += float(row.get("gross_orders") or 0)
        prod_agg[name]["net_orders"] += float(row.get("net_orders") or 0)
        prod_agg[name]["net_rev"] += float(row.get("net_revenue") or 0.0)

    top_products = sorted(
        prod_agg.items(),
        key=lambda kv: kv[1]["net_orders"],
        reverse=True,
    )[:10]
    if not top_products:
        return "", None

    p_window = _window_label_from_months(prod_months)
    cite = Citation(
        source="BigQuery",
        object_name="Gemini_POC.ge_product_demand_monthly",
        date_window_ist=p_window,
        row_count=len(product_rows),
        note="Catalogue item demand has Placed & Delivered Orders; ad spend lives at Ad-Family.",
    )
    lines = [
        f"\n\n#### Catalogue Product Order Demand (`{p_window}`)",
        "| Catalogue Product | Placed Orders | Delivered Orders | Delivered Revenue |",
        "|---|---:|---:|---:|",
    ]
    for p_name, vals in top_products:
        lines.append(
            f"| {p_name} | {int(vals['gross_orders']):,} | "
            f"{int(vals['net_orders']):,} | {format_inr(vals['net_rev'])} |"
        )
    lines.append(f"\n[Source: BigQuery {cite.object_name} · {p_window}]")
    return "\n".join(lines), cite


def render_account_and_family_report(
    *,
    account_rows: list[dict[str, Any]],
    closed_rows: list[dict[str, Any]],
    family_rows: list[dict[str, Any]],
    window_months: int,
    product_family: str | None,
    today_ist: date,
    trace_id: str,
    product_demand_rows: list[dict[str, Any]] | None = None,
    boundary_note: str | None = None,
) -> SmritiQueryResponse:
    """Compute SUM/SUM metrics in Python and build cited Account + Family + Product report."""
    closed_months_set = {str(r["month"]) for r in closed_rows[-window_months:]}
    display_acct = [
        r
        for r in account_rows
        if str(r["month"]) in closed_months_set or bool(r.get("is_provisional"))
    ]
    if not display_acct:
        display_acct = account_rows[-(window_months + 1) :]

    closed_slice = closed_rows[-max(3, window_months) :]
    closed_roas_series = [
        r_val
        for row in closed_slice
        if (
            r_val := compute_net_roas(
                float(row.get("net_revenue") or 0.0),
                float(row.get("performance_spend") or 0.0),
            )
        )
        is not None
    ]
    lead_sentence = build_reversal_aware_summary("Account Net ROAS", closed_roas_series)

    acct_lines = [
        "#### Account Month-on-Month Trend",
        "| Month | Status | Total Spend | Perf Spend | Brand Spend "
        "| Placed Orders | Delivered Orders | Net Revenue | Net ROAS | Net CAC | MoM ROAS Δ |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    prev_roas: float | None = None
    tot_spend = 0.0
    tot_perf = 0.0
    tot_brand = 0.0
    tot_gross_ord = 0
    tot_net_ord = 0
    tot_net_rev = 0.0

    for row in display_acct:
        m_dt = date.fromisoformat(str(row["month"])[:10])
        status = classify_month_settlement(
            m_dt,
            today_ist=today_ist,
            warehouse_status=row.get("settle_state"),
        )
        perf_spend = float(row.get("performance_spend") or 0.0)
        brand_spend = float(row.get("brand_spend") or 0.0)
        total_spend = float(row.get("total_meta_spend") or (perf_spend + brand_spend))
        gross_orders = int(row.get("gross_orders") or row.get("net_orders") or 0)
        net_orders = int(row.get("net_orders") or 0)
        net_rev = float(row.get("net_revenue") or 0.0)

        spend_chk = audit_additive_total([perf_spend, brand_spend], total_spend)
        if not spend_chk.ok and spend_chk.reason:
            emit_reconciliation_warning(
                check_name="account_spend_identity", reason=spend_chk.reason, trace_id=trace_id
            )
        ord_chk = audit_window_subset_bound(net_orders, gross_orders)
        if not ord_chk.ok and ord_chk.reason:
            emit_reconciliation_warning(
                check_name="delivered_vs_placed_orders", reason=ord_chk.reason, trace_id=trace_id
            )

        roas = compute_net_roas(net_rev, perf_spend)
        cac = compute_net_cac(perf_spend, net_orders)

        delta_str = "—"
        if prev_roas is not None and roas is not None:
            d = compute_period_delta(roas, prev_roas, grain="MoM")
            pct_txt = f"{d.pct_change:+.1f}%" if d.pct_change is not None else "N/A"
            delta_str = f"{pct_txt} ({d.direction})"
        prev_roas = roas

        if status != "provisional":
            tot_spend += total_spend
            tot_perf += perf_spend
            tot_brand += brand_spend
            tot_gross_ord += gross_orders
            tot_net_ord += net_orders
            tot_net_rev += net_rev

        acct_lines.append(
            f"| {_month_label(str(row['month']), row.get('month_name'))} | `{status}` | "
            f"{format_inr(total_spend)} | {format_inr(perf_spend)} | {format_inr(brand_spend)} | "
            f"{gross_orders:,} | {net_orders:,} | {format_inr(net_rev)} | "
            f"{_fmt_roas(roas)} | {_fmt_cac(cac)} | {delta_str} |"
        )

    blended_roas = compute_net_roas(tot_net_rev, tot_perf)
    blended_cac = compute_net_cac(tot_perf, tot_net_ord)
    acct_lines.append(
        f"| **Closed Window Total (SUM/SUM)** | `verified` | **{format_inr(tot_spend)}** | "
        f"**{format_inr(tot_perf)}** | **{format_inr(tot_brand)}** | "
        f"**{tot_gross_ord:,}** | **{tot_net_ord:,}** | **{format_inr(tot_net_rev)}** | "
        f"**{_fmt_roas(blended_roas)}** | **{_fmt_cac(blended_cac)}** | — |"
    )

    acct_window = _window_label_from_months([str(r["month"]) for r in display_acct])
    acct_cite = Citation(
        source="BigQuery",
        object_name="Gemini_POC.ge_account_monthly + ge_account_closed_months + ge_month_status",
        date_window_ist=acct_window,
        row_count=len(display_acct),
        note="Brand spend excluded from Net ROAS and Net CAC; totals computed via SUM/SUM.",
    )
    citations = [acct_cite]

    fam_section = ""
    if family_rows:
        agg: dict[str, dict[str, float]] = defaultdict(
            lambda: {"spend": 0.0, "rev": 0.0, "orders": 0.0}
        )
        fam_months: list[str] = []
        distinct_months = {str(x["month"]) for x in family_rows}
        for f_row in family_rows:
            m_str = str(f_row["month"])
            fam_months.append(m_str)
            st = classify_month_settlement(
                date.fromisoformat(m_str[:10]),
                today_ist=today_ist,
                warehouse_status=f_row.get("settle_state"),
            )
            if st == "provisional" and len(distinct_months) > 1:
                continue
            fam_key = str(f_row.get("product_family") or "unclassified")
            agg[fam_key]["spend"] += float(f_row.get("spend") or 0.0)
            agg[fam_key]["rev"] += float(f_row.get("net_revenue") or 0.0)
            agg[fam_key]["orders"] += float(f_row.get("net_orders") or 0)

        sorted_fams = sorted(agg.items(), key=lambda kv: kv[1]["spend"], reverse=True)[:8]
        if sorted_fams:
            fam_window = _window_label_from_months(fam_months)
            fam_cite = Citation(
                source="BigQuery",
                object_name="Gemini_POC.ge_family_monthly",
                date_window_ist=fam_window,
                row_count=len(family_rows),
            )
            citations.append(fam_cite)
            fam_lines = [
                "\n\n#### Ad-Family Spend & Net ROAS (`SUM/SUM` Excluding Provisional Month)",
                "| Product Family | Spend | Net Revenue | Delivered Orders | Net ROAS | Net CAC |",
                "|---|---:|---:|---:|---:|---:|",
            ]
            for fam_name, vals in sorted_fams:
                f_roas = compute_net_roas(vals["rev"], vals["spend"])
                f_cac = compute_net_cac(vals["spend"], int(vals["orders"]))
                fam_lines.append(
                    f"| `{fam_name}` | {format_inr(vals['spend'])} | {format_inr(vals['rev'])} | "
                    f"{int(vals['orders']):,} | {_fmt_roas(f_roas)} | {_fmt_cac(f_cac)} |"
                )
            fam_lines.append(f"\n[Source: BigQuery Gemini_POC.ge_family_monthly · {fam_window}]")
            fam_section = "\n".join(fam_lines)

    prod_section, prod_cite = _build_catalogue_product_section(product_demand_rows or [])
    if prod_cite is not None:
        citations.append(prod_cite)

    boundary_section = (
        f"\n\n#### Scope Boundary — What Could Not Be Computed & Why\n{boundary_note}"
        if boundary_note
        else ""
    )
    caveat = (
        "\n\n*Settlement Caveat:* Current calendar month rows are flagged `provisional` "
        "(RTOs still in transit inflate early ROAS); trend direction uses closed months only."
    )
    scope_tag = f"Family `{product_family}`" if product_family else "Account + Ad-Family Breakdown"
    markdown = (
        f"{lead_sentence}\n\n"
        + "\n".join(acct_lines)
        + f"\n\n[Source: BigQuery {acct_cite.object_name} · {acct_window}]"
        + fam_section
        + prod_section
        + boundary_section
        + caveat
    )
    verified_md = audit_rendered_markdown(markdown, banned_words=BANNED_CAUSAL_WORDS)
    return SmritiQueryResponse(
        headline=f"Net ROAS, Spend & Order Trend · {acct_window} · {scope_tag}",
        answer_markdown=verified_md,
        citations=citations,
        degraded_sources=[],
        latency_ms=0,
        trace_id=trace_id,
    )
