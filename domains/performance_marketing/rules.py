"""Deterministic Performance Marketing business rules, Known Refusals, and grain caveats."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

SettlementStatus = Literal[
    "provisional",
    "settling",
    "mostly settled; ratios can still move",
    "closed",
]

GrainBoundaryKind = Literal["product_roas", "city_roas", "daily_net_roas"]


@dataclass(frozen=True)
class GrainBoundaryCaveat:
    """Identifies an uncomputable sub-grain in a mixed query while allowing valid tables."""

    kind: GrainBoundaryKind
    explanation_markdown: str


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
    """Intercept strictly forbidden/zero-table requests in <1ms before touching BigQuery."""
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

    # 2. Brand Campaign ROAS or CAC (awareness spend is never evaluated on ROAS/CAC).
    if _BRAND_ROAS_CAC_RE.search(q):
        return (
            "**Brand Campaign ROAS & CAC Unavailable:** Brand awareness spend is strictly "
            "excluded from ROAS and CAC denominators because brand campaigns optimize for reach, "
            "not direct conversion.\n\n"
            "- **Valid Alternative:** Ask for **Account Monthly Brand Spend** or live campaign "
            "delivery metrics (**Impressions, Reach, and CPM**)."
        )

    # 3. Creative-level historical warehouse CPM (belongs in live ad connectors, not BigQuery).
    if _CREATIVE_WAREHOUSE_CPM_RE.search(q):
        return (
            "**Creative-Level Historical Warehouse CPM Unavailable:** Curated BigQuery views "
            "aggregate historical spend at account, campaign, and ad-family grain.\n\n"
            "- **Valid Alternative:** Query our **Live Meta Ads (`774668588585301`) & "
            "Google Ads Account connectors** for active creative-level CTR, CPC, and CPM."
        )

    return None


def detect_grain_boundary_caveat(question: str) -> GrainBoundaryCaveat | None:
    """Detect grain boundaries so Smriti answers all valid metrics first + explains the rest."""
    q = question.strip()
    if not q or _PLANNING_INTENT_RE.search(q):
        return None

    if _PRODUCT_ROAS_CAC_RE.search(q):
        return GrainBoundaryCaveat(
            kind="product_roas",
            explanation_markdown=(
                "**Catalogue Product / SKU-Level Spend & ROAS Not Computable:** Paid ad spend is "
                "loaded at **Ad-Family** grain (`Gemini_POC.ge_family_monthly`), not individual "
                "catalogue item or `Combo_SKU` grain, because multi-product campaigns "
                "(`catalogue`, `allproducts`, `healthmonitors`) promote multiple items together. "
                "Above, Smriti answered your request at all valid warehouse grains: **Account MoM "
                "(Spend, Placed Orders, Delivered Orders, Net ROAS)**, **Ad-Family Spend & Net "
                "ROAS**, and **Catalogue Product Placed & Delivered Orders**."
            ),
        )

    if _CITY_STATE_ROAS_CAC_RE.search(q):
        return GrainBoundaryCaveat(
            kind="city_roas",
            explanation_markdown=(
                "**City / State-Level ROAS & CAC Not Computable:** Paid ad spend is not "
                "attributed to delivery cities or states in our warehouse. Above, Smriti "
                "provided **City Placed & Delivered Demand (`ge_city_product_demand_monthly`)** "
                "alongside **National Ad-Family Net ROAS (`ge_family_monthly`)**."
            ),
        )

    if _DAILY_NET_ROAS_CAC_RE.search(q):
        return GrainBoundaryCaveat(
            kind="daily_net_roas",
            explanation_markdown=(
                "**Single-Day Net Delivered ROAS & CAC Not Computable:** Order delivery and RTO "
                "return settlement take days to weeks, making daily Net ROAS/CAC misleading. "
                "Above, Smriti provided **Daily (`DoD`) Placed & Delivered Orders** alongside "
                "**Monthly Account Net ROAS & Settlement Status**."
            ),
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
