"""Performance Marketing Supervisor / DomainPlugin orchestrator (Slices 0–3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.runner import run_with_timeouts
from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.campaign_planner import (
    compute_campaign_strategy,
    extract_campaign_intake,
)
from domains.performance_marketing.collection_plan import build_collection_tasks
from domains.performance_marketing.collectors.bigquery_poc import BigQueryPocCollector
from domains.performance_marketing.collectors.google_ad_transparency import (
    GoogleAdTransparencyCollector,
)
from domains.performance_marketing.collectors.google_ads_account import GoogleAdsAccountCollector
from domains.performance_marketing.collectors.meta_ad_library import MetaAdLibraryCollector
from domains.performance_marketing.collectors.meta_ads_account import MetaAdsAccountCollector
from domains.performance_marketing.collectors.mixpanel_live import MixpanelLiveCollector
from domains.performance_marketing.collectors.web_competitor import WebCompetitorCollector
from domains.performance_marketing.competitor_presenter import render_competitor_intel_report
from domains.performance_marketing.demand_presenter import (
    render_daily_orders_report,
    render_demand_report,
)
from domains.performance_marketing.intent_parser import ParsedMarketingQuery, parse_marketing_query
from domains.performance_marketing.kpi_presenter import render_account_and_family_report
from domains.performance_marketing.live_presenter import render_live_diagnostic_report
from domains.performance_marketing.plan_presenter import render_campaign_plan_report
from domains.performance_marketing.rules import check_marketing_known_refusal

_IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class PerformanceMarketingPlugin:
    """Domain #1 Supervisor orchestrating refusals, parallel collectors, strategy math & reports."""

    domain_id: str = "performance_marketing"

    def __init__(
        self,
        *,
        bq_collector: BigQueryPocCollector | None = None,
        mixpanel_collector: MixpanelLiveCollector | None = None,
        meta_collector: MetaAdsAccountCollector | None = None,
        google_collector: GoogleAdsAccountCollector | None = None,
        meta_library_collector: MetaAdLibraryCollector | None = None,
        google_transparency_collector: GoogleAdTransparencyCollector | None = None,
        web_competitor_collector: WebCompetitorCollector | None = None,
    ) -> None:
        self._bq = bq_collector or BigQueryPocCollector()
        self._mixpanel = mixpanel_collector or MixpanelLiveCollector()
        self._meta = meta_collector or MetaAdsAccountCollector()
        self._google = google_collector or GoogleAdsAccountCollector()
        self._meta_lib = meta_library_collector or MetaAdLibraryCollector()
        self._google_transp = google_transparency_collector or GoogleAdTransparencyCollector()
        self._web_comp = web_competitor_collector or WebCompetitorCollector()

    def check_known_refusal(self, parsed_intent: dict[str, Any]) -> str | None:
        return check_marketing_known_refusal(str(parsed_intent.get("question", "")))

    async def collect_parallel(self, parsed_intent: dict[str, Any]) -> dict[str, Any]:
        now_dt = datetime.now(tz=_IST)
        today_ist = now_dt.date()
        question = str(parsed_intent.get("question", ""))
        routed = parse_marketing_query(question)

        if routed.focus == "ping":
            return {
                "question": question,
                "routed": routed,
                "today_ist": today_ist,
                "collected_at_ist": now_dt.strftime("%d %b %Y %H:%M:%S IST"),
                "results": {},
                "degraded_sources": [],
            }

        tasks = build_collection_tasks(
            routed,
            question=question,
            today_ist=today_ist,
            bq=self._bq,
            mixpanel=self._mixpanel,
            meta_ads=self._meta,
            google_ads=self._google,
            meta_lib=self._meta_lib,
            google_transp=self._google_transp,
            web_comp=self._web_comp,
        )
        run_res = await run_with_timeouts(tasks)
        return {
            "question": question,
            "routed": routed,
            "today_ist": today_ist,
            "results": run_res.results,
            "degraded_sources": run_res.degraded_sources,
        }

    def compute_verified_metrics(
        self,
        parsed_intent: dict[str, Any],
        raw_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        routed: ParsedMarketingQuery = raw_bundle["routed"]
        results: dict[str, Any] = raw_bundle["results"]
        today_ist = raw_bundle["today_ist"]

        strategy: dict[str, Any] | None = None
        if routed.focus == "campaign_plan":
            intake = extract_campaign_intake(
                raw_bundle["question"],
                today_ist=today_ist,
                matched_product=routed.product_family,
                matched_city=routed.city,
            )
            strategy = compute_campaign_strategy(
                intake,
                family_rows=results.get("bq_family") or [],
                closed_account_rows=results.get("bq_closed") or [],
                today_ist=today_ist,
                google_ads_enabled=self._google.is_enabled,
            )

        return {
            **raw_bundle,
            "strategy": strategy,
            "caller_wif": parsed_intent["caller_wif"],
            "trace_id": parsed_intent["trace_id"],
        }

    async def render_response(self, verified_payload: dict[str, Any]) -> SmritiQueryResponse:
        routed: ParsedMarketingQuery = verified_payload["routed"]
        res: dict[str, Any] = verified_payload["results"]
        degraded: list[str] = verified_payload["degraded_sources"]
        today_ist = verified_payload["today_ist"]
        trace_id = str(verified_payload["trace_id"])
        caveat_md = routed.boundary_caveat.explanation_markdown if routed.boundary_caveat else None

        if routed.focus == "ping":
            collected_at = str(verified_payload["collected_at_ist"])
            caller_wif = str(verified_payload["caller_wif"])
            citation = Citation(
                source="Smriti Gateway",
                object_name=f"domains.{self.domain_id} (Connectivity Ping)",
                date_window_ist=collected_at,
                row_count=1,
            )
            answer_md = (
                f"**Hello Smriti v2** — Cloud Run high-code engine is online.\n\n"
                f"- **Normalized User ID:** `{caller_wif}`\n"
                f"- **Active Domain:** `{self.domain_id}`\n"
                f"- **Trace ID:** `{trace_id}`\n\n"
                f"[Source: {citation.source} {citation.object_name} · {citation.date_window_ist}]"
            )
            return SmritiQueryResponse(
                headline=f"System Connectivity Ping · {self.domain_id}",
                answer_markdown=answer_md,
                citations=[citation],
                degraded_sources=[],
                latency_ms=0,
                trace_id=trace_id,
            )

        if routed.focus == "competitor_intel":
            return render_competitor_intel_report(
                query_label=routed.product_family or "senior care health devices",
                meta_lib=res.get("Meta Ad Library"),
                google_transp=res.get("Google Ads Transparency"),
                web_ctx=res.get("Google Search"),
                degraded_sources=degraded,
                today_ist=today_ist,
                trace_id=trace_id,
            )

        if routed.focus == "campaign_plan":
            demand = res.get("bq_demand") or {"product_demand": [], "city_demand": []}
            return render_campaign_plan_report(
                strategy=verified_payload["strategy"],
                family_rows=res.get("bq_family") or [],
                product_rows=demand["product_demand"],
                city_rows=demand["city_demand"],
                mixpanel_bundle=res.get("Mixpanel Live"),
                meta_live=res.get("Meta Ads Account"),
                meta_lib=res.get("Meta Ad Library"),
                google_transp=res.get("Google Ads Transparency"),
                degraded_sources=degraded,
                today_ist=today_ist,
                trace_id=trace_id,
            )

        if routed.focus == "live_diagnostic":
            return render_live_diagnostic_report(
                account_rows=res["bq_account"],
                recent_daily_orders=res["bq_daily_orders"],
                mixpanel_bundle=res.get("Mixpanel Live"),
                meta_bundle=res.get("Meta Ads Account"),
                google_bundle=res.get("Google Ads Account"),
                degraded_sources=degraded,
                product_family=routed.product_family,
                today_ist=today_ist,
                trace_id=trace_id,
            )

        if routed.focus in {"daily_or_weekly_orders", "daily_roas_hybrid"}:
            return render_daily_orders_report(
                daily_rows=res["bq_daily"],
                grain=routed.grain,
                trace_id=trace_id,
                account_rows=res.get("bq_account"),
                today_ist=today_ist,
                boundary_note=caveat_md,
            )

        if routed.focus in {"product_or_city_demand", "city_roas_hybrid"}:
            demand = res["bq_demand"]
            return render_demand_report(
                product_rows=demand["product_demand"],
                city_rows=demand["city_demand"],
                city=routed.city,
                catalogue_product=routed.catalogue_product,
                trace_id=trace_id,
                family_rows=res.get("bq_family") or [],
                today_ist=today_ist,
                boundary_note=caveat_md,
            )

        demand = res.get("bq_demand") or {"product_demand": []}
        return render_account_and_family_report(
            account_rows=res["bq_account"],
            closed_rows=res["bq_closed"],
            family_rows=res["bq_family"],
            window_months=routed.window_count,
            product_family=routed.product_family,
            today_ist=today_ist,
            trace_id=trace_id,
            product_demand_rows=demand["product_demand"],
            boundary_note=caveat_md,
        )
