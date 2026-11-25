"""Demand & DoD/WoW presenter helpers keeping every module focused (< 300 lines)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from core.guardrails.output_audit import audit_rendered_markdown
from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.kpi_presenter import (
    BANNED_CAUSAL_WORDS,
    _fmt_cac,
    _fmt_roas,
    _month_label,
    _window_label_from_months,
)
from domains.performance_marketing.math_engine import (
    compute_net_cac,
    compute_net_roas,
    compute_period_delta,
    format_inr,
)
from domains.performance_marketing.rules import classify_month_settlement


def render_demand_report(
    *,
    product_rows: list[dict[str, Any]],
    city_rows: list[dict[str, Any]],
    city: str | None,
    catalogue_product: str | None,
    trace_id: str,
    family_rows: list[dict[str, Any]] | None = None,
    today_ist: date | None = None,
    boundary_note: str | None = None,
) -> SmritiQueryResponse:
    """Render Catalogue Product & City Delivered Demand tables (+ optional Family ROAS & caveat)."""
    citations: list[Citation] = []
    sections: list[str] = []

    if city_rows:
        c_window = _window_label_from_months([str(r["month"]) for r in city_rows])
        c_cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.ge_city_product_demand_monthly",
            date_window_ist=c_window,
            row_count=len(city_rows),
        )
        citations.append(c_cite)
        lines = [
            f"#### City Product Demand (`{city}`)",
            "| Month | City | Catalogue Product | Placed Orders | Delivered Orders | Net Revenue |",
            "|---|---|---|---:|---:|---:|",
        ]
        for r in city_rows[:15]:
            m_lbl = date.fromisoformat(str(r["month"])[:10]).strftime("%b %Y")
            lines.append(
                f"| {m_lbl} | `{r['city']}` | {r['catalogue_product']} | "
                f"{int(r.get('gross_orders') or 0):,} | {int(r.get('net_orders') or 0):,} | "
                f"{format_inr(float(r.get('net_revenue') or 0.0))} |"
            )
        lines.append(f"\n[Source: BigQuery {c_cite.object_name} · {c_window}]")
        sections.append("\n".join(lines))

    if product_rows and not city_rows:
        p_window = _window_label_from_months([str(r["month"]) for r in product_rows])
        p_cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.ge_product_demand_monthly",
            date_window_ist=p_window,
            row_count=len(product_rows),
        )
        citations.append(p_cite)
        lines = [
            "#### National Catalogue Product Demand",
            "| Month | Catalogue Product | Placed Orders | Delivered Orders | Net Revenue |",
            "|---|---|---:|---:|---:|",
        ]
        for r in product_rows[:15]:
            m_lbl = date.fromisoformat(str(r["month"])[:10]).strftime("%b %Y")
            lines.append(
                f"| {m_lbl} | {r['catalogue_product']} | "
                f"{int(r.get('gross_orders') or 0):,} | {int(r.get('net_orders') or 0):,} | "
                f"{format_inr(float(r.get('net_revenue') or 0.0))} |"
            )
        lines.append(f"\n[Source: BigQuery {p_cite.object_name} · {p_window}]")
        sections.append("\n".join(lines))

    if family_rows and today_ist is not None:
        agg: dict[str, dict[str, float]] = defaultdict(
            lambda: {"spend": 0.0, "rev": 0.0, "orders": 0.0}
        )
        fam_months: list[str] = []
        distinct_m = {str(x["month"]) for x in family_rows}
        for f_row in family_rows:
            m_str = str(f_row["month"])
            fam_months.append(m_str)
            st = classify_month_settlement(
                date.fromisoformat(m_str[:10]),
                today_ist=today_ist,
                warehouse_status=f_row.get("settle_state"),
            )
            if st == "provisional" and len(distinct_m) > 1:
                continue
            key = str(f_row.get("product_family") or "unclassified")
            agg[key]["spend"] += float(f_row.get("spend") or 0.0)
            agg[key]["rev"] += float(f_row.get("net_revenue") or 0.0)
            agg[key]["orders"] += float(f_row.get("net_orders") or 0)

        top_fams = sorted(agg.items(), key=lambda kv: kv[1]["spend"], reverse=True)[:8]
        if top_fams:
            f_window = _window_label_from_months(fam_months)
            f_cite = Citation(
                source="BigQuery",
                object_name="Gemini_POC.ge_family_monthly",
                date_window_ist=f_window,
                row_count=len(family_rows),
            )
            citations.append(f_cite)
            f_lines = [
                "#### National Ad-Family Spend & Net ROAS (`SUM/SUM`)",
                "| Product Family | Spend | Net Revenue | Delivered Orders | Net ROAS | Net CAC |",
                "|---|---:|---:|---:|---:|---:|",
            ]
            for fam_name, vals in top_fams:
                roas = compute_net_roas(vals["rev"], vals["spend"])
                cac = compute_net_cac(vals["spend"], int(vals["orders"]))
                f_lines.append(
                    f"| `{fam_name}` | {format_inr(vals['spend'])} | {format_inr(vals['rev'])} | "
                    f"{int(vals['orders']):,} | {_fmt_roas(roas)} | {_fmt_cac(cac)} |"
                )
            f_lines.append(f"\n[Source: BigQuery {f_cite.object_name} · {f_window}]")
            sections.append("\n".join(f_lines))

    if not sections:
        fallback_cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.ge_product_demand_monthly",
            date_window_ist="Recent 4 Months IST",
            row_count=0,
        )
        citations.append(fallback_cite)
        sections.append(
            "No matching catalogue product or city demand rows recorded in window.\n\n"
            "[Source: BigQuery Gemini_POC.ge_product_demand_monthly · Recent 4 Months IST]"
        )

    if boundary_note:
        sections.append(
            f"#### Scope Boundary — What Could Not Be Computed & Why\n{boundary_note}"
        )

    scope = f"{city} · {catalogue_product or 'All Products'}" if city else "All India Catalogue"
    markdown = audit_rendered_markdown("\n\n".join(sections), banned_words=BANNED_CAUSAL_WORDS)
    return SmritiQueryResponse(
        headline=f"Delivered Product Demand · {scope}",
        answer_markdown=markdown,
        citations=citations,
        degraded_sources=[],
        latency_ms=0,
        trace_id=trace_id,
    )


def render_daily_orders_report(
    *,
    daily_rows: list[dict[str, Any]],
    grain: str,
    trace_id: str,
    account_rows: list[dict[str, Any]] | None = None,
    today_ist: date | None = None,
    boundary_note: str | None = None,
) -> SmritiQueryResponse:
    """Render DoD / WoW placed & delivered orders (+ optional Monthly ROAS & boundary note)."""
    citations: list[Citation] = []
    sections: list[str] = []

    if daily_rows:
        first_dt = str(daily_rows[0]["order_date"])
        last_dt = str(daily_rows[-1]["order_date"])
        window_str = f"{first_dt} – {last_dt} IST"
        cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.sales_master_data",
            date_window_ist=window_str,
            row_count=len(daily_rows),
            note="Recent days remain provisional until delivery & RTO settlement completes.",
        )
        citations.append(cite)
        lines = [
            "#### Daily Placed & Delivered Order Progression",
            "| Order Date (IST) | Placed Orders | Delivered Orders "
            "| Delivered Revenue | DoD Placed Δ |",
            "|---|---:|---:|---:|---|",
        ]
        prev_gross: float | None = None
        for row in daily_rows[-10:]:
            gross = int(row.get("gross_orders") or 0)
            net = int(row.get("net_orders") or 0)
            rev = float(row.get("net_revenue") or 0.0)
            delta_txt = "—"
            if prev_gross is not None:
                d = compute_period_delta(float(gross), prev_gross, grain="DoD")
                pct_s = f"{d.pct_change:+.1f}%" if d.pct_change is not None else "N/A"
                delta_txt = f"{pct_s} ({d.direction})"
            prev_gross = float(gross)
            lines.append(
                f"| {row['order_date']} | {gross:,} | {net:,} | {format_inr(rev)} | {delta_txt} |"
            )
        lines.append(f"\n[Source: BigQuery Gemini_POC.sales_master_data · {window_str}]")
        sections.append("\n".join(lines))
    else:
        window_str = "Last 14 Days IST"
        cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.sales_master_data",
            date_window_ist=window_str,
            row_count=0,
        )
        citations.append(cite)
        sections.append(
            "No daily order rows found in the requested window.\n\n"
            "[Source: BigQuery Gemini_POC.sales_master_data · Last 14 Days IST]"
        )

    if account_rows and today_ist is not None:
        a_window = _window_label_from_months([str(r["month"]) for r in account_rows[-4:]])
        a_cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.ge_account_monthly",
            date_window_ist=a_window,
            row_count=len(account_rows[-4:]),
        )
        citations.append(a_cite)
        m_lines = [
            "#### Monthly Account Net ROAS & CAC (Valid Attribution Grain)",
            "| Month | Status | Perf Spend | Net Revenue | Delivered Orders | Net ROAS | Net CAC |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for r in account_rows[-4:]:
            st = classify_month_settlement(
                date.fromisoformat(str(r["month"])[:10]),
                today_ist=today_ist,
                warehouse_status=r.get("settle_state"),
            )
            perf = float(r.get("performance_spend") or 0.0)
            rev = float(r.get("net_revenue") or 0.0)
            ords = int(r.get("net_orders") or 0)
            m_lines.append(
                f"| {_month_label(str(r['month']), r.get('month_name'))} | `{st}` | "
                f"{format_inr(perf)} | {format_inr(rev)} | {ords:,} | "
                f"{_fmt_roas(compute_net_roas(rev, perf))} | "
                f"{_fmt_cac(compute_net_cac(perf, ords))} |"
            )
        m_lines.append(f"\n[Source: BigQuery {a_cite.object_name} · {a_window}]")
        sections.append("\n".join(m_lines))

    if boundary_note:
        sections.append(
            f"#### Scope Boundary — What Could Not Be Computed & Why\n{boundary_note}"
        )

    md = audit_rendered_markdown("\n\n".join(sections), banned_words=BANNED_CAUSAL_WORDS)
    return SmritiQueryResponse(
        headline=f"{grain} Order Demand · {window_str}",
        answer_markdown=md,
        citations=citations,
        degraded_sources=[],
        latency_ms=0,
        trace_id=trace_id,
    )
