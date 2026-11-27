"""Executive presenter for Structured Campaign Briefs (Golden Scenarios #3, #4, #5 + Memory)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from core.guardrails.output_audit import audit_rendered_markdown
from core.memory.schemas import MemoryChunk
from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.competitor_presenter import format_rival_creative_block
from domains.performance_marketing.kpi_presenter import (
    BANNED_CAUSAL_WORDS,
    _fmt_cac,
    _fmt_roas,
    _window_label_from_months,
)
from domains.performance_marketing.math_engine import compute_net_cac, compute_net_roas, format_inr
from domains.performance_marketing.rules import classify_month_settlement
from domains.performance_marketing.schemas import CampaignPlanIntake, PhasedBudgetPlan


def render_campaign_plan_report(
    *,
    strategy: dict[str, Any],
    family_rows: list[dict[str, Any]],
    product_rows: list[dict[str, Any]],
    city_rows: list[dict[str, Any]],
    mixpanel_bundle: dict[str, Any] | None,
    meta_live: dict[str, Any] | None,
    meta_lib: dict[str, Any] | None,
    google_transp: dict[str, Any] | None,
    degraded_sources: list[str],
    today_ist: date,
    trace_id: str,
) -> SmritiQueryResponse:
    """Render structured Campaign Brief with verified math and inline [Source · Window] tags."""
    intake: CampaignPlanIntake = strategy["intake"]
    plan: PhasedBudgetPlan = strategy["phased_plan"]
    rule_chunk: MemoryChunk | None = strategy.get("applied_ruleset_chunk")
    mem_chunks: list[MemoryChunk] = strategy.get("memory_chunks") or []
    cites: list[Citation] = []
    numbered_sections: list[tuple[str, str]] = []

    reg_lbl = f"{intake.region} (assumed)" if intake.region_assumed else intake.region
    tgt_lbl = (
        f"{strategy['effective_target_roas']:.2f}x Net ROAS (historical P50 assumed)"
        if intake.target_assumed
        else f"{strategy['effective_target_roas']:.2f}x Net ROAS (requested)"
    )
    scale_lbl = (
        f"`{strategy['scale_multiple']:.2f}x` vs. last closed month "
        f"({format_inr(strategy['last_closed_spend_inr'])})"
        if strategy["scale_multiple"] is not None
        else "New / unscaled family baseline"
    )
    premise_line = (
        f"\n- **External Premise:** *{intake.external_premise}* (`your premise, not our data`)"
        if intake.external_premise
        else ""
    )
    rule_line = (
        f"\n- **Active Ruleset Applied:** `{rule_chunk.source_title}` (`{rule_chunk.trust_tier}`)"
        if rule_chunk is not None
        else ""
    )
    numbered_sections.append(
        (
            "Verdict & Intake Scope",
            f"**{strategy['verdict']}**\n"
            f"- **Product / Family:** `{intake.product_query}` · **Region:** `{reg_lbl}` · "
            f"**Window:** `{intake.window_label}`\n"
            f"- **Planned Budget:** **{format_inr(intake.budget_inr)}** ({scale_lbl}) · "
            f"**Target KPI:** `{tgt_lbl}`{premise_line}{rule_line}",
        )
    )

    if family_rows:
        f_win = _window_label_from_months([str(r["month"]) for r in family_rows])
        f_cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.ge_family_monthly",
            date_window_ist=f_win,
            row_count=len(family_rows),
        )
        cites.append(f_cite)
        h_lines = [
            "| Month | Status | Spend | Net Revenue | Delivered Orders | Net ROAS | Net CAC |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for r in family_rows[-4:]:
            m_dt = date.fromisoformat(str(r["month"])[:10])
            st = classify_month_settlement(
                m_dt, today_ist=today_ist, warehouse_status=r.get("settle_state")
            )
            sp = float(r.get("spend") or 0)
            rv = float(r.get("net_revenue") or 0)
            od = int(r.get("net_orders") or 0)
            roas_s = _fmt_roas(compute_net_roas(rv, sp))
            cac_s = _fmt_cac(compute_net_cac(sp, od))
            h_lines.append(
                f"| {m_dt.strftime('%b %Y')} | `{st}` | {format_inr(sp)} | {format_inr(rv)} | "
                f"{od:,} | {roas_s} | {cac_s} |"
            )
        if city_rows:
            tot_c_ord = sum(int(x.get("net_orders") or 0) for x in city_rows)
            h_lines.append(
                f"\n- **City Demand (`{intake.region}`):** `{tot_c_ord:,}` delivered orders."
            )
        elif product_rows:
            tot_p_ord = sum(int(x.get("net_orders") or 0) for x in product_rows)
            h_lines.append(f"\n- **Catalogue Demand:** `{tot_p_ord:,}` delivered orders.")
        h_lines.append(f"\n[Source: BigQuery {f_cite.object_name} · {f_win}]")
        numbered_sections.append(
            (f"Historical Warehouse Baseline ({strategy['baseline_source']})", "\n".join(h_lines))
        )
    else:
        b_cite = Citation(
            source="BigQuery",
            object_name="Gemini_POC.ge_account_closed_months",
            date_window_ist="Recent Closed Months IST",
            row_count=3,
        )
        cites.append(b_cite)
        numbered_sections.append(
            (
                "Historical Warehouse Baseline",
                f"No dedicated `{intake.product_query}` ad-family rows found; anchored to "
                f"{strategy['baseline_source']} (P50 Net ROAS `{strategy['p50_roas']:.2f}x`, "
                f"P50 Net CAC `{format_inr(strategy['p50_cac_inr'])}`).\n\n"
                f"[Source: BigQuery {b_cite.object_name} · Recent Closed Months IST]",
            )
        )

    if mixpanel_bundle is not None:
        mp_win = str(mixpanel_bundle["effective_window_ist"])
        mp_cite = Citation(
            source="Mixpanel",
            object_name="3-Step Paid Funnel",
            date_window_ist=mp_win,
            row_count=3,
        )
        cites.append(mp_cite)
        numbered_sections.append(
            (
                "Website Funnel Health (`Mixpanel Live`)",
                f"- **Product Views:** `{int(mixpanel_bundle['product_page_views']):,}` -> "
                f"**Checkout Start:** `{mixpanel_bundle['begin_checkout']:,}` "
                f"(`{mixpanel_bundle['view_to_checkout_rate']}`) -> "
                f"**Payment Reached:** `{mixpanel_bundle['payment_options_reached']:,}` "
                f"(`{mixpanel_bundle['checkout_to_payment_rate']}`)\n\n"
                f"[Source: Mixpanel 3-Step Paid Funnel · {mp_win}]",
            )
        )

    p_lines = [
        "| Phase | Channel | Funnel Stage | Budget (INR) "
        "| Daily Rate | Window | Gate / Condition |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for row in plan.rows:
        p_lines.append(
            f"| {row.phase_name} | `{row.channel}` | {row.funnel_stage} | "
            f"{format_inr(row.amount_inr)} | {format_inr(row.daily_run_rate_inr)}/d | "
            f"{row.date_range} | {row.scale_condition} |"
        )
    p_lines.append(
        f"| **Total Allocated Media Budget** | **All Active** | **100% Sum** | "
        f"**{format_inr(plan.total_budget_inr)}** | — | `{intake.window_label}` | "
        "A/B arm is carved inside Phase 1 (non-additive) |"
    )
    numbered_sections.append(
        ("Phased Channel & Funnel Budget Allocation (`100%` Verified Sum)", "\n".join(p_lines))
    )

    if mem_chunks:
        m_lines: list[str] = []
        seen_mem: set[str] = set()
        for mc in mem_chunks[:4]:
            safe_txt = mc.content_text.replace("\n", " ")[:220]
            for banned in BANNED_CAUSAL_WORDS:
                safe_txt = re.sub(rf"\b{re.escape(banned)}\b", "[observed]", safe_txt, flags=re.I)
            m_lines.append(
                f"- **{mc.section_type}:** {safe_txt} "
                f"[Source: Smriti Memory {mc.source_title} ({mc.trust_tier}) · "
                f"{mc.created_at_iso[:10]}]"
            )
            if mc.source_title not in seen_mem:
                seen_mem.add(mc.source_title)
                cites.append(
                    Citation(
                        source="Smriti Memory",
                        object_name=f"{mc.source_title} ({mc.trust_tier})",
                        date_window_ist=mc.created_at_iso[:10],
                        row_count=1,
                    )
                )
        numbered_sections.append(
            ("Institutional Memory & Ruleset Learnings (`Smriti Memory`)", "\n".join(m_lines))
        )

    today_str = f"{today_ist.strftime('%d %b %Y')} IST"
    rival_md, r_cites = format_rival_creative_block(meta_lib, google_transp, None, today_str)
    cites.extend(r_cites)
    live_bits: list[str] = []
    if meta_live and meta_live.get("active_ads"):
        top_ad = meta_live["active_ads"][0]
        m_cite = Citation(
            source="Meta Ads Account",
            object_name="Account 774668588585301",
            date_window_ist=str(meta_live["date_window_ist"]),
            row_count=len(meta_live["active_ads"]),
        )
        cites.append(m_cite)
        live_bits.append(
            f"- **Top Active Meta Creative:** `{top_ad['ad_name']}` (CTR `{top_ad['ctr_pct']}%`, "
            f"CPC `Rs {top_ad['cpc_inr']}`) [Source: Meta Ads Account 774668588585301 · "
            f"{meta_live['date_window_ist']}]"
        )
    if rival_md:
        live_bits.append(rival_md)
    if live_bits:
        numbered_sections.append(
            ("Live Ad & Competitor Creative Snapshot", "\n\n".join(live_bits))
        )

    numbered_sections.append(
        (
            "Key Risks & Confirmation Questions (`<= 3`)",
            "- **Risks:** (1) RTO returns take 10–20 days to settle—gate Phase 1 on CTR, CPC, and "
            "Mixpanel checkout start rate rather than early provisional Net ROAS. "
            "(2) Scaling >3x can fatigue narrow audiences without fresh Reels/Static hooks.\n"
            "- **Please Confirm Before Execution:**\n"
            f"  1. Confirm geographic focus (`{reg_lbl}`) and any pin-code exclusions?\n"
            f"  2. Approve the `{tgt_lbl}` guardrail and Phase 1 -> Phase 2 gate thresholds?\n"
            "  3. Confirm inventory cover & COD/prepaid readiness "
            "for the 14-day A/B creative test?",
        )
    )

    rendered_blocks = [
        f"#### {idx}. {title}\n{body}"
        for idx, (title, body) in enumerate(numbered_sections, start=1)
    ]
    if degraded_sources:
        rendered_blocks.append(
            "#### Optional Live Sources Unavailable (Graceful Degradation)\n"
            + "\n".join(f"- `{s}`" for s in degraded_sources)
        )

    verified = audit_rendered_markdown(
        "\n\n".join(rendered_blocks), banned_words=BANNED_CAUSAL_WORDS
    )
    headline = (
        f"Campaign Brief · {intake.product_query} · "
        f"{format_inr(intake.budget_inr)} · {intake.window_label}"
    )
    return SmritiQueryResponse(
        headline=headline,
        answer_markdown=verified,
        citations=cites,
        degraded_sources=degraded_sources,
        latency_ms=0,
        trace_id=trace_id,
    )
