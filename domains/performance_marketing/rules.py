"""Deterministic Performance Marketing business rules, Known Refusals, and settlement flags."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

SettlementStatus = Literal[
    "provisional",
    "settling",
    "mostly settled; ratios can still move",
    "closed",
]

_PLANNING_INTENT_RE = re.compile(
    r"\b(plan\s+a|media\s+plan|campaign\s+plan|campaign\s+brief|design\s+a\s+campaign|"
    r"need\s+to\s+run|want\s+to\s+run|need\s+to\s+launch|rs\.?\s*\d|₹\s*\d|inr\s*\d)\b",
    re.IGNORECASE,
)

_WRITE_MUTATION_RE = re.compile(
    r"\b("
    r"(pause|unpause|resume|delete|remove|archive|disable|deactivate|turn\s+off|stop)\s+"
    r"(?:(?:this|these|the|our|my|all|active|live|running)\s+)*"
    r"(ad|ads|adset|adsets|ad\s+set|campaign|campaigns)|"
    r"(edit|modify|update|change|increase|decrease|raise|lower|set)\s+"
    r"(?:(?:this|these|the|our|my|all|active|live|daily)\s+)*"
    r"(ad\s+copy|bid|bids|daily\s+budget|live\s+budget|campaign\s+budget|budget)|"
    r"(publish|push)\s+(?:(?:this|these|the)\s+)*(ad|campaign)\s+(?:directly\s+)?(in|to|into)\s+"
    r"(meta|facebook|google)"
    r")\b",
    re.IGNORECASE,
)

_PRODUCT_ROAS_CAC_RE = re.compile(
    r"("
    r"\b(product[-\s]level|sku[-\s]level|per[-\s]product|per[-\s]sku|product[-\s]wise|sku[-\s]wise|"
    r"by\s+product|by\s+sku|catalogue\s+product|each\s+product|each\s+sku)\b.*\b(roas|cac)\b|"
    r"\b(roas|cac)\b.*\b(by\s+product|by\s+sku|per\s+product|per\s+sku|product[-\s]level|"
    r"sku[-\s]level|product[-\s]wise|sku[-\s]wise|for\s+each\s+product|for\s+each\s+sku|"
    r"aenb\d+)\b"
    r")",
    re.IGNORECASE,
)

_CITY_STATE_ROAS_CAC_RE = re.compile(
    r"("
    r"\b(city[-\s]level|state[-\s]level|city[-\s]wise|state[-\s]wise|by\s+city|by\s+state|"
    r"per\s+city|per\s+state|pincode[-\s]level)\b.*\b(roas|cac)\b|"
    r"\b(roas|cac)\b.*\b(by\s+city|by\s+state|per\s+city|per\s+state|city[-\s]level|"
    r"state[-\s]level|city[-\s]wise|state[-\s]wise)\b|"
    r"\b(delhi|mumbai|bengaluru|bangalore|hyderabad|chennai|kolkata|pune|ahmedabad|noida|"
    r"gurgaon|gurugram|jaipur|lucknow)\s+(net\s+|delivered\s+)?(roas|cac)\b|"
    r"\b(roas|cac)\s+(in|for|of)\s+(delhi|mumbai|bengaluru|bangalore|hyderabad|chennai|"
    r"kolkata|pune|ahmedabad|noida|gurgaon|gurugram|jaipur|lucknow)\b"
    r")",
    re.IGNORECASE,
)

_DAILY_NET_ROAS_CAC_RE = re.compile(
    r"("
    r"\b(daily|day[-\s]on[-\s]day|dod|yesterday'?s|today'?s)\s+"
    r"(net\s+|delivered\s+)?(roas|cac)\b|"
    r"\b(net\s+roas|delivered\s+roas|net\s+cac|delivered\s+cac)\b.*\b(daily|day[-\s]on[-\s]day|"
    r"by\s+day|per\s+day|dod)\b"
    r")",
    re.IGNORECASE,
)

_BRAND_ROAS_CAC_RE = re.compile(
    r"("
    r"\bbrand(\s+awareness|\s+campaign|\s+campaigns)?\s+(net\s+|delivered\s+)?(roas|cac)\b|"
    r"\b(roas|cac)\s+(of|for|on)\s+(our\s+|the\s+)?brand(\s+awareness|\s+campaign|\s+campaigns)?\b"
    r")",
    re.IGNORECASE,
)

_CREATIVE_WAREHOUSE_CPM_RE = re.compile(
    r"("
    r"\bcreative[-\s]level\b.*\b(warehouse|bigquery|historical)\b.*\bcpm\b|"
    r"\b(warehouse|bigquery|historical)\b.*\bcreative[-\s]level\b.*\bcpm\b"
    r")",
    re.IGNORECASE,
)


def check_marketing_known_refusal(question: str) -> str | None:
    """Intercept impossible or mutating requests in <1ms with explanation + valid alternative."""
    q = question.strip()
    if not q:
        return None

    # 1. Explicit ad-platform write/mutation block (never block "need to run / plan a campaign").
    if _WRITE_MUTATION_RE.search(q) and not _PLANNING_INTENT_RE.search(q):
        return (
            "**Read-Only Guardrail:** Smriti never creates, edits, pauses, or mutates live ads, "
            "budgets, or warehouse records.\n\n"
            "- **Valid Alternative:** I can generate a **Read-Only Campaign Brief & Phased Budget "
            "Plan** or run a **Live Ad Diagnostic** so your team can review and apply changes "
            "directly in Meta Ads Manager or Google Ads."
        )

    # 2. Product-level / SKU-level ROAS or CAC.
    if _PRODUCT_ROAS_CAC_RE.search(q):
        return (
            "**Product/SKU-Level ROAS & CAC Unavailable:** Paid ad spend is tracked at "
            "**ad-family** grain (`Gemini_POC.ge_family_monthly`), not individual catalogue SKU "
            "or `Product_` grain (and `allproducts` campaigns span multiple SKUs).\n\n"
            "- **Valid Alternatives Available Immediately:**\n"
            "  1. **Ad-Family Net ROAS & Net CAC** "
            "(`Gemini_POC.ge_family_monthly`, e.g., `nebulizer`, `allproducts`)\n"
            "  2. **Catalogue Product Delivered Orders & Revenue** "
            "(`Gemini_POC.ge_product_demand_monthly`)"
        )

    # 3. City-level or State-level ROAS / CAC (ignore campaign brief prompts with target ROAS).
    if _CITY_STATE_ROAS_CAC_RE.search(q) and not _PLANNING_INTENT_RE.search(q):
        return (
            "**City/State-Level ROAS & CAC Unavailable:** Delivered order attribution to paid ad "
            "spend is not modeled at city or state grain in our warehouse.\n\n"
            "- **Valid Alternatives Available Immediately:**\n"
            "  1. **City Delivered Orders & Product Demand Share** "
            "(`Gemini_POC.ge_city_product_demand_monthly`)\n"
            "  2. **National Ad-Family Net ROAS & Net CAC** (`Gemini_POC.ge_family_monthly`)"
        )

    # 4. Daily Net ROAS or Daily Net CAC.
    if _DAILY_NET_ROAS_CAC_RE.search(q):
        return (
            "**Daily Net ROAS & Daily Net CAC Unavailable:** Order delivery and RTO return "
            "settlement take days to weeks, making single-day Net ROAS/CAC misleading.\n\n"
            "- **Valid Alternatives Available Immediately:**\n"
            "  1. **Daily Spend, Impressions, CTR, CPC, Paid Sessions & Placed Orders (`DoD`)**\n"
            "  2. **Closed-Month / Monthly Net ROAS & Net CAC** "
            "(`Gemini_POC.ge_account_closed_months`)"
        )

    # 5. Brand Campaign ROAS or CAC.
    if _BRAND_ROAS_CAC_RE.search(q):
        return (
            "**Brand Campaign ROAS & CAC Unavailable:** Brand awareness spend is strictly "
            "excluded from ROAS and CAC denominators because brand campaigns optimize for reach, "
            "not direct conversion.\n\n"
            "- **Valid Alternative:** I can report **Brand Spend, Impressions, Reach, and CPM**."
        )

    # 6. Creative-level historical warehouse CPM.
    if _CREATIVE_WAREHOUSE_CPM_RE.search(q):
        return (
            "**Creative-Level Historical Warehouse CPM Unavailable:** Curated BigQuery views "
            "aggregate historical spend at account, campaign, and ad-family grain.\n\n"
            "- **Valid Alternative:** I can query our **Live Meta Ads (`774668588585301`) & "
            "Google Ads Account connectors** for active creative-level CTR, CPC, and CPM."
        )

    return None


def classify_month_settlement(
    target_month_first: date,
    *,
    today_ist: date,
    warehouse_status: str | None = None,
) -> SettlementStatus:
    """Classify month settlement status per Rule #10 (`provisional` / `settling` / `closed`)."""
    months_diff = (today_ist.year - target_month_first.year) * 12 + (
        today_ist.month - target_month_first.month
    )
    if months_diff <= 0:
        return "provisional"

    if warehouse_status:
        lowered = warehouse_status.strip().lower()
        if lowered == "provisional":
            return "provisional"
        if lowered == "settling":
            return "settling"
        if "mostly settled" in lowered:
            return "mostly settled; ratios can still move"
        if lowered == "closed":
            return "closed"

    if months_diff == 1:
        if today_ist.day < 20:
            return "settling"
        return "mostly settled; ratios can still move"

    return "closed"
