"""Deterministic intent & entity parser for Performance Marketing queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from core.router import TimeGrainOption, extract_time_spec
from domains.performance_marketing.entity_lexicon import (
    is_campaign_planning_query,
    resolve_city,
    resolve_product_entities,
)
from domains.performance_marketing.rules import GrainBoundaryCaveat, detect_grain_boundary_caveat

QueryFocus = Literal[
    "ping",
    "memory_save",
    "memory_recall",
    "campaign_plan",
    "competitor_intel",
    "account_and_family_mom",
    "family_focus",
    "product_or_city_demand",
    "daily_or_weekly_orders",
    "live_diagnostic",
    "product_roas_hybrid",
    "city_roas_hybrid",
    "daily_roas_hybrid",
]

_PING_RE = re.compile(
    r"^\s*(?:ping(?:\s+smriti(?:\s+v2)?)?|health\s*check)[!\s.?]*$",
    re.IGNORECASE,
)

_MEMORY_SAVE_RE = re.compile(
    r"^\s*(?:please\s+)?(?:save(?:\s+this)?(?:\s+to)?(?:\s+smriti)?\s+"
    r"(?:memory|approved\s+plan|approved\s+decision|approved\s+brief|learning|rule)|"
    r"remember\s+this\s+(?:approved\s+)?(?:learning|rule|decision)|"
    r"record\s+(?:this\s+)?(?:campaign\s+)?(?:learning|decision))\b",
    re.IGNORECASE,
)

_MEMORY_RECALL_RE = re.compile(
    r"\b("
    r"smriti\s+memory|institutional\s+memory|saved\s+(?:learnings?|decisions?|plans?|rules?|brds?)|"
    r"past\s+(?:brds?|post[-\s]?mortems?|learnings?)|post[-\s]?mortems?|channel\s+rulesets?|"
    r"excel\s+rulesets?|media\s+rulesets?|what\s+worked\s+(?:last|in\s+past)|"
    r"what\s+did\s+we\s+learn|recall\s+(?:memory|learnings?)"
    r")\b",
    re.IGNORECASE,
)

_COMPETITOR_INTEL_RE = re.compile(
    r"\b("
    r"competitor|competitors|rival|rivals|ad\s+library|meta\s+library|facebook\s+library|"
    r"fb\s+ad\s+library|ads?\s+transparency|google\s+transparency|ad\s+center|"
    r"rival\s+ads?|competitor\s+ads?|competitor\s+creatives?|other\s+brands?|"
    r"who\s+else\s+is\s+(?:advertising|running)|benchmark\s+creatives?|"
    r"(?:friends|dignity|karein|omron|dr\.?\s*morepen|dr\.?\s*trust|beato|vissco|frido|"
    r"seniority|caresmith|agaro)\b.*\b(?:ads?|creatives?|hooks?|offers?|running|campaigns?)"
    r")\b",
    re.IGNORECASE,
)

_LIVE_DIAGNOSTIC_RE = re.compile(
    r"\b("
    r"mixpanel|funnel|drop[-\s]?off|dropping\s+off|cart\s+abandonment|checkout|"
    r"payment\s+options|product\s+page\s+views?|website\s+traffic|website\s+conversion|"
    r"cross[-\s]source\s+cvr|session|sessions|"
    r"live\s+ads?|live\s+campaigns?|active\s+ads?|active\s+campaigns?|active\s+creatives?|"
    r"running\s+ads?|current\s+ads?|creative\s+ctr|opportunity\s+score|live\s+diagnostic|"
    r"live\s+pulse|ad\s+account\s+health|ads\s+manager|meta\s+account"
    r")\b",
    re.IGNORECASE,
)

_DEMAND_RE = re.compile(
    r"\b("
    r"city\s+demand|product\s+demand|catalogue\s+product|catalogue\s+item|demand\s+share|"
    r"demand\s+breakdown|orders?\s+in|orders?\s+by\s+city|orders?\s+by\s+state|"
    r"orders?\s+by\s+product|delivered\s+orders?\s+by\s+product|top[-\s]selling|"
    r"best[-\s]selling|top\s+products?|units?\s+delivered|which\s+cities"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedMarketingQuery:
    """Structured intent extracted deterministically in <1ms."""

    focus: QueryFocus
    grain: TimeGrainOption
    window_count: int
    product_family: str | None = None
    catalogue_product: str | None = None
    city: str | None = None
    boundary_caveat: GrainBoundaryCaveat | None = None


def parse_marketing_query(question: str) -> ParsedMarketingQuery:
    """Classify marketing warehouse query into focus, time grain, entities, and caveats."""
    q = question.strip()
    if _PING_RE.match(q):
        return ParsedMarketingQuery(focus="ping", grain="MoM", window_count=1)

    time_spec = extract_time_spec(q, default_months=3)
    lowered = q.lower()
    prod = resolve_product_entities(q)
    matched_family = prod.product_family
    matched_catalogue = prod.catalogue_product
    matched_city = resolve_city(q)

    if _MEMORY_SAVE_RE.search(q):
        return ParsedMarketingQuery(
            focus="memory_save",
            grain="MoM",
            window_count=1,
            product_family=matched_family,
            catalogue_product=matched_catalogue,
            city=matched_city,
        )

    if is_campaign_planning_query(q):
        return ParsedMarketingQuery(
            focus="campaign_plan",
            grain="MoM",
            window_count=4,
            product_family=matched_family,
            catalogue_product=matched_catalogue,
            city=matched_city,
        )

    if _MEMORY_RECALL_RE.search(q):
        return ParsedMarketingQuery(
            focus="memory_recall",
            grain="MoM",
            window_count=1,
            product_family=matched_family,
            catalogue_product=matched_catalogue,
            city=matched_city,
        )

    if _COMPETITOR_INTEL_RE.search(q):
        return ParsedMarketingQuery(
            focus="competitor_intel",
            grain="MoM",
            window_count=1,
            product_family=matched_family,
            catalogue_product=matched_catalogue,
            city=matched_city,
        )

    caveat = detect_grain_boundary_caveat(q)
    if caveat is not None:
        if caveat.kind == "product_roas":
            return ParsedMarketingQuery(
                focus="product_roas_hybrid",
                grain="MoM",
                window_count=max(3, time_spec.window_count),
                product_family=matched_family,
                catalogue_product=matched_catalogue,
                boundary_caveat=caveat,
            )
        if caveat.kind == "city_roas":
            return ParsedMarketingQuery(
                focus="city_roas_hybrid",
                grain="MoM",
                window_count=max(3, time_spec.window_count),
                product_family=matched_family,
                catalogue_product=matched_catalogue,
                city=matched_city,
                boundary_caveat=caveat,
            )
        if caveat.kind == "daily_net_roas":
            return ParsedMarketingQuery(
                focus="daily_roas_hybrid",
                grain="DoD",
                window_count=14,
                product_family=matched_family,
                catalogue_product=matched_catalogue,
                boundary_caveat=caveat,
            )

    if _LIVE_DIAGNOSTIC_RE.search(q):
        return ParsedMarketingQuery(
            focus="live_diagnostic",
            grain=time_spec.grain,
            window_count=28,
            product_family=matched_family,
            catalogue_product=matched_catalogue,
            city=matched_city,
        )

    if time_spec.grain in {"DoD", "WoW"}:
        return ParsedMarketingQuery(
            focus="daily_or_weekly_orders",
            grain=time_spec.grain,
            window_count=time_spec.window_count if time_spec.grain == "DoD" else 28,
            product_family=matched_family,
            catalogue_product=matched_catalogue,
            city=matched_city,
        )

    if matched_city or _DEMAND_RE.search(q):
        return ParsedMarketingQuery(
            focus="product_or_city_demand",
            grain=time_spec.grain,
            window_count=max(3, time_spec.window_count),
            product_family=matched_family,
            catalogue_product=matched_catalogue,
            city=matched_city,
        )

    if matched_family and "account" not in lowered:
        return ParsedMarketingQuery(
            focus="family_focus",
            grain=time_spec.grain,
            window_count=max(3, time_spec.window_count),
            product_family=matched_family,
            catalogue_product=matched_catalogue,
        )

    return ParsedMarketingQuery(
        focus="account_and_family_mom",
        grain=time_spec.grain,
        window_count=max(3, time_spec.window_count),
        product_family=matched_family,
        catalogue_product=matched_catalogue,
    )
