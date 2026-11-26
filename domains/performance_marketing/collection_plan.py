"""Builds parallel CollectorTask lists for Performance Marketing intents (`core/runner.py`)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

from core.runner import CollectorTask
from domains.performance_marketing.collectors.bigquery_poc import BigQueryPocCollector
from domains.performance_marketing.collectors.google_ad_transparency import (
    GoogleAdTransparencyCollector,
)
from domains.performance_marketing.collectors.google_ads_account import GoogleAdsAccountCollector
from domains.performance_marketing.collectors.meta_ad_library import MetaAdLibraryCollector
from domains.performance_marketing.collectors.meta_ads_account import MetaAdsAccountCollector
from domains.performance_marketing.collectors.mixpanel_live import MixpanelLiveCollector
from domains.performance_marketing.collectors.web_competitor import WebCompetitorCollector
from domains.performance_marketing.intent_parser import ParsedMarketingQuery


def _task(
    name: str,
    coro_fn: Callable[[], Awaitable[Any]],
    *,
    critical: bool = True,
) -> CollectorTask:
    return CollectorTask(name=name, coro_factory=coro_fn, critical=critical)


def build_collection_tasks(
    routed: ParsedMarketingQuery,
    *,
    question: str,
    today_ist: date,
    bq: BigQueryPocCollector,
    mixpanel: MixpanelLiveCollector,
    meta_ads: MetaAdsAccountCollector,
    google_ads: GoogleAdsAccountCollector,
    meta_lib: MetaAdLibraryCollector,
    google_transp: GoogleAdTransparencyCollector,
    web_comp: WebCompetitorCollector,
) -> list[CollectorTask]:
    """Assemble concurrent read-only tasks per routed intent."""
    end_yday = today_ist - timedelta(days=1)
    start_28d = end_yday - timedelta(days=27)
    search_term = routed.product_family or "senior care health devices"

    if routed.focus == "competitor_intel":
        tasks = [
            _task(
                "Meta Ad Library",
                lambda: meta_lib.search_active_rival_ads([search_term]),
                critical=False,
            )
        ]
        if google_transp.is_enabled:
            tasks.append(
                _task(
                    "Google Ads Transparency",
                    lambda: google_transp.search_active_rival_creatives(search_term),
                    critical=False,
                )
            )
        if web_comp.is_configured:
            tasks.append(
                _task(
                    "Google Search",
                    lambda: web_comp.fetch_market_context(search_term),
                    critical=False,
                )
            )
        return tasks

    if routed.focus == "campaign_plan":
        tasks = [
            _task("bq_closed", lambda: bq.fetch_account_closed_months(limit_months=4)),
            _task(
                "bq_family",
                lambda: bq.fetch_family_monthly(
                    product_family=routed.product_family, limit_months=4
                ),
            ),
            _task(
                "bq_demand",
                lambda: bq.fetch_product_and_city_demand(
                    catalogue_product=routed.catalogue_product,
                    city=routed.city,
                    limit_months=4,
                ),
            ),
            _task(
                "Mixpanel Live",
                lambda: mixpanel.fetch_3step_funnel([], start_28d, end_yday, channel="meta"),
                critical=False,
            ),
            _task(
                "Meta Ads Account",
                lambda: meta_ads.fetch_live_ads_and_opportunity_score(routed.product_family),
                critical=False,
            ),
            _task(
                "Meta Ad Library",
                lambda: meta_lib.search_active_rival_ads([search_term]),
                critical=False,
            ),
        ]
        if google_ads.is_enabled:
            tasks.append(
                _task(
                    "Google Ads Account",
                    lambda: google_ads.fetch_live_campaigns_and_search_terms(
                        routed.product_family
                    ),
                    critical=False,
                )
            )
        if google_transp.is_enabled:
            tasks.append(
                _task(
                    "Google Ads Transparency",
                    lambda: google_transp.search_active_rival_creatives(search_term),
                    critical=False,
                )
            )
        return tasks

    if routed.focus == "live_diagnostic":
        tasks = [
            _task("bq_account", lambda: bq.fetch_account_monthly(limit_months=3)),
            _task(
                "bq_daily_orders",
                lambda: bq.fetch_recent_daily_orders(days=28, paid_meta_only=True),
            ),
            _task(
                "Mixpanel Live",
                lambda: mixpanel.fetch_3step_funnel([], start_28d, end_yday, channel="meta"),
                critical=False,
            ),
            _task(
                "Meta Ads Account",
                lambda: meta_ads.fetch_live_ads_and_opportunity_score(routed.product_family),
                critical=False,
            ),
        ]
        if google_ads.is_enabled:
            tasks.append(
                _task(
                    "Google Ads Account",
                    lambda: google_ads.fetch_live_campaigns_and_search_terms(
                        routed.product_family
                    ),
                    critical=False,
                )
            )
        return tasks

    if routed.focus in {"daily_or_weekly_orders", "daily_roas_hybrid"}:
        tasks = [_task("bq_daily", lambda: bq.fetch_recent_daily_orders(days=routed.window_count))]
        if routed.focus == "daily_roas_hybrid":
            tasks.append(_task("bq_account", lambda: bq.fetch_account_monthly(limit_months=4)))
        return tasks

    if routed.focus in {"product_or_city_demand", "city_roas_hybrid"}:
        tasks = [
            _task(
                "bq_demand",
                lambda: bq.fetch_product_and_city_demand(
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
                    lambda: bq.fetch_family_monthly(
                        product_family=routed.product_family,
                        limit_months=routed.window_count + 1,
                    ),
                )
            )
        return tasks

    lookback = routed.window_count + 2
    tasks = [
        _task("bq_account", lambda: bq.fetch_account_monthly(limit_months=lookback)),
        _task("bq_closed", lambda: bq.fetch_account_closed_months(limit_months=lookback)),
        _task(
            "bq_family",
            lambda: bq.fetch_family_monthly(
                product_family=routed.product_family,
                limit_months=routed.window_count + 1,
            ),
        ),
    ]
    if routed.focus == "product_roas_hybrid":
        tasks.append(
            _task(
                "bq_demand",
                lambda: bq.fetch_product_and_city_demand(
                    catalogue_product=routed.catalogue_product,
                    city=None,
                    limit_months=routed.window_count + 1,
                ),
            )
        )
    return tasks
