"""Offline unit tests for `core/guardrails/sql_ast.py` (`LOW_LEVEL_DESIGN.md` §7)."""

from __future__ import annotations

import pytest

from core.guardrails.sql_ast import SqlGuardrailViolation, validate_readonly_sql

ALLOWLIST = frozenset(
    {
        "Gemini_POC.ge_account_monthly",
        "Gemini_POC.ge_account_closed_months",
        "Gemini_POC.ge_month_status",
        "Gemini_POC.ge_family_monthly",
        "Gemini_POC.ge_product_demand_monthly",
        "Gemini_POC.ge_city_demand_monthly",
        "Gemini_POC.ge_city_product_demand_monthly",
        "Gemini_POC.sales_master_data",
    }
)
PII_TABLES = frozenset({"Gemini_POC.sales_master_data"})


def test_accepts_valid_allowlisted_select_and_cte() -> None:
    sql = """
    WITH recent AS (
        SELECT family, spend, net_revenue
        FROM `my-gcp-proj.Gemini_POC.ge_family_monthly`
    )
    SELECT family, SUM(net_revenue) AS rev
    FROM recent
    GROUP BY family
    """
    validated = validate_readonly_sql(
        sql,
        allowlisted_tables=ALLOWLIST,
        pii_restricted_tables=PII_TABLES,
    )
    assert "ge_family_monthly" in validated


@pytest.mark.parametrize(
    "malicious_sql",
    [
        "DELETE FROM Gemini_POC.ge_family_monthly WHERE 1=1",
        "DROP TABLE Gemini_POC.sales_master_data",
        "INSERT INTO Gemini_POC.ge_family_monthly (family) VALUES ('x')",
        "UPDATE Gemini_POC.ge_family_monthly SET spend = 0 WHERE 1=1",
        (
            "MERGE Gemini_POC.ge_family_monthly t USING Gemini_POC.ge_month_status s "
            "ON FALSE WHEN NOT MATCHED THEN INSERT ROW"
        ),
        "SELECT family FROM Gemini_POC.ge_family_monthly; DROP TABLE Gemini_POC.ge_family_monthly",
    ],
)
def test_blocks_ddl_dml_and_multi_statement_queries(malicious_sql: str) -> None:
    with pytest.raises(SqlGuardrailViolation):
        validate_readonly_sql(malicious_sql, allowlisted_tables=ALLOWLIST)


def test_blocks_unallowlisted_tables() -> None:
    sql = "SELECT * FROM `other_dataset.raw_customer_secrets`"
    with pytest.raises(SqlGuardrailViolation, match="allowlist"):
        validate_readonly_sql(sql, allowlisted_tables=ALLOWLIST)


@pytest.mark.parametrize(
    "pii_sql",
    [
        "SELECT Combo_SKU, customer_name FROM Gemini_POC.sales_master_data",
        "SELECT Combo_SKU FROM Gemini_POC.sales_master_data WHERE phone = '9876543210'",
        "SELECT email, shipping_address FROM Gemini_POC.sales_master_data",
        "SELECT * FROM Gemini_POC.sales_master_data LIMIT 10",
    ],
)
def test_blocks_pii_columns_and_star_on_pii_tables(pii_sql: str) -> None:
    with pytest.raises(SqlGuardrailViolation):
        validate_readonly_sql(
            pii_sql,
            allowlisted_tables=ALLOWLIST,
            pii_restricted_tables=PII_TABLES,
        )
