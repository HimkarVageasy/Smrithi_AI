"""Performance Marketing domain plugin (`DomainPlugin` implementation — Slice 2)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from core.runner import CollectorTask, run_with_timeouts
from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.collectors.bigquery_poc import BigQueryPocCollector
from domains.performance_marketing.collectors.google_ads_account import GoogleAdsAccountCollector
from domains.performance_marketing.collectors.meta_ads_account import MetaAdsAccountCollector
from domains.performance_marketing.collectors.mixpanel_live import MixpanelLiveCollector
from domains.performance_marketing.demand_presenter import (
    render_daily_orders_report,
    render_demand_report,
)
from domains.performance_marketing.intent_parser import ParsedMarketingQuery, parse_marketing_query
from domains.performance_marketing.kpi_presenter import render_account_and_family_report
from domains.performance_marketing.live_presenter import render_live_diagnostic_report
from domains.performance_marketing.rules import check_marketing_known_refusal

_IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _task(
    name: str,
    coro_fn: Callable[[], Awaitable[Any]],
    *,
    critical: bool = True,
) -> CollectorTask:
    return CollectorTask(name=name, coro_factory=coro_fn, critical=critical)


class PerformanceMarketingPlugin:
    """Domain #1 plugin orchestrating refusals, parallel collectors, and Python math."""

    domain_id: str = "performance_marketing"

    def __init__(
        self,
        *,
        bq_collector: BigQueryPocCollector | None = None,
        mixpanel_collector: MixpanelLiveCollector | None = None,
        meta_collector: MetaAdsAccountCollector | None = None,
        google_collector: GoogleAdsAccountCollector | None = None,
    ) -> None:
        self._bq = bq_collector or BigQueryPocCollector()
        self._mixpanel = mixpanel_collector or MixpanelLiveCollector()
        self._meta = meta_collector or MetaAdsAccountCollector()
        self._google = google_collector or GoogleAdsAccountCollector()

    def check_known_refusal(self, parsed_intent: dict[str, Any]) -> str | None:
        return check_marketing_known_refusal(str(parsed_intent.get("question", "")))

    async def collect_parallel(self, parsed_intent: dict[str, Any]) -> dict[str, Any]:
        now_dt = datetime.now(tz=_IST)
        today_ist = now_dt.date()
        routed = parse_marketing_query(str(parsed_intent.get("question", "")))

        if routed.focus == "ping":
            return {
                "routed": routed,
                "today_ist": today_ist,
                "collected_at_ist": now_dt.strftime("%d %b %Y %H:%M:%S IST"),
                "degraded_sources": [],
            }

        if routed.focus == "live_diagnostic":
            end_yday = today_ist - timedelta(days=1)
            start_28d = end_yday - timedelta(days=27)
            tasks = [
                _task("bq_account", lambda: self._bq.fetch_account_monthly(limit_months=3)),
                _task("bq_daily_orders", lambda: self._bq.fetch_recent_daily_orders(days=28)),
                _task(
                    "Mixpanel Live",
                    lambda: self._mixpanel.fetch_3step_funnel(
                        [], start_28d, end_yday, channel="meta"
                    ),
                    critical=False,
                ),
                _task(
                    "Meta Ads Account",
                    lambda: self._meta.fetch_live_ads_and_opportunity_score(routed.product_family),
                    critical=False,
                ),
            ]
            if self._google.is_enabled:
                tasks.append(
                    _task(
                        "Google Ads Account",
                        lambda: self._google.fetch_live_campaigns_and_search_terms(
                            routed.product_family
                        ),
                        critical=False,
                    )
                )
            res = await run_with_timeouts(tasks)
            return {
                "routed": routed,
                "today_ist": today_ist,
                "account_rows": res.results["bq_account"],
                "daily_rows": res.results["bq_daily_orders"],
                "mixpanel_bundle": res.results.get("Mixpanel Live"),
                "meta_bundle": res.results.get("Meta Ads Account"),
                "google_bundle": res.results.get("Google Ads Account"),
                "degraded_sources": res.degraded_sources,
            }

        if routed.focus in {"daily_or_weekly_orders", "daily_roas_hybrid"}:
            tasks = [
                _task(
                    "bq_daily",
                    lambda: self._bq.fetch_recent_daily_orders(days=routed.window_count),
                )
            ]
            if routed.focus == "daily_roas_hybrid":
                tasks.append(
                    _task("bq_account", lambda: self._bq.fetch_account_monthly(limit_months=4))
                )
            res = await run_with_timeouts(tasks)
            return {
                "routed": routed,
                "today_ist": today_ist,
                "daily_rows": res.results["bq_daily"],
                "account_rows": res.results.get("bq_account"),
                "degraded_sources": [],
            }

        if routed.focus in {"product_or_city_demand", "city_roas_hybrid"}:
            tasks = [
                _task(
                    "bq_demand",
                    lambda: self._bq.fetch_product_and_city_demand(
                        catalogue_product=routed.catalogue_product,
                        city=routed.city,
                        limit_months=routed.window_count + 1,
                    ),
                )
            ]
            if routed.focus == "city_roas_hybrid":
                tasks.append(
                    _task(
                        "bq_family",
                        lambda: self._bq.fetch_family_monthly(
                            product_family=routed.product_family,
                            limit_months=routed.window_count + 1,
                        ),
                    )
                )
            res = await run_with_timeouts(tasks)
            demand_bundle = res.results["bq_demand"]
            return {
                "routed": routed,
                "today_ist": today_ist,
                "product_rows": demand_bundle["product_demand"],
                "city_rows": demand_bundle["city_demand"],
                "family_rows": res.results.get("bq_family") or [],
                "degraded_sources": [],
            }

        lookback = routed.window_count + 2
        tasks = [
            _task("bq_account", lambda: self._bq.fetch_account_monthly(limit_months=lookback)),
            _task(
                "bq_closed",
                lambda: self._bq.fetch_account_closed_months(limit_months=lookback),
            ),
            _task(
                "bq_family",
                lambda: self._bq.fetch_family_monthly(
                    product_family=routed.product_family,
                    limit_months=routed.window_count + 1,
                ),
            ),
        ]
        if routed.focus == "product_roas_hybrid":
            tasks.append(
                _task(
                    "bq_demand",
                    lambda: self._bq.fetch_product_and_city_demand(
                        catalogue_product=routed.catalogue_product,
                        city=None,
                        limit_months=routed.window_count + 1,
                    ),
                )
            )
        res = await run_with_timeouts(tasks)
        demand = res.results.get("bq_demand") or {"product_demand": []}
        return {
            "routed": routed,
            "today_ist": today_ist,
            "account_rows": res.results["bq_account"],
            "closed_rows": res.results["bq_closed"],
            "family_rows": res.results["bq_family"],
            "product_rows": demand["product_demand"],
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

        if routed.focus == "live_diagnostic":
            return render_live_diagnostic_report(
                account_rows=verified_payload["account_rows"],
                recent_daily_orders=verified_payload["daily_rows"],
                mixpanel_bundle=verified_payload.get("mixpanel_bundle"),
                meta_bundle=verified_payload.get("meta_bundle"),
                google_bundle=verified_payload.get("google_bundle"),
                degraded_sources=verified_payload.get("degraded_sources", []),
                product_family=routed.product_family,
                today_ist=verified_payload["today_ist"],
                trace_id=trace_id,
            )

        if routed.focus in {"daily_or_weekly_orders", "daily_roas_hybrid"}:
            return render_daily_orders_report(
                daily_rows=verified_payload["daily_rows"],
                grain=routed.grain,
                trace_id=trace_id,
                account_rows=verified_payload.get("account_rows"),
                today_ist=verified_payload["today_ist"],
                boundary_note=caveat_md,
            )

        if routed.focus in {"product_or_city_demand", "city_roas_hybrid"}:
            return render_demand_report(
                product_rows=verified_payload["product_rows"],
                city_rows=verified_payload["city_rows"],
                city=routed.city,
                catalogue_product=routed.catalogue_product,
                trace_id=trace_id,
                family_rows=verified_payload.get("family_rows"),
                today_ist=verified_payload["today_ist"],
                boundary_note=caveat_md,
            )

        return render_account_and_family_report(
            account_rows=verified_payload["account_rows"],
            closed_rows=verified_payload["closed_rows"],
            family_rows=verified_payload["family_rows"],
            window_months=routed.window_count,
            product_family=routed.product_family,
            today_ist=verified_payload["today_ist"],
            trace_id=trace_id,
            product_demand_rows=verified_payload.get("product_rows"),
            boundary_note=caveat_md,
        )
