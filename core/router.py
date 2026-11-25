"""Domain-agnostic deterministic time-grain and window router (`core/router.py`)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

TimeGrainOption = Literal["DoD", "WoW", "MoM", "YoY"]

_DOD_RE = re.compile(r"\b(dod|day[-\s]on[-\s]day|daily|yesterday)\b", re.IGNORECASE)
_WOW_RE = re.compile(r"\b(wow|week[-\s]on[-\s]week|weekly|last\s+week)\b", re.IGNORECASE)
_YOY_RE = re.compile(
    r"\b(yoy|year[-\s]on[-\s]year|last\s+year|same\s+month\s+last\s+year)\b",
    re.IGNORECASE,
)
_MOM_RE = re.compile(r"\b(mom|month[-\s]on[-\s]month|monthly|month|months)\b", re.IGNORECASE)

_WINDOW_MONTHS_RE = re.compile(
    r"\b(?:last|past)\s+(\d{1,2})\s+(?:closed\s+)?months?\b",
    re.IGNORECASE,
)
_HYPHEN_MONTHS_RE = re.compile(r"\b(\d{1,2})[-\s]months?\b", re.IGNORECASE)


@dataclass(frozen=True)
class RoutedTimeSpec:
    """Extracted time-grain and lookback window independent of business domain."""

    grain: TimeGrainOption
    window_count: int


def extract_time_spec(question: str, *, default_months: int = 3) -> RoutedTimeSpec:
    """Deterministically extract DoD/WoW/MoM/YoY grain and lookback window in <1ms."""
    q = question.strip()
    if _DOD_RE.search(q):
        return RoutedTimeSpec(grain="DoD", window_count=14)
    if _WOW_RE.search(q):
        return RoutedTimeSpec(grain="WoW", window_count=4)
    if _YOY_RE.search(q):
        return RoutedTimeSpec(grain="YoY", window_count=13)

    months = default_months
    for regex in (_WINDOW_MONTHS_RE, _HYPHEN_MONTHS_RE):
        match = regex.search(q)
        if match:
            parsed = int(match.group(1))
            months = max(1, min(parsed, 24))
            break

    if _MOM_RE.search(q):
        return RoutedTimeSpec(grain="MoM", window_count=months)

    return RoutedTimeSpec(grain="MoM", window_count=months)
