"""Competitor Intelligence Presenter — Golden Scenario #6 (<=50 sample, zero rankings)."""

from __future__ import annotations

from datetime import date
from typing import Any

from core.guardrails.output_audit import audit_rendered_markdown
from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.kpi_presenter import BANNED_CAUSAL_WORDS


def format_rival_creative_block(
    meta_lib: dict[str, Any] | None,
    google_transp: dict[str, Any] | None,
    web_ctx: dict[str, Any] | None,
    today_str: str,
) -> tuple[str, list[Citation]]:
    """Format public rival creative formats and hooks with mandatory Rule F2 caveats."""
    cites: list[Citation] = []
    parts: list[str] = []

    if meta_lib is not None:
        m_cite = Citation(
            source="Meta Ad Library",
            object_name=f"ads_archive ({meta_lib['country']} · '{meta_lib['search_terms']}')",
            date_window_ist=f"Active Snapshot {today_str}",
            row_count=int(meta_lib.get("sampled_count") or 0),
            note=meta_lib.get("caveat"),
        )
        cites.append(m_cite)
        fmt_summary = (
            ", ".join(f"`{k}`: {v}" for k, v in (meta_lib.get("format_mix") or {}).items())
            or "No active ads in sample"
        )
        lines = [
            f"**Meta Ad Library Snapshot** *(from a sample of up to 50 active ads — "
            f"{meta_lib['sampled_count']} active ads found, zero performance metrics)*:",
            f"- **Observed Format Mix:** {fmt_summary}",
        ]
        for cr in (meta_lib.get("sample_creatives") or [])[:4]:
            hook = cr.get("hook_snippet") or cr.get("headline") or "Active creative"
            lines.append(f'- `{cr["advertiser"]}` ({cr["format"]}): "{hook}"')
        lines.append(f"\n[Source: Meta Ad Library {m_cite.object_name} · {m_cite.date_window_ist}]")
        parts.append("\n".join(lines))

    if google_transp is not None:
        g_cite = Citation(
            source="Google Ads Transparency",
            object_name=f"Transparency ({google_transp['region']} · '{google_transp['query']}')",
            date_window_ist=f"Active Snapshot {today_str}",
            row_count=int(google_transp.get("sampled_count") or 0),
            note=google_transp.get("caveat"),
        )
        cites.append(g_cite)
        g_lines = [
            f"**Google Ads Transparency Snapshot** *({google_transp['sampled_count']} active "
            "creatives sampled, zero CPC/performance metrics)*:"
        ]
        for cr in (google_transp.get("sample_creatives") or [])[:4]:
            g_lines.append(f'- `{cr["advertiser"]}` ({cr["format"]}): "{cr["headline"]}"')
        g_lines.append(
            f"\n[Source: Google Ads Transparency {g_cite.object_name} · {g_cite.date_window_ist}]"
        )
        parts.append("\n".join(g_lines))

    if web_ctx is not None and web_ctx.get("snippets"):
        w_cite = Citation(
            source="Google Search",
            object_name=f"Market Context ('{web_ctx['query']}')",
            date_window_ist=f"Snapshot {today_str}",
            row_count=len(web_ctx["snippets"]),
        )
        cites.append(w_cite)
        w_lines = ["**Public Category & Offer Context:**"]
        for sn in web_ctx["snippets"][:3]:
            w_lines.append(f"- **{sn['title']}:** {sn['snippet']}")
        w_lines.append(f"\n[Source: Google Search {w_cite.object_name} · {w_cite.date_window_ist}]")
        parts.append("\n".join(w_lines))

    return "\n\n".join(parts), cites


def render_competitor_intel_report(
    *,
    query_label: str,
    meta_lib: dict[str, Any] | None,
    google_transp: dict[str, Any] | None,
    web_ctx: dict[str, Any] | None,
    degraded_sources: list[str],
    today_ist: date,
    trace_id: str,
) -> SmritiQueryResponse:
    """Render Golden Scenario #6 Rival Ad Library Audit without performance rankings."""
    today_str = f"{today_ist.strftime('%d %b %Y')} IST"
    rival_md, cites = format_rival_creative_block(meta_lib, google_transp, web_ctx, today_str)

    sections: list[str] = []
    if rival_md:
        sections.append(rival_md)
    else:
        fallback_cite = Citation(
            source="Meta Ad Library",
            object_name=f"ads_archive (IN · '{query_label}')",
            date_window_ist=today_str,
            row_count=0,
            note="Live rival connector unconfigured or returned 0 ads.",
        )
        cites.append(fallback_cite)
        sections.append(
            f"No live rival creative feed returned for `{query_label}` (check connector status "
            "below). Public ad libraries provide active creative formats and messaging hooks only, "
            "from a sample of up to 50 active ads, with zero spend or performance rankings.\n\n"
            f"[Source: Meta Ad Library {fallback_cite.object_name} · {today_str}]"
        )

    if degraded_sources:
        deg_list = "\n".join(f"- `{s}`" for s in degraded_sources)
        sections.append(f"#### Connector Availability Note\n{deg_list}")

    verified = audit_rendered_markdown("\n\n".join(sections), banned_words=BANNED_CAUSAL_WORDS)
    return SmritiQueryResponse(
        headline=f"Competitor Creative Audit · {query_label} · India",
        answer_markdown=verified,
        citations=cites,
        degraded_sources=degraded_sources,
        latency_ms=0,
        trace_id=trace_id,
    )
