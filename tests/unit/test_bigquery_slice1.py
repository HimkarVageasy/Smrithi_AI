"""Slice 1 end-to-end offline tests: BigQuery collector, SUM/SUM reports, and output guardrails."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.app import create_app
from core.guardrails.output_audit import (
    OutputGuardrailViolation,
    audit_rendered_markdown,
    scrub_pii_text,
)
from core.guardrails.sql_ast import SqlGuardrailViolation
from domains.base import DomainRegistry
from domains.performance_marketing.collectors.bigquery_poc import (
    BigQueryPocCollector,
    QueryParamTuple,
)
from domains.performance_marketing.plugin import PerformanceMarketingPlugin


def _build_mock_executor() -> tuple[BigQueryPocCollector, list[str]]:
    executed_queries: list[str] = []

    async def _fake_executor(
        validated_sql: str,
        params: Sequence[QueryParamTuple],
    ) -> list[dict[str, Any]]:
        executed_queries.append(validated_sql)
        lowered = validated_sql.lower()

        if "ge_account_closed_months" in lowered:
            return [
                {
                    "month": "2026-10-01",
                    "month_name": "Oct 2026",
                    "settle_state": "mostly settled",
                    "is_provisional": False,
                    "performance_spend": 400_000.0,
                    "brand_spend": 50_000.0,
                    "net_revenue": 1_000_000.0,
                    "net_orders": 500,
                },
                {
                    "month": "2026-09-01",
                    "month_name": "Sep 2026",
                    "settle_state": "closed",
                    "is_provisional": False,
                    "performance_spend": 300_000.0,
                    "brand_spend": 40_000.0,
                    "net_revenue": 780_000.0,
                    "net_orders": 390,
                },
                {
                    "month": "2026-08-01",
                    "month_name": "Aug 2026",
                    "settle_state": "closed",
                    "is_provisional": False,
                    "performance_spend": 300_000.0,
                    "brand_spend": 30_000.0,
                    "net_revenue": 600_000.0,
                    "net_orders": 300,
                },
            ]

        if "ge_account_monthly" in lowered:
            return [
                {
                    "month": "2026-11-01",
                    "month_name": "Nov 2026",
                    "settle_state": "provisional",
                    "is_provisional": True,
                    "performance_spend": 200_000.0,
                    "brand_spend": 20_000.0,
                    "net_revenue": 640_000.0,
                    "net_orders": 320,
                },
                {
                    "month": "2026-10-01",
                    "month_name": "Oct 2026",
                    "settle_state": "mostly settled",
                    "is_provisional": False,
                    "performance_spend": 400_000.0,
                    "brand_spend": 50_000.0,
                    "net_revenue": 1_000_000.0,
                    "net_orders": 500,
                },
                {
                    "month": "2026-09-01",
                    "month_name": "Sep 2026",
                    "settle_state": "closed",
                    "is_provisional": False,
                    "performance_spend": 300_000.0,
                    "brand_spend": 40_000.0,
                    "net_revenue": 780_000.0,
                    "net_orders": 390,
                },
                {
                    "month": "2026-08-01",
                    "month_name": "Aug 2026",
                    "settle_state": "closed",
                    "is_provisional": False,
                    "performance_spend": 300_000.0,
                    "brand_spend": 30_000.0,
                    "net_revenue": 600_000.0,
                    "net_orders": 300,
                },
            ]

        if "ge_family_monthly" in lowered:
            return [
                {
                    "month": "2026-10-01",
                    "settle_state": "mostly settled",
                    "product_family": "nebulizer",
                    "campaigns": 3,
                    "spend": 63_000.0,
                    "net_revenue": 189_000.0,
                    "net_orders": 126,
                },
                {
                    "month": "2026-11-01",
                    "settle_state": "provisional",
                    "product_family": "nebulizer",
                    "campaigns": 3,
                    "spend": 40_000.0,
                    "net_revenue": 160_000.0,
                    "net_orders": 100,
                },
            ]

        if "ge_city_product_demand_monthly" in lowered:
            return [
                {
                    "month": "2026-10-01",
                    "city": "DELHI",
                    "catalogue_product": "Nebulizer",
                    "net_orders": 48,
                    "gross_orders": 55,
                    "net_revenue": 72_000.0,
                }
            ]

        if "ge_product_demand_monthly" in lowered:
            return [
                {
                    "month": "2026-10-01",
                    "catalogue_product": "Nebulizer",
                    "net_orders": 210,
                    "gross_orders": 240,
                    "net_revenue": 315_000.0,
                }
            ]

        if "sales_master_data" in lowered:
            return [
                {
                    "order_date": "2026-11-23",
                    "gross_orders": 50,
                    "net_orders": 35,
                    "net_revenue": 52_500.0,
                },
                {
                    "order_date": "2026-11-24",
                    "gross_orders": 60,
                    "net_orders": 40,
                    "net_revenue": 60_000.0,
                },
            ]

        return []

    collector = BigQueryPocCollector(query_executor=_fake_executor)
    return collector, executed_queries


def test_golden_scenario_1_three_month_mom_account_and_family_trend() -> None:
    collector, queries = _build_mock_executor()
    registry = DomainRegistry()
    registry.register(PerformanceMarketingPlugin(bq_collector=collector), is_default=True)
    client = TestClient(create_app(registry=registry))

    resp = client.post(
        "/v1/query",
        json={"question": "Show 3-month MoM account and family ROAS trend"},
    )
    assert resp.status_code == 200
    body = resp.json()
    md = body["answer_markdown"]

    # Closed Perf Spend = 300k + 300k + 400k = 10,00,000
    # Closed Net Rev = 600k + 780k + 1000k = 23,80,000 -> 2.38x (excludes Nov & Brand spend)
    assert len(queries) == 3
    assert "`provisional`" in md
    assert "`mostly settled; ratios can still move`" in md
    assert "Rs 10,00,000" in md
    assert "Rs 23,80,000" in md
    assert "2.38x" in md
    assert "`nebulizer`" in md
    assert "[Source: BigQuery Gemini_POC.ge_account_monthly" in md
    assert body["latency_ms"] < 5000


def test_golden_scenario_2_product_roas_trap_intercepts_with_zero_sql_queries() -> None:
    collector, queries = _build_mock_executor()
    registry = DomainRegistry()
    registry.register(PerformanceMarketingPlugin(bq_collector=collector), is_default=True)
    client = TestClient(create_app(registry=registry))

    resp = client.post("/v1/query", json={"question": "Delivered ROAS by product"})
    assert resp.status_code == 200
    assert len(queries) == 0
    assert "Product/SKU-Level ROAS" in resp.json()["answer_markdown"]


def test_city_demand_and_dod_order_flows() -> None:
    collector, _ = _build_mock_executor()
    registry = DomainRegistry()
    registry.register(PerformanceMarketingPlugin(bq_collector=collector), is_default=True)
    client = TestClient(create_app(registry=registry))

    city_resp = client.post(
        "/v1/query",
        json={"question": "Show Nebulizer demand in Delhi for last 3 months"},
    )
    assert city_resp.status_code == 200
    assert "`DELHI`" in city_resp.json()["answer_markdown"]

    dod_resp = client.post("/v1/query", json={"question": "Show DoD orders for last week"})
    assert dod_resp.status_code == 200
    assert "20.0% (up)" in dod_resp.json()["answer_markdown"]


@pytest.mark.asyncio
async def test_collector_blocks_real_sales_master_data_pii_columns() -> None:
    collector, _ = _build_mock_executor()
    for pii_col in ("Phone_", "notification_email", "address_line_1", "employee_details"):
        bad_sql = (
            f"SELECT sale_order_code, {pii_col} "
            "FROM `gemini-poc-503210.Gemini_POC.sales_master_data`"
        )
        with pytest.raises(SqlGuardrailViolation):
            await collector.run_validated_query(bad_sql)


def test_output_guardrail_scrubs_pii_and_blocks_causal_words() -> None:
    raw = "Contact +91 9876543210 or buyer@gmail.com [Source: BigQuery view · Oct 2026 IST]"
    scrubbed = scrub_pii_text(raw)
    assert "9876543210" not in scrubbed
    assert "buyer@gmail.com" not in scrubbed

    with pytest.raises(OutputGuardrailViolation, match="profitable"):
        audit_rendered_markdown(
            "Campaign is profitable [Source: BigQuery view · Oct 2026 IST]",
            banned_words=frozenset({"caused", "drove", "profitable"}),
        )
