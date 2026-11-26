"""Mixpanel Live Connector — strictly Read-Only paid sessions & 3-step funnel (`M1`–`M6`)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any, Literal

import httpx

from core.cache import CacheBackend, build_default_cache
from core.runner import ConnectorUnavailableError

PaidChannelFilter = Literal["meta", "google", "all_paid"]
MixpanelStepFetcher = Callable[[str, date, date, str | None, PaidChannelFilter], Awaitable[int]]


class MixpanelRuleViolation(ValueError):
    """Raised when a caller requests forbidden revenue/order events or invalid Mixpanel ranges."""


def compute_cross_source_cvr(
    bq_delivered_orders: int,
    mixpanel_paid_sessions: int,
) -> dict[str, Any]:
    """Compute M6 Cross-source conversion (`BigQuery Delivered Orders / Mixpanel Sessions`)."""
    if bq_delivered_orders < 0 or mixpanel_paid_sessions < 0:
        raise MixpanelRuleViolation("Order and session counts must be non-negative.")
    if mixpanel_paid_sessions == 0:
        return {
            "label": "Cross-source conversion (BigQuery Delivered Orders / Mixpanel Sessions)",
            "bq_delivered_orders": bq_delivered_orders,
            "mixpanel_sessions": 0,
            "cvr_pct": None,
            "display": "No sessions recorded in period",
        }
    pct = round((bq_delivered_orders / mixpanel_paid_sessions) * 100.0, 2)
    return {
        "label": "Cross-source conversion (BigQuery Delivered Orders / Mixpanel Sessions)",
        "bq_delivered_orders": bq_delivered_orders,
        "mixpanel_sessions": mixpanel_paid_sessions,
        "cvr_pct": pct,
        "display": (
            f"{pct:.2f}% ({bq_delivered_orders:,} BQ delivered / "
            f"{mixpanel_paid_sessions:,} MP sessions)"
        ),
    }


def _fmt_step_rate(numerator: int | None, denominator: int | None) -> str:
    if numerator is None or denominator is None:
        return "N/A (pre-cutoff)"
    if denominator <= 0:
        return "No sessions recorded in period"
    return f"{(numerator / denominator) * 100.0:.2f}%"


class MixpanelLiveCollector:
    """Enforces M1..M6 UTM, 1-SKU-per-call fan-out, and 24 Feb / 18 Sep 2026 date boundaries."""

    MIN_START_DATE: date = date(2026, 2, 24)
    CHECKOUT_CUTOFF_DATE: date = date(2026, 9, 18)
    FORBIDDEN_EVENTS: frozenset[str] = frozenset(
        {"Purchase", "Order Placed", "product_purchase", "mp_order_complete", "Revenue"}
    )
    STEP_PRODUCT_VIEW: str = "Page Viewed"
    STEP_BEGIN_CHECKOUT: str = "mp_begin_checkout"
    STEP_PAYMENT_OPTIONS: str = "mp_navigation_payment_options"
    MAX_CONCURRENT_REQUESTS: int = 4  # Mixpanel Query API enforces <=5 concurrent calls/project

    def __init__(
        self,
        *,
        project_id: str | None = None,
        username: str | None = None,
        secret: str | None = None,
        api_host: str | None = None,
        cache: CacheBackend | None = None,
        step_fetcher: MixpanelStepFetcher | None = None,
    ) -> None:
        self._project_id = (
            project_id if project_id is not None else os.getenv("MIXPANEL_PROJECT_ID", "3992118")
        ).strip()
        self._username = (username or os.getenv("MIXPANEL_USERNAME", "")).strip()
        self._secret = (secret or os.getenv("MIXPANEL_SECRET", "")).strip()
        self._api_host = (
            api_host or os.getenv("MIXPANEL_API_HOST", "https://eu.mixpanel.com")
        ).rstrip("/")
        self._cache = cache or build_default_cache()
        self._step_fetcher = step_fetcher
        self._sem = asyncio.Semaphore(self.MAX_CONCURRENT_REQUESTS)

    def assert_event_allowed(self, event_name: str) -> None:
        """Block Purchase/Order/Revenue events (orders come strictly from BigQuery)."""
        lowered = event_name.strip().lower()
        for forbidden in self.FORBIDDEN_EVENTS:
            if lowered == forbidden.lower():
                raise MixpanelRuleViolation(
                    f"Mixpanel event '{event_name}' is forbidden; "
                    "read orders/revenue from BigQuery."
                )

    @staticmethod
    def _build_where_expression(
        *,
        include_products_variant: bool,
        sku: str | None,
        channel: PaidChannelFilter,
    ) -> str:
        clauses: list[str] = []
        if channel == "meta":
            clauses.append('lower(properties["utm_source"]) == "paid"')
            clauses.append('lower(properties["utm_medium"]) == "meta"')
        elif channel == "google":
            clauses.append(
                '(lower(properties["utm_source"]) == "paid" or '
                'lower(properties["utm_source"]) == "google")'
            )
            clauses.append(
                '(lower(properties["utm_medium"]) == "cpc" or '
                'lower(properties["utm_medium"]) == "ppc" or '
                'lower(properties["utm_medium"]) == "google")'
            )
        else:
            clauses.append('lower(properties["utm_source"]) == "paid"')

        if include_products_variant:
            clauses.append('lower(properties["page_variant"]) == "products"')
        if sku:
            safe_sku = sku.replace('"', "")
            clauses.append(f'properties["sku"] == "{safe_sku}"')
        return " and ".join(clauses)

    async def _query_single_raw_event(
        self,
        client: httpx.AsyncClient,
        api_event: str,
        where_expr: str,
        start: date,
        end: date,
    ) -> int:
        params = {
            "project_id": self._project_id,
            "event": api_event,
            "from_date": start.isoformat(),
            "to_date": end.isoformat(),
            "type": "unique",
            "where": where_expr,
        }
        async with self._sem:
            resp = await client.get(
                f"{self._api_host}/api/query/segmentation",
                params=params,
                auth=(self._username, self._secret),
            )
            if resp.status_code == 429:
                await asyncio.sleep(0.8)
                resp = await client.get(
                    f"{self._api_host}/api/query/segmentation",
                    params=params,
                    auth=(self._username, self._secret),
                )
            if resp.status_code == 400:
                return 0
            resp.raise_for_status()
            series = resp.json().get("data", {}).get("values", {}).get(api_event, {})
            return sum(int(v or 0) for v in series.values()) if isinstance(series, dict) else 0

    async def _fetch_segmentation_unique_count(
        self,
        step_name: str,
        start: date,
        end: date,
        sku: str | None,
        channel: PaidChannelFilter,
    ) -> int:
        self.assert_event_allowed(step_name)
        if self._step_fetcher is not None:
            async with self._sem:
                return await self._step_fetcher(step_name, start, end, sku, channel)

        if not (self._project_id and self._username and self._secret):
            raise ConnectorUnavailableError("Mixpanel credentials not configured")

        async with httpx.AsyncClient(timeout=7.0) as client:
            if step_name != self.STEP_PRODUCT_VIEW:
                where_expr = self._build_where_expression(
                    include_products_variant=False, sku=sku, channel=channel
                )
                return await self._query_single_raw_event(
                    client, step_name, where_expr, start, end
                )

            # Query primary event first (keeps concurrent Mixpanel calls at 3 <= 5 limit)
            primary_where = self._build_where_expression(
                include_products_variant=True, sku=sku, channel=channel
            )
            for ev in ("Page Viewed", "mp_page_view"):
                cnt = await self._query_single_raw_event(client, ev, primary_where, start, end)
                if cnt > 0:
                    return cnt

            fb_where = self._build_where_expression(
                include_products_variant=False, sku=sku, channel=channel
            )
            return await self._query_single_raw_event(
                client, "Product Viewed", fb_where, start, end
            )

    async def _sum_across_skus(
        self,
        step_name: str,
        start: date,
        end: date,
        combo_skus: list[str],
        channel: PaidChannelFilter,
    ) -> int:
        """Enforce M4: max 1 SKU filter value per call; fan out in parallel and sum in Python."""
        targets: list[str | None] = [s.strip() for s in combo_skus if s.strip()] or [None]
        counts = await asyncio.gather(
            *(
                self._fetch_segmentation_unique_count(step_name, start, end, sku, channel)
                for sku in targets
            )
        )
        return sum(counts)

    async def fetch_3step_funnel(
        self,
        combo_skus: list[str],
        start: date,
        end: date,
        *,
        channel: PaidChannelFilter = "meta",
    ) -> dict[str, Any]:
        """Fetch verified 3-step funnel enforcing 2026-02-24 & 2026-09-18 IST boundaries."""
        if end < self.MIN_START_DATE or end < start:
            raise MixpanelRuleViolation(
                f"Requested Mixpanel window ({start}..{end}) ends before 2026-02-24 or is inverted."
            )

        notes: list[str] = []
        eff_start = max(start, self.MIN_START_DATE)
        if start < self.MIN_START_DATE:
            notes.append("Start date clipped to 2026-02-24 IST instrumentation boundary.")

        sku_key = ",".join(sorted(combo_skus)) or "ALL"
        cache_key = f"mp_funnel:{channel}:{sku_key}:{eff_start.isoformat()}:{end.isoformat()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        checkout_start: date | None = eff_start
        if end <= self.CHECKOUT_CUTOFF_DATE:
            checkout_start = None
            notes.append("Checkout steps omitted because window ends on/before 2026-09-18 cutoff.")
        elif eff_start <= self.CHECKOUT_CUTOFF_DATE:
            checkout_start = self.CHECKOUT_CUTOFF_DATE + timedelta(days=1)
            notes.append(
                f"Checkout steps computed strictly for {checkout_start.isoformat()} – "
                f"{end.isoformat()} IST (post 2026-09-18 instrumentation cutoff)."
            )

        if checkout_start is None:
            product_views = await self._sum_across_skus(
                self.STEP_PRODUCT_VIEW, eff_start, end, combo_skus, channel
            )
            begin_checkout, payment_reached = None, None
        else:
            product_views, begin_checkout, payment_reached = await asyncio.gather(
                self._sum_across_skus(self.STEP_PRODUCT_VIEW, eff_start, end, combo_skus, channel),
                self._sum_across_skus(
                    self.STEP_BEGIN_CHECKOUT, checkout_start, end, combo_skus, channel
                ),
                self._sum_across_skus(
                    self.STEP_PAYMENT_OPTIONS, checkout_start, end, combo_skus, channel
                ),
            )

        result = {
            "channel": channel,
            "combo_skus": combo_skus,
            "effective_window_ist": f"{eff_start.isoformat()} – {end.isoformat()} IST",
            "checkout_window_ist": (
                f"{checkout_start.isoformat()} – {end.isoformat()} IST" if checkout_start else None
            ),
            "product_page_views": product_views,
            "begin_checkout": begin_checkout,
            "payment_options_reached": payment_reached,
            "view_to_checkout_rate": _fmt_step_rate(begin_checkout, product_views),
            "checkout_to_payment_rate": _fmt_step_rate(payment_reached, begin_checkout),
            "notes": notes,
        }
        self._cache.set(cache_key, result)
        return result
