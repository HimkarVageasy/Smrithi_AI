"""Shared semantic lexicon for marketing entities, INR budgets, mutations, and planning intents."""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.router import parse_number_token


@dataclass(frozen=True)
class MatchedProductEntities:
    """Resolved ad-side `product_family` (`ge_family_monthly`) and `catalogue_product` keys."""

    product_family: str | None = None
    catalogue_product: str | None = None


_PRODUCT_GROUPS: tuple[tuple[str | None, str | None, tuple[str, ...]], ...] = (
    (
        "diaper",
        "diaper",
        (
            "adult diaper pants", "adult diapers", "diaper pants", "pull-up diapers",
            "pull up diapers", "tape diapers", "incontinence", "diapers", "diaper",
        ),
    ),
    ("underpad", "underpad", ("bed protectors", "bed protector", "underpads", "underpad")),
    (
        "nebulizer",
        "nebulizer",
        (
            "mesh nebulizer", "mesh nebuliser", "portable nebulizer", "portable nebuliser",
            "steam inhaler", "nebulizers", "nebulisers", "nebulizer", "nebuliser",
            "vaporizer", "vaporiser",
        ),
    ),
    (
        "massagegun",
        "massage gun",
        (
            "mini massage gun", "percussion massager", "massage guns", "massage gun",
            "massageguns", "massagegun", "massagers", "massager",
        ),
    ),
    (
        "healthmonitors",
        "bp monitor",
        (
            "blood pressure monitors", "blood pressure monitor", "blood pressure machines",
            "blood pressure machine", "bp monitors", "bp monitor", "bp machines", "bp machine",
            "health monitors", "health monitor", "healthmonitors",
        ),
    ),
    ("healthmonitors", "oximeter", ("pulse oximeters", "pulse oximeter", "oximeters", "oximeter")),
    ("healthmonitors", "thermometer", ("thermometers", "thermometer")),
    (
        "glucosesensor",
        "cgm",
        (
            "continuous glucose", "glucose sensors", "glucose sensor", "sugar sensors",
            "sugar sensor", "cgm sensors", "cgm sensor", "glucosesensor", "glucometer", "cgm",
        ),
    ),
    (
        "walking stick",
        "walking stick",
        (
            "walking sticks", "walking stick", "walking canes", "walking cane",
            "quad stick", "foldable stick", "canes", "cane", "stick",
        ),
    ),
    ("walker", "walker", ("rollators", "rollator", "walkers", "walker")),
    ("wheelchair", "wheelchair", ("wheelchairs", "wheelchair", "wheel chair")),
    (
        "pillow",
        "pillow",
        (
            "cervical pillows", "cervical pillow", "neck pillows", "neck pillow",
            "orthopaedic pillow", "orthopedic pillow", "pillows", "pillow",
        ),
    ),
    (
        "knee",
        "knee",
        (
            "knee caps", "knee cap", "kneecaps", "kneecap", "knee braces", "knee brace",
            "knee supports", "knee support", "knee",
        ),
    ),
    (
        "lumbar",
        "lumbar",
        (
            "lumbar belts", "lumbar belt", "lumbar supports", "lumbar support",
            "back supports", "back support", "back belts", "back belt",
            "backrests", "backrest", "lumbar",
        ),
    ),
    (
        "bunion",
        "bunion",
        ("bunion correctors", "bunion corrector", "bunion splint", "bunions", "bunion"),
    ),
    (
        "bathroomsafety",
        "commode",
        ("bathroom safety", "bathroomsafety", "commode chair", "commodes", "commode"),
    ),
    ("bathroomsafety", "grab", ("grab bars", "grab bar")),
    ("bathroomsafety", "shower", ("shower chairs", "shower chair")),
    ("hearing", "hearing", ("hearing aids", "hearing aid", "hearing")),
    ("allprodpros", None, ("allprodpros",)),
    ("allproducts", None, ("allproducts", "all products")),
    ("catalogue", None, ("catalogue campaign", "catalogue ads")),
)

