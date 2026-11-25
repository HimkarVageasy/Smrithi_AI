"""Read-only SQL AST validator, table allowlist gate, and PII projection blocker (`sqlglot`)."""

from __future__ import annotations

from collections.abc import Set as AbstractSet

import sqlglot
from sqlglot import exp

DEFAULT_MAX_BYTES_BILLED: int = 500_000_000  # 500 MB safety cap per warehouse query

DEFAULT_FORBIDDEN_PII_COLUMNS: frozenset[str] = frozenset(
    {
        "customer_name",
        "first_name",
        "last_name",
        "full_name",
        "recipient_name",
        "buyer_name",
        "phone",
        "phone_",
        "phone_number",
        "mobile",
        "mobile_number",
        "contact_number",
        "whatsapp_number",
        "email",
        "email_address",
        "customer_email",
        "notification_email",
        "address",
        "street_address",
        "shipping_address",
        "billing_address",
        "address_line1",
        "address_line2",
        "address_line_1",
        "address_line_2",
        "pincode",
        "postal_code",
        "zip_code",
        "employee_details",
    }
)

_FORBIDDEN_STATEMENT_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Merge,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Set,
    exp.LoadData,
    exp.Export,
)


class SqlGuardrailViolation(ValueError):
    """Raised when a SQL query violates read-only, table-allowlist, or PII invariants."""


def _normalize_table_identifier(table: exp.Table) -> tuple[str, str]:
    """Return (full_lower, dataset_table_lower) for allowlist matching."""
    parts = [p for p in (table.catalog, table.db, table.name) if p]
    full_name = ".".join(parts).lower()
    dataset_table = ".".join(parts[-2:]).lower() if len(parts) >= 2 else full_name
    return full_name, dataset_table


def validate_readonly_sql(
    sql: str,
    *,
    allowlisted_tables: AbstractSet[str],
    pii_restricted_tables: AbstractSet[str] = frozenset(),
    extra_forbidden_columns: AbstractSet[str] = frozenset(),
) -> str:
    """Validate BigQuery SQL is a single read-only SELECT on allowlisted views without PII."""
    raw = sql.strip()
    if not raw:
        raise SqlGuardrailViolation("SQL query cannot be empty.")

    try:
        statements = [stmt for stmt in sqlglot.parse(raw, read="bigquery") if stmt is not None]
    except sqlglot.errors.ParseError as exc:
        raise SqlGuardrailViolation(f"Invalid BigQuery SQL syntax: {exc}") from exc

    if len(statements) != 1:
        raise SqlGuardrailViolation(
            f"Exactly 1 SELECT statement is permitted; received {len(statements)} statements."
        )

    root = statements[0]
    if not isinstance(root, (exp.Select, exp.Union)):
        raise SqlGuardrailViolation(
            f"Only SELECT queries are permitted; rejected root statement '{type(root).__name__}'."
        )

    for forbidden_cls in _FORBIDDEN_STATEMENT_TYPES:
        if root.find(forbidden_cls) is not None:
            raise SqlGuardrailViolation(
                f"Forbidden mutating/admin SQL construct '{forbidden_cls.__name__}' detected."
            )

    # Collect CTE aliases so WITH-clauses are not mistaken for physical warehouse tables.
    cte_aliases = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE) if cte.alias_or_name}

    normalized_allowlist = {t.strip().lower() for t in allowlisted_tables if t.strip()}
    normalized_pii_tables = {t.strip().lower() for t in pii_restricted_tables if t.strip()}

    touches_pii_table = False
    referenced_tables = list(root.find_all(exp.Table))
    if not referenced_tables:
        raise SqlGuardrailViolation("SQL query must reference at least one allowlisted table/view.")

    for table in referenced_tables:
        if not table.db and not table.catalog and table.name.lower() in cte_aliases:
            continue
        full_name, dataset_table = _normalize_table_identifier(table)
        if full_name not in normalized_allowlist and dataset_table not in normalized_allowlist:
            raise SqlGuardrailViolation(
                f"Table '{full_name}' is not in the approved read-only allowlist."
            )
        if full_name in normalized_pii_tables or dataset_table in normalized_pii_tables:
            touches_pii_table = True

    if touches_pii_table and root.find(exp.Star) is not None:
        raise SqlGuardrailViolation(
            "Wildcard 'SELECT *' is forbidden on PII-sensitive tables; "
            "project safe columns explicitly."
        )

    blocked_columns = DEFAULT_FORBIDDEN_PII_COLUMNS | {
        col.strip().lower() for col in extra_forbidden_columns if col.strip()
    }
    for column in root.find_all(exp.Column):
        col_name = column.name.strip().lower()
        if col_name in blocked_columns:
            raise SqlGuardrailViolation(
                f"PII column '{column.name}' is strictly blocked at the SQL projection/filter gate."
            )

    return raw
