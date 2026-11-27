"""Performance Marketing Excel/CSV Channel Ruleset & Entity Tag Adapter (`ruleset_excel.py`)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from core.guardrails.output_audit import scrub_pii_text
from core.memory.schemas import MemoryChunk, TrustTier, new_chunk_uuid
from domains.performance_marketing.entity_lexicon import resolve_city, resolve_product_entities

_SEASON_TAGS: tuple[str, ...] = (
    "winter", "summer", "monsoon", "diwali", "festive", "aqi", "air quality",
)


def _norm_pct(raw: str) -> float | None:
    cleaned = raw.strip().rstrip("%").strip()
    if not cleaned:
        return None
    try:
        val = float(cleaned)
    except ValueError:
        return None
    if val > 1.0:
        val = val / 100.0
    if 0.0 < val < 1.0:
        return round(val, 4)
    return None


def _norm_float(raw: str) -> float | None:
    cleaned = raw.strip().replace(",", "").lstrip("₹RrSs. ")
    if not cleaned:
        return None
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def extract_marketing_tags_from_text(text: str, extra_tags: Sequence[str] = ()) -> list[str]:
    """Derive canonical marketing entity tags (`family`, `city`, `season`) from free text."""
    tags: list[str] = [t.strip().lower() for t in extra_tags if t.strip()]
    prod = resolve_product_entities(text)
    if prod.product_family:
        tags.append(prod.product_family.lower())
    if prod.catalogue_product:
        tags.append(prod.catalogue_product.lower())
    city = resolve_city(text)
    if city:
        tags.append(city.lower())
    lowered = text.lower()
    for s_tag in _SEASON_TAGS:
        if re.search(rf"\b{re.escape(s_tag)}\b", lowered):
            tags.append(s_tag)
    deduped: list[str] = []
    for item in tags:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def parse_marketing_ruleset_rows(
    rows: Sequence[dict[str, str]],
    *,
    source_title: str,
    caller_wif: str,
    created_at_iso: str,
    gcs_uri: str | None = None,
    trust_tier: TrustTier = "OFFICIAL_DOC",
) -> list[MemoryChunk]:
    """Convert Excel/CSV marketing channel & phasing ruleset rows into L1 + L3 MemoryChunks."""
    if not rows:
        return []

    root_id = new_chunk_uuid()
    l3_chunks: list[MemoryChunk] = []
    covered_families: list[str] = []

    for row in rows:
        low_row = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items() if k}
        raw_fam = (
            low_row.get("product_family")
            or low_row.get("family")
            or low_row.get("product")
            or low_row.get("category")
            or "allproducts"
        )
        ents = resolve_product_entities(raw_fam)
        fam = (ents.product_family or raw_fam.strip().lower() or "allproducts")
        if fam not in covered_families:
            covered_families.append(fam)

        prosp = _norm_pct(low_row.get("prospecting_pct") or low_row.get("prospecting_split") or "")
        retarg = _norm_pct(low_row.get("retargeting_pct") or low_row.get("retargeting_split") or "")
        if prosp is not None and retarg is None:
            retarg = round(1.0 - prosp, 4)
        elif retarg is not None and prosp is None:
            prosp = round(1.0 - retarg, 4)
        if prosp is not None and retarg is not None and abs((prosp + retarg) - 1.0) > 0.02:
            prosp, retarg = None, None

        p1 = _norm_pct(low_row.get("phase_1_pct") or low_row.get("p1_pct") or "")
        p2 = _norm_pct(low_row.get("phase_2_pct") or low_row.get("p2_pct") or "")
        p3 = _norm_pct(low_row.get("phase_3_pct") or low_row.get("p3_pct") or "")
        has_valid_phases = (
            p1 is not None
            and p2 is not None
            and p3 is not None
            and abs((p1 + p2 + p3) - 1.0) <= 0.02
        )

        max_daily = _norm_float(
            low_row.get("max_daily_phase1_inr") or low_row.get("daily_cap_inr") or ""
        )
        min_roas = _norm_float(
            low_row.get("min_roas_guardrail") or low_row.get("target_roas") or ""
        )
        note = scrub_pii_text(
            low_row.get("rule_note")
            or low_row.get("learning")
            or low_row.get("creative_guideline")
            or ""
        )

        metrics: dict[str, Any] = {"product_family": fam}
        parts = [f"Family `{fam}` ruleset:"]
        if prosp is not None and retarg is not None:
            metrics["prospecting_pct"] = prosp
            metrics["retargeting_pct"] = retarg
            parts.append(f"Funnel split {int(round(prosp * 100))}/{int(round(retarg * 100))}")
        if has_valid_phases:
            metrics["phase_1_pct"] = p1
            metrics["phase_2_pct"] = p2
            metrics["phase_3_pct"] = p3
            parts.append(
                f"Phasing {int(round((p1 or 0) * 100))}%/"
                f"{int(round((p2 or 0) * 100))}%/{int(round((p3 or 0) * 100))}%"
            )
        if max_daily is not None:
            metrics["max_daily_phase1_inr"] = max_daily
            parts.append(f"Phase 1 cap Rs {int(max_daily):,}/d")
        if min_roas is not None:
            metrics["min_roas_guardrail"] = min_roas
            parts.append(f"Min ROAS {min_roas:.2f}x")
        if note:
            parts.append(note)

        tags = extract_marketing_tags_from_text(f"{fam} {note}", extra_tags=[fam, "ruleset"])
        l3_chunks.append(
            MemoryChunk(
                chunk_uuid=new_chunk_uuid(),
                parent_chunk_uuid=root_id,
                root_chunk_uuid=root_id,
                level=3,
                domain_id="performance_marketing",
                trust_tier=trust_tier,
                entity_tags=tags,
                section_type="Channel_Ruleset",
                content_text=" · ".join(parts)[:1000],
                metrics_json=metrics,
                source_title=source_title,
                gcs_uri=gcs_uri,
                created_by_wif=caller_wif,
                approved_by_wif=caller_wif,
                created_at_iso=created_at_iso,
            )
        )

    if not l3_chunks:
        return []

    summary_chunk = MemoryChunk(
        chunk_uuid=root_id,
        parent_chunk_uuid=None,
        root_chunk_uuid=root_id,
        level=1,
        domain_id="performance_marketing",
        trust_tier=trust_tier,
        entity_tags=[*covered_families, "ruleset"],
        section_type="Summary",
        content_text=(
            f"Marketing Channel & Phasing Ruleset ({len(l3_chunks)} rules covering: "
            f"{', '.join(covered_families[:8])})."
        ),
        metrics_json={"rule_count": len(l3_chunks)},
        source_title=source_title,
        gcs_uri=gcs_uri,
        created_by_wif=caller_wif,
        approved_by_wif=caller_wif,
        created_at_iso=created_at_iso,
    )
    return [summary_chunk, *l3_chunks]


def select_ruleset_override(
    chunks: Sequence[MemoryChunk],
    product_query: str,
) -> tuple[dict[str, Any], MemoryChunk] | None:
    """Pick the highest-priority Channel_Ruleset override matching `product_query`."""
    norm_prod = product_query.strip().lower()
    fallback: tuple[dict[str, Any], MemoryChunk] | None = None
    for ch in chunks:
        if ch.section_type != "Channel_Ruleset" or not ch.metrics_json:
            continue
        fam = str(ch.metrics_json.get("product_family") or "").strip().lower()
        has_split = "prospecting_pct" in ch.metrics_json or "phase_1_pct" in ch.metrics_json
        if not has_split:
            continue
        if fam == norm_prod:
            return ch.metrics_json, ch
        if fam in {"allproducts", "global", "all"} and fallback is None:
            fallback = (ch.metrics_json, ch)
    return fallback