_SORTED_PRODUCT_SYNONYMS: tuple[tuple[str, str | None, str | None], ...] = tuple(
    sorted(
        ((phrase, fam, cat) for fam, cat, phrases in _PRODUCT_GROUPS for phrase in phrases),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

_CITY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("NOIDA", ("gautam buddha nagar", "greater noida", "noida")),
    ("DELHI", ("new delhi", "delhi ncr", "delhi", "ncr")),
    ("MUMBAI", ("navi mumbai", "mumbai", "bombay")),
    ("BANGALORE", ("bengaluru", "bangalore")),
    ("GURGAON", ("gurugram", "gurgaon")),
    ("KOLKATA", ("calcutta", "kolkata")),
)
_DIRECT_CITIES: tuple[str, ...] = (
    "hyderabad", "chennai", "pune", "ahmedabad", "jaipur", "lucknow", "chandigarh",
    "indore", "kochi", "coimbatore", "surat", "nagpur", "patna", "bhopal",
)

_CAC_SPAN_MASK_RE = re.compile(
    r"\b(?:(?:max|maximum|target(?:ing)?|net|delivered)\s+){0,2}cac"
    r"(?:\s+(?:of|under|below|around|at|:))?\s*(?:rs\.?|inr|₹|rupees?)?\s*[\d,]+(?:\.\d+)?",
    re.IGNORECASE,
)
_CURRENCY = r"(?:rs\.?|inr|₹|rupees?)"
_NUM_EXPR = (
    r"(?:\d+(?:\.\d+)?|(?:[a-z]+\s+and\s+a\s+half)|half(?:\s+a)?|quarter|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|"
    r"twenty(?:[-\s]five)?|thirty|forty|fifty|sixty|seventy(?:[-\s]five)?|eighty|ninety|hundred)"
)
_UNIT_AMOUNT_RE = re.compile(
    rf"(?:{_CURRENCY}\s*)?\b({_NUM_EXPR})\s*(crores?|crs?|lakhs?|lacs?|thousand)\b"
    rf"(?:\s*{_CURRENCY})?",
    re.IGNORECASE,
)
_SHORT_LK_RE = re.compile(
    rf"(?:{_CURRENCY}\s*)?\b(\d+(?:\.\d+)?)\s*([lk])\b(?!\s*it(?:er|re)s?)(?:\s*{_CURRENCY})?",
    re.IGNORECASE,
)
_PLAIN_CURR_BEFORE_RE = re.compile(rf"(?:{_CURRENCY})\s*([\d,]{{4,}})\b", re.IGNORECASE)
_PLAIN_CURR_AFTER_RE = re.compile(rf"\b([\d,]{{4,}})\s*(?:{_CURRENCY})\b", re.IGNORECASE)
_BUDGET_PLAIN_RE = re.compile(r"\bbudget\s*(?:of|is|:|=)?\s*([\d,]{4,})\b", re.IGNORECASE)

_WRITE_MUTATION_RE = re.compile(
    r"\b("
    r"(pause|unpause|resume|delete|remove|archive|disable|deactivate|turn\s+off|stop)\s+"
    r"(?:(?:this|these|the|our|my|all|active|live|running)\s+)*"
    r"(ad|ads|adset|adsets|ad\s+set|campaign|campaigns)|"
    r"(edit|modify|update|change|increase|decrease|raise|lower)\s+"
    r"(?:(?:this|these|the|our|my|all|active|live|daily)\s+)*"
    r"(ad\s+copy|bid|bids|daily\s+budget|live\s+budget|campaign\s+budget|budget)|"
    r"set\s+(?:(?:this|the|our|my)\s+)*(daily\s+budget|live\s+budget|active\s+budget|bid|bids)|"
    r"(publish|push)\s+(?:(?:this|these|the)\s+)*(ad|campaign)\s+(?:directly\s+)?(in|to|into)\s+"
    r"(meta|facebook|google)"
    r")\b",
    re.IGNORECASE,
)
_EXPLICIT_PLAN_NOUN_RE = re.compile(
    r"\b(campaign\s+plan|media\s+plan|ad\s+plan|marketing\s+plan|campaign\s+brief|media\s+brief|"
    r"ad\s+brief|campaign\s+strategy|media\s+strategy|ad\s+strategy|launch\s+plan|scaling\s+plan|"
    r"go[-\s]to[-\s]market|phased\s+budget|budget\s+allocation|budget\s+phasing|budget\s+split)\b",
    re.IGNORECASE,
)
_STRONG_PLAN_ACTION_RE = re.compile(
    r"\b(plan|planning|propose|draft|design|map\s+out|allocate|deploy|invest|scale\s+up|"
    r"(?:need|want|looking|going|planning|thinking|intend)\s+to\s+"
    r"(?:run|launch|start|plan|scale|promote|push|spend|invest|advertise)|"
    r"how\s+(?:should|can|do|would|to)\s+(?:we|i)\s+"
    r"(?:run|launch|scale|allocate|spend|invest|deploy|structure|promote|advertise|plan)|"
    r"what\s+campaign\s+should\s+(?:we|i)\s+run|"
    r"where\s+should\s+(?:we|i)\s+(?:spend|invest|allocate)|"
    r"let'?s\s+(?:run|launch|plan|build)|launch\s+(?:a|an|our|this|new))\b",
    re.IGNORECASE,
)
_GENERAL_BUILD_ACTION_RE = re.compile(
    r"\b(create|build|prepare|structure|outline|recommend|suggest|help\s+(?:me|us))\b",
    re.IGNORECASE,
)
_CAMPAIGN_CONTEXT_RE = re.compile(
    r"\b(campaign|campaigns|ads?|advertising|media|promo|promotion|budget|phasing|allocation|"
    r"brief|strategy|winter|summer|monsoon|festive|diwali|seasonal|next\s+month|upcoming|q[1-4])\b",
    re.IGNORECASE,
)
_HISTORICAL_RETRO_RE = re.compile(
    r"\b(why\s+did|what\s+happened|had\s+spend|was\s+spend|spent\s+in|"
    r"did\s+(?:we|\w+)\s+(?:spend|invest)|which\s+(?:ad\s+)?(?:families|months?)\s+had|"
    r"spend\s+(?:above|over|under|below|exceed))\b",
    re.IGNORECASE,
)


def resolve_product_entities(text: str) -> MatchedProductEntities:
    """Resolve natural product phrases to (`product_family`, `catalogue_product`)."""
    lowered = text.lower()
    for phrase, fam, cat in _SORTED_PRODUCT_SYNONYMS:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return MatchedProductEntities(product_family=fam, catalogue_product=cat)
    return MatchedProductEntities()


def resolve_city(text: str) -> str | None:
    """Resolve Indian city / metro aliases to uppercase warehouse names."""
    lowered = text.lower()
    for canonical, aliases in _CITY_GROUPS:
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                return canonical
    for city in _DIRECT_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", lowered):
            return city.upper()
    return None


def extract_inr_amount(text: str) -> int | None:
    """Extract planned INR media budget across digits, words, Lakh/Crore/K, and Rupees/Rs/₹."""
    masked = _CAC_SPAN_MASK_RE.sub(" ", text)

    u_match = _UNIT_AMOUNT_RE.search(masked)
    if u_match:
        raw_num = re.sub(r"\s+a$", "", u_match.group(1).strip().lower())
        num = parse_number_token(raw_num)
        if num is not None:
            unit = u_match.group(2).lower()
            mult = (
                10_000_000
                if unit.startswith("c")
                else (1_000 if unit == "thousand" else 100_000)
            )
            return max(1_000, int(round(num * mult)))

    lk_match = _SHORT_LK_RE.search(masked)
    if lk_match:
        num = float(lk_match.group(1))
        mult = 100_000 if lk_match.group(2).lower() == "l" else 1_000
        return max(1_000, int(round(num * mult)))

    for rx in (_PLAIN_CURR_BEFORE_RE, _PLAIN_CURR_AFTER_RE, _BUDGET_PLAIN_RE):
        pm = rx.search(masked)
        if pm:
            digits = pm.group(1).replace(",", "")
            if digits.isdigit() and int(digits) >= 1_000:
                return int(digits)
    return None


def is_write_mutation_command(text: str) -> bool:
    """Return True if user asks to pause, edit, mutate, or publish live ads/budgets."""
    return bool(_WRITE_MUTATION_RE.search(text))


def is_campaign_planning_query(text: str) -> bool:
    """Return True across any natural-language request for a Campaign Plan / Phased Brief."""
    q = text.strip()
    if not q or is_write_mutation_command(q):
        return False
    if _EXPLICIT_PLAN_NOUN_RE.search(q):
        return True

    has_budget = extract_inr_amount(q) is not None
    prod = resolve_product_entities(q)
    has_prod = bool(prod.product_family or prod.catalogue_product)
    is_retro = bool(_HISTORICAL_RETRO_RE.search(q))

    if _STRONG_PLAN_ACTION_RE.search(q) and not is_retro:
        if _CAMPAIGN_CONTEXT_RE.search(q) or has_budget or has_prod:
            return True

    if _GENERAL_BUILD_ACTION_RE.search(q) and not is_retro:
        if _CAMPAIGN_CONTEXT_RE.search(q) or has_budget:
            return True

    if has_budget and not is_retro and (_CAMPAIGN_CONTEXT_RE.search(q) or has_prod):
        return True

    return False
