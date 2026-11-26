"""Domain-agnostic time-grain, window, and English number helpers (`core/router.py`)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

TimeGrainOption = Literal["DoD", "WoW", "MoM", "YoY"]

_WORD_NUMBERS: dict[str, float] = {
    "half": 0.5,
    "quarter": 0.25,
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "couple": 2.0,
    "two": 2.0,
    "few": 3.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "eleven": 11.0,
    "twelve": 12.0,
    "thirteen": 13.0,
    "fourteen": 14.0,
    "fifteen": 15.0,
    "sixteen": 16.0,
    "seventeen": 17.0,
    "eighteen": 18.0,
    "nineteen": 19.0,
    "twenty": 20.0,
    "twenty five": 25.0,
    "twenty-five": 25.0,
    "thirty": 30.0,
    "forty": 40.0,
    "fifty": 50.0,
    "sixty": 60.0,
    "seventy": 70.0,
    "seventy five": 75.0,
    "seventy-five": 75.0,
    "eighty": 80.0,
    "ninety": 90.0,
    "hundred": 100.0,
}

_DOD_RE = re.compile(
    r"\b(dod|day[-\s]on[-\s]day|day[-\s]over[-\s]day|day[-\s]by[-\s]day|day[-\s]wise|"
    r"daily|yesterday)\b",
    re.IGNORECASE,
)
_DAYS_WINDOW_RE = re.compile(
    r"\b(?:last|past)\s+(\d{1,2}|one|two|three|four|five|six|seven|ten|fourteen|fifteen|"
    r"twenty|thirty)\s+days?\b",
    re.IGNORECASE,
)
_WOW_RE = re.compile(
    r"\b(wow|week[-\s]on[-\s]week|week[-\s]over[-\s]week|week[-\s]by[-\s]week|"
    r"week[-\s]wise|weekly|last\s+week)\b",
    re.IGNORECASE,
)
_YOY_RE = re.compile(
    r"\b(yoy|year[-\s]on[-\s]year|year[-\s]over[-\s]year|last\s+year|"
    r"same\s+month\s+last\s+year|annual)\b",
    re.IGNORECASE,
)
_MOM_RE = re.compile(
    r"\b(mom|month[-\s]on[-\s]month|month[-\s]over[-\s]month|month[-\s]wise|"
    r"monthly|month|months)\b",
    re.IGNORECASE,
)

_NUM_TOKEN = (
    r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"couple\s+of|few)"
)
_WINDOW_MONTHS_RE = re.compile(
    rf"\b(?:last|past)\s+({_NUM_TOKEN})\s+(?:closed\s+|settled\s+)?months?\b",
    re.IGNORECASE,
)
_HYPHEN_MONTHS_RE = re.compile(rf"\b({_NUM_TOKEN})[-\s]months?\b", re.IGNORECASE)
_QUARTER_RE = re.compile(r"\b(last\s+quarter|past\s+quarter|quarterly)\b", re.IGNORECASE)
_HALF_YEAR_RE = re.compile(r"\b(last\s+half[-\s]year|last\s+2\s+quarters)\b", re.IGNORECASE)


@dataclass(frozen=True)
class RoutedTimeSpec:
    """Extracted time-grain and lookback window independent of business domain."""

    grain: TimeGrainOption
    window_count: int


def parse_number_token(raw: str) -> float | None:
    """Parse a numeric string or English number word (including 'two and a half') into float."""
    cleaned = raw.strip().lower().replace(",", "")
    if not cleaned:
        return None
    cleaned = re.sub(r"\s+of$", "", cleaned)
    try:
        return float(cleaned)
    except ValueError:
        pass
    half_match = re.fullmatch(r"([a-z-]+)\s+and\s+a\s+half", cleaned)
    if half_match and half_match.group(1) in _WORD_NUMBERS:
        return _WORD_NUMBERS[half_match.group(1)] + 0.5
    return _WORD_NUMBERS.get(cleaned)


def extract_time_spec(question: str, *, default_months: int = 3) -> RoutedTimeSpec:
    """Deterministically extract DoD/WoW/MoM/YoY grain and lookback window in <1ms."""
    q = question.strip()
    days_m = _DAYS_WINDOW_RE.search(q)
    if _DOD_RE.search(q) or days_m:
        days = 14
        if days_m:
            parsed_d = parse_number_token(days_m.group(1))
            if parsed_d is not None:
                days = max(1, min(int(parsed_d), 90))
        return RoutedTimeSpec(grain="DoD", window_count=days)
    if _WOW_RE.search(q):
        return RoutedTimeSpec(grain="WoW", window_count=4)
    if _YOY_RE.search(q):
        return RoutedTimeSpec(grain="YoY", window_count=13)

    months = default_months
    for regex in (_WINDOW_MONTHS_RE, _HYPHEN_MONTHS_RE):
        match = regex.search(q)
        if match:
            parsed = parse_number_token(match.group(1))
            if parsed is not None:
                months = max(1, min(int(parsed), 24))
                break
    else:
        if _HALF_YEAR_RE.search(q):
            months = 6
        elif _QUARTER_RE.search(q):
            months = 3

    if _MOM_RE.search(q):
        return RoutedTimeSpec(grain="MoM", window_count=months)

    return RoutedTimeSpec(grain="MoM", window_count=months)
