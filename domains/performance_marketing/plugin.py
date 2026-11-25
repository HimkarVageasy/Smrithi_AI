"""Performance Marketing domain plugin (`DomainPlugin` implementation — Slice 1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.collectors.bigquery_poc import BigQueryPocCollector
from domains.performance_marketing.demand_presenter import (
    render_daily_orders_report,
    render_demand_report,
)
from domains.performance_marketing.intent_parser import ParsedMarketingQuery, parse_marketing_query
from domains.performance_marketing.kpi_presenter import render_account_and_family_report
from domains.performance_marketing.rules import check_marketing_known_refusal

_IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class PerformanceMarketingPlugin:
    """Domain #1 plugin orchestrating refusals, parallel BigQuery reads, and Python math."""

    domain_id: str = "performance_marketing"

    def __init__(self, *, bq_collector: BigQueryPocCollector | None = None) -> None:
        self._bq = bq_collector or BigQueryPocCollector()

    def check_known_refusal(self, parsed_intent: dict[str, Any]) -> str | None:
        return check_marketing_known_refusal(str(parsed_intent.get("question", "")))

    async def collect_parallel(self, parsed_intent: dict[str, Any]) -> dict[str, Any]:
        now_dt = datetime.now(tz=_IST)
        routed = parse_marketing_query(str(parsed_intent.get("question", "")))

        if routed.focus == "ping":
            return {
                "routed": routed,
                "today_ist": now_dt.date(),
                "collected_at_ist": now_dt.strftime("%d %b %Y %H:%M:%S IST"),
                "degraded_sources": [],
            }

        if routed.focus == "daily_or_weekly_orders":
            daily_rows = await self._bq.fetch_recent_daily_orders(days=routed.window_count)
            return {
                "routed": routed,
                "today_ist": now_dt.date(),
                "daily_rows": daily_rows,
                "degraded_sources": [],
            }

        if routed.focus == "product_or_city_demand":
            demand_bundle = await self._bq.fetch_product_and_city_demand(
                catalogue_product=routed.catalogue_product,
                city=routed.city,
                limit_months=routed.window_count + 1,
            )
            return {
                "routed": routed,
                "today_ist": now_dt.date(),
                "product_rows": demand_bundle["product_demand"],
                "city_rows": demand_bundle["city_demand"],
                "degraded_sources": [],
            }

        # Default & Family focus: fetch Account, Closed Months, and Family views in PARALLEL
        lookback = routed.window_count + 2
        account_rows, closed_rows, family_rows = await asyncio.gather(
            self._bq.fetch_account_monthly(limit_months=lookback),
            self._bq.fetch_account_closed_months(limit_months=lookback),
            self._bq.fetch_family_monthly(
                product_family=routed.product_family,
                limit_months=routed.window_count + 1,
            ),
        )
        return {
            "routed": routed,
            "today_ist": now_dt.date(),
            "account_rows": account_rows,
            "closed_rows": closed_rows,
            "family_rows": family_rows,
            "degraded_sources": [],
        }

    def compute_verified_metrics(
        self,
        parsed_intent: dict[str, Any],
        raw_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **raw_bundle,
            "caller_wif": parsed_intent["caller_wif"],
            "trace_id": parsed_intent["trace_id"],
        }

    async def render_response(self, verified_payload: dict[str, Any]) -> SmritiQueryResponse:
        routed: ParsedMarketingQuery = verified_payload["routed"]
        trace_id = str(verified_payload["trace_id"])

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

        if routed.focus == "daily_or_weekly_orders":
            return render_daily_orders_report(
                daily_rows=verified_payload["daily_rows"],
                grain=routed.grain,
                trace_id=trace_id,
            )

        if routed.focus == "product_or_city_demand":
            return render_demand_report(
                product_rows=verified_payload["product_rows"],
                city_rows=verified_payload["city_rows"],
                city=routed.city,
                catalogue_product=routed.catalogue_product,
                trace_id=trace_id,
            )

        return render_account_and_family_report(
            account_rows=verified_payload["account_rows"],
            closed_rows=verified_payload["closed_rows"],
            family_rows=verified_payload["family_rows"],
            window_months=routed.window_count,
            product_family=routed.product_family,
            today_ist=verified_payload["today_ist"],
            trace_id=trace_id,
        )
