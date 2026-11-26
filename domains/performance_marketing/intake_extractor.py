"""Deterministic Campaign Plan Intake Extractor (`Rule #22` assumed tags & premise labels)."""

from __future__ import annotations

import calendar
import re
from datetime import date

from domains.performance_marketing.schemas import CampaignPlanIntake

_LAKH_CRORE_RE = re.compile(
    r"(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(crores?|crs?|lakhs?|lacs?|l|k)\b",
    re.IGNORECASE,
)
_RUPEE_PLAIN_RE = re.compile(
    r"(?:rs\.?|inr|₹)\s*([\d,]{4,})",
    re.IGNORECASE,
)
_TARGET_ROAS_RE = re.compile(
    r"(?:target(?:ing)?\s+(?:net\s+)?roas(?:\s+of)?\s*(\d+(?:\.\d+)?)x?|"
    r"(\d+(?:\.\d+)?)\s*x\s*(?:net\s+|delivered\s+)?roas)",
    re.IGNORECASE,
)
_TARGET_CAC_RE = re.compile(
    r"target(?:ing)?\s+(?:max\s+|net\s+)?cac(?:\s+of)?\s*(?:rs\.?|₹|inr)?\s*([\d,]+)",
    re.IGNORECASE,
)
_PREMISE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("air quality", "Winter air quality / AQI spike"),
    ("aqi", "Winter AQI spike"),
    ("pollution", "Seasonal air pollution demand"),
    ("smog", "Seasonal smog respiratory demand"),
    ("winter", "Winter seasonal demand"),
    ("diwali", "Diwali festive demand window"),
    ("festive", "Festive shopping window"),
    ("monsoon", "Monsoon seasonal demand"),
)


def _next_month_label(today_ist: date) -> str:
    year = today_ist.year + (1 if today_ist.month == 12 else 0)
    month = 1 if today_ist.month == 12 else today_ist.month + 1
    return f"{calendar.month_name[month]} {year} (assumed)"


def extract_campaign_intake(
    question: str,
    *,
    today_ist: date,
    matched_product: str | None = None,
    matched_city: str | None = None,
) -> CampaignPlanIntake:
    """Deterministically extract CampaignPlanIntake and tag assumed defaults (Rule #22)."""
    q = question.strip()
    lowered = q.lower()

    budget_inr = 300_000
    lc_match = _LAKH_CRORE_RE.search(q)
    plain_match = _RUPEE_PLAIN_RE.search(q)
    if lc_match:
        num = float(lc_match.group(1))
        unit = lc_match.group(2).lower()
        mult = 10_000_000 if unit.startswith("c") else (1_000 if unit == "k" else 100_000)
        budget_inr = max(1_000, int(round(num * mult)))
    elif plain_match:
        digits = plain_match.group(1).replace(",", "")
        if digits.isdigit():
            budget_inr = max(1_000, int(digits))

    target_roas: float | None = None
    target_cac: float | None = None
    target_assumed = True
    roas_m = _TARGET_ROAS_RE.search(q)
    cac_m = _TARGET_CAC_RE.search(q)
    if roas_m:
        raw_r = roas_m.group(1) or roas_m.group(2)
        target_roas = float(raw_r)
        target_assumed = False
    elif cac_m:
        raw_c = cac_m.group(1).replace(",", "")
        target_cac = float(raw_c)
        target_assumed = False

    if matched_city:
        region = matched_city
        region_assumed = False
    elif "all india" in lowered or "pan india" in lowered or "national" in lowered:
        region = "All India"
        region_assumed = False
    else:
        region = "All India"
        region_assumed = True

    window_label = _next_month_label(today_ist)
    for m_idx in range(1, 13):
        m_name = calendar.month_name[m_idx]
        if m_name.lower() in lowered:
            yr = today_ist.year + (1 if m_idx < today_ist.month else 0)
            window_label = f"{m_name} {yr}"
            break
    else:
        if "winter" in lowered:
            window_label = f"Winter ({_next_month_label(today_ist).replace(' (assumed)', '')})"

    premise: str | None = None
    for kw, label in _PREMISE_KEYWORDS:
        if kw in lowered:
            premise = label
            break

    return CampaignPlanIntake(
        product_query=matched_product or "allproducts",
        region=region,
        region_assumed=region_assumed,
        budget_inr=budget_inr,
        target_roas=target_roas,
        target_cac_inr=target_cac,
        target_assumed=target_assumed,
        window_label=window_label,
        external_premise=premise,
    )
