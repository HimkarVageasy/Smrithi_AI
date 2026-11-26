"""BigQuery warehouse collector (`Gemini_POC`) — sole source of financial & order truth."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from typing import Any

from core.guardrails.sql_ast import DEFAULT_MAX_BYTES_BILLED, validate_readonly_sql

QueryParamTuple = tuple[str, str, Any]  # (name, bq_type, value)
AsyncQueryExecutor = Callable[[str, Sequence[QueryParamTuple]], Awaitable[list[dict[str, Any]]]]


def _serialize_row(raw_row: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in raw_row.items()}


class BigQueryPocCollector:
    """Validated, read-only BigQuery collector locked to allowlisted Gemini_POC views."""

    BASE_VIEWS: frozenset[str] = frozenset(
        {
            "ge_account_monthly", "ge_account_closed_months", "ge_month_status",
            "ge_family_monthly", "ge_product_demand_monthly", "ge_city_demand_monthly",
            "ge_city_product_demand_monthly", "vw_meta_channel_monthly",
            "vw_meta_campaign_monthly", "sales_master_data",
        }
    )

    def __init__(
        self,
        *,
        project_id: str | None = None,
        dataset: str | None = None,
        max_bytes_billed: int = DEFAULT_MAX_BYTES_BILLED,
        timeout_seconds: float = 8.0,
        query_executor: AsyncQueryExecutor | None = None,
    ) -> None:
        self._project_id = (
            project_id or os.getenv("GCP_PROJECT_ID", "gemini-poc-503210")
        ).strip()
        self._dataset = (dataset or os.getenv("BIGQUERY_DATASET", "Gemini_POC")).strip()
        self._max_bytes_billed = max_bytes_billed
        self._timeout_seconds = timeout_seconds
        self._query_executor = query_executor
        self._bq_client: Any = None

        self.allowlisted_tables: frozenset[str] = frozenset(
            {f"{self._dataset}.{v}" for v in self.BASE_VIEWS}
            | {f"{self._project_id}.{self._dataset}.{v}" for v in self.BASE_VIEWS}
        )
        self.pii_restricted_tables: frozenset[str] = frozenset(
            {
                f"{self._dataset}.sales_master_data",
                f"{self._project_id}.{self._dataset}.sales_master_data",
            }
        )

    def _table_ref(self, view_name: str) -> str:
        return f"`{self._project_id}.{self._dataset}.{view_name}`"

    def _get_bq_client(self) -> Any:
        if self._bq_client is None:
            from google.cloud import bigquery  # Lazy import so offline unit tests need zero GCP SDK

            self._bq_client = bigquery.Client(project=self._project_id)
        return self._bq_client

    def _execute_sync_bq(
        self,
        validated_sql: str,
        params: Sequence[QueryParamTuple],
    ) -> list[dict[str, Any]]:
        from google.cloud import bigquery

        bq_params = [
            bigquery.ScalarQueryParameter(name, param_type, value)
            for name, param_type, value in params
        ]
        job_config = bigquery.QueryJobConfig(
            use_query_cache=True,
            maximum_bytes_billed=self._max_bytes_billed,
            query_parameters=bq_params,
        )
        client = self._get_bq_client()
        query_job = client.query(validated_sql, job_config=job_config)
        rows = query_job.result(timeout=self._timeout_seconds)
        return [_serialize_row(dict(row.items())) for row in rows]

    async def run_validated_query(
        self,
        sql: str,
        params: Sequence[QueryParamTuple] = (),
    ) -> list[dict[str, Any]]:
        """Validate SQL via sqlglot AST gate before executing with 24h cache + 500MB cap."""
        validated_sql = validate_readonly_sql(
            sql,
            allowlisted_tables=self.allowlisted_tables,
            pii_restricted_tables=self.pii_restricted_tables,
        )
        if self._query_executor is not None:
            return await self._query_executor(validated_sql, params)

        return await asyncio.wait_for(
            asyncio.to_thread(self._execute_sync_bq, validated_sql, params),
            timeout=self._timeout_seconds,
        )

    async def fetch_account_monthly(self, *, limit_months: int = 6) -> list[dict[str, Any]]:
        """Fetch account-level monthly spend, delivered revenue/orders, and settlement status."""
        acct_tbl = self._table_ref("ge_account_monthly")
        status_tbl = self._table_ref("ge_month_status")
        sql = f"""
        SELECT
            a.month, a.month_name,
            COALESCE(s.settle_state, a.settle_state) AS settle_state,
            COALESCE(s.is_provisional, a.is_provisional) AS is_provisional,
            COALESCE(s.is_latest_closed, FALSE) AS is_latest_closed,
            a.performance_spend, a.brand_spend, a.total_meta_spend,
            a.net_revenue, a.gross_revenue, a.net_orders, a.gross_orders, a.rto_orders,
            a.performance_impressions, a.performance_clicks, a.rto_rate_by_orders
        FROM {acct_tbl} AS a
        LEFT JOIN {status_tbl} AS s ON a.month = s.month
        ORDER BY a.month DESC
        LIMIT @limit_months
        """
        rows = await self.run_validated_query(sql, [("limit_months", "INT64", limit_months)])
        return list(reversed(rows))

    async def fetch_account_closed_months(self, *, limit_months: int = 6) -> list[dict[str, Any]]:
        """Fetch closed-only account months (`ge_account_closed_months`) for trend direction."""
        closed_tbl = self._table_ref("ge_account_closed_months")
        sql = f"""
        SELECT
            month, month_name, settle_state, is_provisional,
            performance_spend, brand_spend, total_meta_spend,
            net_revenue, gross_revenue, net_orders, gross_orders, rto_orders,
            performance_impressions, performance_clicks, rto_rate_by_orders
        FROM {closed_tbl}
        ORDER BY month DESC
        LIMIT @limit_months
        """
        rows = await self.run_validated_query(sql, [("limit_months", "INT64", limit_months)])
        return list(reversed(rows))

    async def fetch_family_monthly(
        self,
        *,
        product_family: str | None = None,
        limit_months: int = 4,
    ) -> list[dict[str, Any]]:
        """Fetch ad-side family x month metrics (`ge_family_monthly`)."""
        fam_tbl = self._table_ref("ge_family_monthly")
        params: list[QueryParamTuple] = [("limit_months", "INT64", limit_months)]
        where_clause = ""
        if product_family:
            where_clause = "WHERE LOWER(product_family) LIKE CONCAT('%', LOWER(@family), '%')"
            params.append(("family", "STRING", product_family.strip()))

        sql = f"""
        WITH recent_months AS (
            SELECT DISTINCT month
            FROM {fam_tbl}
            ORDER BY month DESC
            LIMIT @limit_months
        )
        SELECT
            f.month,
            f.settle_state,
            f.product_family,
            f.campaigns,
            f.spend,
            f.net_revenue,
            f.net_orders,
            f.contribution_before_margin
        FROM {fam_tbl} AS f
        INNER JOIN recent_months AS rm
            ON f.month = rm.month
        {where_clause}
        ORDER BY f.month ASC, f.spend DESC
        """
        return await self.run_validated_query(sql, params)

    async def fetch_product_and_city_demand(
        self,
        *,
        catalogue_product: str | None = None,
        city: str | None = None,
        limit_months: int = 4,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch catalogue product demand and optional city x product demand share."""
        prod_tbl = self._table_ref("ge_product_demand_monthly")
        prod_params: list[QueryParamTuple] = [("limit_months", "INT64", limit_months)]
        prod_filter = ""
        if catalogue_product:
            prod_filter = (
                "WHERE LOWER(catalogue_product) LIKE CONCAT('%', LOWER(@prod), '%')"
            )
            prod_params.append(("prod", "STRING", catalogue_product.strip()))

        prod_sql = f"""
        WITH recent_months AS (
            SELECT DISTINCT month FROM {prod_tbl} ORDER BY month DESC LIMIT @limit_months
        )
        SELECT
            p.month,
            p.catalogue_product,
            SUM(p.net_revenue) AS net_revenue,
            SUM(p.net_orders) AS net_orders,
            SUM(p.gross_orders) AS gross_orders
        FROM {prod_tbl} AS p
        INNER JOIN recent_months AS rm ON p.month = rm.month
        {prod_filter}
        GROUP BY p.month, p.catalogue_product
        ORDER BY p.month ASC, net_orders DESC
        """
        product_rows = await self.run_validated_query(prod_sql, prod_params)

        city_rows: list[dict[str, Any]] = []
        if city:
            city_tbl = self._table_ref("ge_city_product_demand_monthly")
            city_params: list[QueryParamTuple] = [
                ("limit_months", "INT64", limit_months),
                ("city", "STRING", city.strip().upper()),
            ]
            city_prod_filter = ""
            if catalogue_product:
                city_prod_filter = (
                    "AND LOWER(c.catalogue_product) LIKE CONCAT('%', LOWER(@prod), '%')"
                )
                city_params.append(("prod", "STRING", catalogue_product.strip()))

            city_sql = f"""
            WITH recent_months AS (
                SELECT DISTINCT month FROM {city_tbl} ORDER BY month DESC LIMIT @limit_months
            )
            SELECT
                c.month,
                c.city,
                c.catalogue_product,
                SUM(c.net_orders) AS net_orders,
                SUM(c.gross_orders) AS gross_orders,
                SUM(c.net_revenue) AS net_revenue
            FROM {city_tbl} AS c
            INNER JOIN recent_months AS rm ON c.month = rm.month
            WHERE UPPER(c.city) = @city
            {city_prod_filter}
            GROUP BY c.month, c.city, c.catalogue_product
            ORDER BY c.month ASC, net_orders DESC
            """
            city_rows = await self.run_validated_query(city_sql, city_params)

        return {"product_demand": product_rows, "city_demand": city_rows}

    async def fetch_recent_daily_orders(
        self,
        *,
        days: int = 14,
        paid_meta_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch safe non-PII daily order counts (`sales_master_data`) for DoD/WoW or Meta CVR."""
        sales_tbl = self._table_ref("sales_master_data")
        meta_clause = (
            "AND (LOWER(TRIM(utm_medium)) IN ('meta', 'fb', 'ig', 'paid_social') "
            "OR LOWER(TRIM(utm_source)) IN ('meta', 'facebook', 'fb', 'ig') "
            "OR LOWER(TRIM(Order_Source_Bucket)) LIKE '%meta%' "
            "OR LOWER(TRIM(order_source)) LIKE '%meta%')"
            if paid_meta_only
            else ""
        )
        sql = f"""
        SELECT
            Order_Date AS order_date,
            COUNT(DISTINCT sale_order_code) AS gross_orders,
            COUNT(DISTINCT IF(UPPER(Status_) = 'DELIVERED', sale_order_code, NULL)) AS net_orders,
            SUM(
                IF(UPPER(Status_) = 'DELIVERED', COALESCE(selling_price_Exc_GST, 0.0), 0.0)
            ) AS net_revenue
        FROM {sales_tbl}
        WHERE Order_Date >= DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL @days DAY)
        {meta_clause}
        GROUP BY Order_Date
        ORDER BY Order_Date ASC
        """
        return await self.run_validated_query(sql, [("days", "INT64", days)])
