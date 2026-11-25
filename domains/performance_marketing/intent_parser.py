"""Deterministic intent & entity parser for Performance Marketing queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from core.router import TimeGrainOption, extract_time_spec

QueryFocus = Literal[
    "ping",
    "account_and_family_mom",
    "family_focus",
    "product_or_city_demand",
    "daily_or_weekly_orders",
]

_PING_RE = re.compile(r"^\s*ping(\s+smriti(\s+v2)?)?[!\s.?]*$", re.IGNORECASE)

_KNOWN_FAMILIES: tuple[str, ...] = (
    "nebulizer",
    "allproducts",
    "walker",
    "rollator",
    "wheelchair",
    "knee",
    "lumbar",
    "backrest",
    "hearing",
    "oximeter",
    "bp monitor",
    "thermometer",
    "diaper",
    "underpad",
    "commode",
    "stick",
    "cane",
)

_KNOWN_CITIES: tuple[str, ...] = (
    "delhi",
    "mumbai",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "chennai",
    "kolkata",
    "pune",
    "ahmedabad",
    "noida",
    "gurgaon",
    "gurugram",
    "jaipur",
    "lucknow",
)

_DEMAND_RE = re.compile(
    r"\b(city\s+demand|product\s+demand|catalogue\s+product|demand\s+share|orders\s+in|"
    r"orders\s+by\s+city|orders\s+by\s+product|delivered\s+orders\s+by\s+product)\b",
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


def parse_marketing_query(question: str) -> ParsedMarketingQuery:
    """Classify marketing warehouse query into focus, time grain, and entity filters."""
    q = question.strip()
    if _PING_RE.match(q):
        return ParsedMarketingQuery(focus="ping", grain="MoM", window_count=1)

    time_spec = extract_time_spec(q, default_months=3)
    lowered = q.lower()

    matched_family: str | None = None
    for fam in _KNOWN_FAMILIES:
        if fam in lowered:
            matched_family = fam
            break

    matched_city: str | None = None
    for city in _KNOWN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", lowered):
            matched_city = "BENGALURU" if city == "bangalore" else (
                "GURUGRAM" if city == "gurgaon" else city.upper()
            )
            break

    if time_spec.grain in {"DoD", "WoW"}:
        return ParsedMarketingQuery(
            focus="daily_or_weekly_orders",
            grain=time_spec.grain,
            window_count=14 if time_spec.grain == "DoD" else 28,
            product_family=matched_family,
            city=matched_city,
        )

    if matched_city or _DEMAND_RE.search(q):
        return ParsedMarketingQuery(
            focus="product_or_city_demand",
            grain=time_spec.grain,
            window_count=max(3, time_spec.window_count),
            product_family=matched_family,
            catalogue_product=matched_family,
            city=matched_city,
        )

    if matched_family and "account" not in lowered:
        return ParsedMarketingQuery(
            focus="family_focus",
            grain=time_spec.grain,
            window_count=max(3, time_spec.window_count),
            product_family=matched_family,
        )

    return ParsedMarketingQuery(
        focus="account_and_family_mom",
        grain=time_spec.grain,
        window_count=max(3, time_spec.window_count),
        product_family=matched_family,
    )
