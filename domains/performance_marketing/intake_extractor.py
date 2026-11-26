"""Deterministic Campaign Plan Intake Extractor (`Rule #22` assumed tags & premise labels)."""

from __future__ import annotations

import calendar
import re
from datetime import date

from domains.performance_marketing.entity_lexicon import (
    extract_inr_amount,
    resolve_city,
    resolve_product_entities,
)
from domains.performance_marketing.schemas import CampaignPlanIntake

_TARGET_ROAS_RE = re.compile(
    r"(?:"
    r"(?:target(?:ing)?|aim(?:ing)?\s+for|goal\s+of|at\s+least)\s+(?:a\s+)?(?:net\s+|delivered\s+)?"
    r"roas(?:\s+of)?\s*(\d+(?:\.\d+)?)x?|"
    r"roas\s+(?:target|goal|guardrail)(?:\s+of|\s*:)?\s*(\d+(?:\.\d+)?)x?|"
    r"\b(\d+(?:\.\d+)?)\s*x\s*(?:net\s+|delivered\s+)?roas\b"
    r")",
    re.IGNORECASE,
)
_TARGET_CAC_RE = re.compile(
    r"(?:"
    r"(?:target(?:ing)?\s+)?(?:max(?:imum)?\s+|net\s+|delivered\s+)?cac"
    r"(?:\s+(?:target|goal|of|under|below|at|:))+\s*(?:rs\.?|₹|inr|rupees?)?\s*([\d,]+)|"
    r"target(?:ing)?\s+(?:max\s+|net\s+)?cac\s*(?:rs\.?|₹|inr|rupees?)?\s*([\d,]+)"
    r")",
    re.IGNORECASE,
)
_MONTH_PATTERNS: tuple[tuple[int, str], ...] = (
    (1, r"\b(?:january|jan)\b"),
    (2, r"\b(?:february|feb)\b"),
    (3, r"\b(?:march|mar)\b"),
    (4, r"\b(?:april|apr)\b"),
    (5, r"\b(?:(?:in|for|during|from|month\s+of)\s+may|may\s+20\d{2})\b"),
    (6, r"\b(?:june|jun)\b"),
    (7, r"\b(?:july|jul)\b"),
    (8, r"\b(?:august|aug)\b"),
    (9, r"\b(?:september|sept|sep)\b"),
    (10, r"\b(?:october|oct)\b"),
    (11, r"\b(?:november|nov)\b"),
    (12, r"\b(?:december|dec)\b"),
)
_PREMISE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("air quality", "Winter air quality / AQI spike"),
    ("aqi", "Winter AQI spike"),
    ("pollution", "Seasonal air pollution demand"),
    ("smog", "Seasonal smog respiratory demand"),
    ("cold wave", "Winter cold-wave joint/respiratory care demand"),
    ("winter", "Winter seasonal demand"),
    ("summer", "Summer seasonal demand"),
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

    parsed_budget = extract_inr_amount(q)
    budget_inr = parsed_budget if parsed_budget is not None else 300_000

    target_roas: float | None = None
    target_cac: float | None = None
    target_assumed = True
    roas_m = _TARGET_ROAS_RE.search(q)
    cac_m = _TARGET_CAC_RE.search(q)
    if roas_m:
        raw_r = next(g for g in roas_m.groups() if g is not None)
        target_roas = float(raw_r)
        target_assumed = False
    elif cac_m:
        raw_c = next(g for g in cac_m.groups() if g is not None).replace(",", "")
        target_cac = float(raw_c)
        target_assumed = False

    resolved_city = matched_city or resolve_city(q)
    if resolved_city:
        region = resolved_city
        region_assumed = False
    elif re.search(r"\b(all\s+india|pan[-\s]india|nationwide|national)\b", lowered):
        region = "All India"
        region_assumed = False
    else:
        region = "All India"
        region_assumed = True

    next_lbl = _next_month_label(today_ist)
    next_clean = next_lbl.replace(" (assumed)", "")
    window_label = next_lbl
    for m_idx, pat in _MONTH_PATTERNS:
        if re.search(pat, lowered):
            m_name = calendar.month_name[m_idx]
            yr = today_ist.year + (1 if m_idx < today_ist.month else 0)
            window_label = f"{m_name} {yr}"
            break
    else:
        for season in ("Winter", "Summer", "Monsoon", "Diwali", "Festive"):
            if season.lower() in lowered:
                window_label = f"{season} ({next_clean})"
                break

    premise: str | None = None
    for kw, label in _PREMISE_KEYWORDS:
        if kw in lowered:
            premise = label
            break

    resolved_prod = matched_product
    if not resolved_prod:
        ents = resolve_product_entities(q)
        resolved_prod = ents.product_family or ents.catalogue_product

    return CampaignPlanIntake(
        product_query=resolved_prod or "allproducts",
        region=region,
        region_assumed=region_assumed,
        budget_inr=budget_inr,
        target_roas=target_roas,
        target_cac_inr=target_cac,
        target_assumed=target_assumed,
        window_label=window_label,
        external_premise=premise,
    )
