"""Demand & DoD/WoW presenter helpers keeping every module focused (< 300 lines)."""

from __future__ import annotations

from datetime import date
from typing import Any

from core.guardrails.output_audit import audit_rendered_markdown
from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.kpi_presenter import (
    BANNED_CAUSAL_WORDS,
    _window_label_from_months,
)
from domains.performance_marketing.math_engine import compute_period_delta, format_inr


def render_demand_report(
    *,
    product_rows: list[dict[str, Any]],
    city_rows: list[dict[str, Any]],
    city: str | None,
    catalogue_product: str | None,
    trace_id: str,
) -> SmritiQueryResponse:
    """Render Catalogue Product & City Delivered Demand tables with verified citations."""
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
            f"#### City Product Delivered Demand (`{city}`)",
            "| Month | City | Catalogue Product | Delivered Orders | Gross Orders | Net Revenue |",
            "|---|---|---|---:|---:|---:|",
        ]
        for r in city_rows[:15]:
            m_lbl = date.fromisoformat(str(r["month"])[:10]).strftime("%b %Y")
            lines.append(
                f"| {m_lbl} | `{r['city']}` | {r['catalogue_product']} | "
                f"{int(r.get('net_orders') or 0):,} | {int(r.get('gross_orders') or 0):,} | "
                f"{format_inr(float(r.get('net_revenue') or 0.0))} |"
            )
        lines.append(f"\n[Source: BigQuery {c_cite.object_name} · {c_window}]")
        sections.append("\n".join(lines))

    if product_rows:
        p_window = _window_label_from_months([str(r["month"]) for r in product_rows])
        p_cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.ge_product_demand_monthly",
            date_window_ist=p_window,
            row_count=len(product_rows),
        )
        citations.append(p_cite)
        lines = [
            "#### National Catalogue Product Delivered Demand",
            "| Month | Catalogue Product | Delivered Orders | Gross Orders | Net Revenue |",
            "|---|---|---:|---:|---:|",
        ]
        for r in product_rows[:15]:
            m_lbl = date.fromisoformat(str(r["month"])[:10]).strftime("%b %Y")
            lines.append(
                f"| {m_lbl} | {r['catalogue_product']} | "
                f"{int(r.get('net_orders') or 0):,} | {int(r.get('gross_orders') or 0):,} | "
                f"{format_inr(float(r.get('net_revenue') or 0.0))} |"
            )
        lines.append(f"\n[Source: BigQuery {p_cite.object_name} · {p_window}]")
        sections.append("\n".join(lines))

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
) -> SmritiQueryResponse:
    """Render DoD / WoW placed & delivered order progression from sales_master_data."""
    if not daily_rows:
        cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.sales_master_data",
            date_window_ist="Last 14 Days IST",
            row_count=0,
        )
        md = (
            "No daily order rows found in the requested window.\n\n"
            "[Source: BigQuery Gemini_POC.sales_master_data · Last 14 Days IST]"
        )
        return SmritiQueryResponse(
            headline=f"{grain} Order Progression · Warehouse",
            answer_markdown=audit_rendered_markdown(md, banned_words=BANNED_CAUSAL_WORDS),
            citations=[cite],
            degraded_sources=[],
            latency_ms=0,
            trace_id=trace_id,
        )

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

    lines = [
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

    lines.append(
        "\n*Note:* Recent daily delivered orders are `provisional` while shipments are in transit."
    )
    lines.append(f"\n[Source: BigQuery Gemini_POC.sales_master_data · {window_str}]")
    md = audit_rendered_markdown("\n".join(lines), banned_words=BANNED_CAUSAL_WORDS)
    return SmritiQueryResponse(
        headline=f"{grain} Order Demand · {window_str}",
        answer_markdown=md,
        citations=[cite],
        degraded_sources=[],
        latency_ms=0,
        trace_id=trace_id,
    )
