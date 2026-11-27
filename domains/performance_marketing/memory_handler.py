"""Governed Memory Save (`APPROVED_DECISION`) & Recall handlers for Performance Marketing."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from core.guardrails.output_audit import audit_rendered_markdown, scrub_pii_text
from core.memory.doc_parser import (
    chunk_document_hierarchy,
    extract_document_text,
    extract_spreadsheet_rows,
)
from core.memory.schemas import MemoryChunk, TrustTier, new_chunk_uuid
from core.memory.store import CloudMemoryStore, MemoryWriteForbiddenError
from core.schemas import Citation, SmritiQueryResponse
from domains.performance_marketing.kpi_presenter import BANNED_CAUSAL_WORDS
from domains.performance_marketing.ruleset_excel import (
    extract_marketing_tags_from_text,
    parse_marketing_ruleset_rows,
)

_SAVE_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:save(?:\s+this)?(?:\s+to)?(?:\s+smriti)?\s+"
    r"(?:memory|approved\s+plan|approved\s+decision|approved\s+brief|learning|rule)|"
    r"remember\s+this\s+(?:approved\s+)?(?:learning|rule|decision)|"
    r"record\s+(?:this\s+)?(?:campaign\s+)?(?:learning|decision))\s*[:\-–]?\s*",
    re.IGNORECASE,
)
_INLINE_SPLIT_RE = re.compile(
    r"\b(\d{2})\s*/\s*(\d{2})\s*(?:prospecting[-\s/]*retargeting|funnel\s+split|split)\b",
    re.IGNORECASE,
)


def ingest_marketing_document(
    *,
    filename: str,
    raw_bytes: bytes,
    entity_tags: list[str],
    trust_tier: TrustTier,
    caller_wif: str,
    created_at_iso: str,
    gcs_uri: str | None = None,
) -> list[MemoryChunk]:
    """Parse marketing Excel/CSV rulesets or BRD/Post-Mortem docs into MemoryChunks."""
    if filename.lower().endswith((".xlsx", ".csv")):
        rows = extract_spreadsheet_rows(filename, raw_bytes)
        return parse_marketing_ruleset_rows(
            rows,
            source_title=filename,
            caller_wif=caller_wif,
            created_at_iso=created_at_iso,
            gcs_uri=gcs_uri,
            trust_tier=trust_tier,
        )
    doc_text = extract_document_text(filename, raw_bytes)
    tags = extract_marketing_tags_from_text(doc_text, extra_tags=entity_tags)
    return chunk_document_hierarchy(
        domain_id="performance_marketing",
        source_title=filename,
        raw_text=doc_text,
        entity_tags=tags,
        caller_wif=caller_wif,
        created_at_iso=created_at_iso,
        trust_tier=trust_tier,
        gcs_uri=gcs_uri,
    )


def extract_save_body(question: str) -> str:
    """Strip command prefix from a chat memory-save instruction."""
    stripped = _SAVE_PREFIX_RE.sub("", question.strip(), count=1).strip()
    return stripped or question.strip()


def build_approved_decision_chunks(
    question: str,
    *,
    caller_wif: str,
    created_at_iso: str,
) -> list[MemoryChunk]:
    """Build L1 Summary + L3 Atomic Fact (and optional split override) from chat save command."""
    body = scrub_pii_text(extract_save_body(question))
    tags = extract_marketing_tags_from_text(body)
    prod_tag = tags[0] if tags else "allproducts"

    metrics: dict[str, Any] = {"product_family": prod_tag}
    sec_type = "Approved_Learning"
    split_m = _INLINE_SPLIT_RE.search(body)
    if split_m:
        p_val = int(split_m.group(1))
        r_val = int(split_m.group(2))
        if p_val + r_val == 100 and p_val > 0 and r_val > 0:
            metrics["prospecting_pct"] = round(p_val / 100.0, 4)
            metrics["retargeting_pct"] = round(r_val / 100.0, 4)
            sec_type = "Channel_Ruleset"

    root_id = new_chunk_uuid()
    title = f"Approved Decision ({prod_tag} · {created_at_iso[:10]})"
    l1 = MemoryChunk(
        chunk_uuid=root_id,
        parent_chunk_uuid=None,
        root_chunk_uuid=root_id,
        level=1,
        domain_id="performance_marketing",
        trust_tier="APPROVED_DECISION",
        entity_tags=tags or ["general"],
        section_type="Summary",
        content_text=body[:500],
        metrics_json=metrics,
        source_title=title,
        created_by_wif=caller_wif,
        approved_by_wif=caller_wif,
        created_at_iso=created_at_iso,
    )
    l3 = MemoryChunk(
        chunk_uuid=new_chunk_uuid(),
        parent_chunk_uuid=root_id,
        root_chunk_uuid=root_id,
        level=3,
        domain_id="performance_marketing",
        trust_tier="APPROVED_DECISION",
        entity_tags=tags or ["general"],
        section_type=sec_type,
        content_text=body[:1000],
        metrics_json=metrics,
        source_title=title,
        created_by_wif=caller_wif,
        approved_by_wif=caller_wif,
        created_at_iso=created_at_iso,
    )
    return [l1, l3]


async def execute_chat_memory_save(
    store: CloudMemoryStore,
    *,
    question: str,
    caller_wif: str,
    created_at_iso: str,
    trace_id: str,
) -> SmritiQueryResponse:
    """Persist an `APPROVED_DECISION` to BigQuery memory if caller is authorized."""
    chunks = build_approved_decision_chunks(
        question, caller_wif=caller_wif, created_at_iso=created_at_iso
    )
    try:
        saved_count = await store.save_chunks(chunks, caller_wif=caller_wif)
    except MemoryWriteForbiddenError:
        cite = Citation(
            source="Deterministic Guardrail",
            object_name="core.memory.store.SMRITI_MEMORY_APPROVERS",
            date_window_ist=created_at_iso,
            note="Memory write blocked; caller not in approver allowlist.",
        )
        md = (
            f"**Memory Write Governance Boundary:** `{caller_wif}` is not currently listed in "
            "`SMRITI_MEMORY_APPROVERS` to save org-wide Institutional Memory.\n\n"
            "- **How to Enable:** Ask an admin to add your work email to "
            "`SMRITI_MEMORY_APPROVERS` on Cloud Run, or have an approved lead save this decision."
            f"\n\n[Source: {cite.source} {cite.object_name} · {created_at_iso}]"
        )
        return SmritiQueryResponse(
            headline="Memory Governance · Approval Required",
            answer_markdown=audit_rendered_markdown(md),
            citations=[cite],
            degraded_sources=[],
            latency_ms=0,
            trace_id=trace_id,
        )

    l3 = chunks[-1]
    cite = Citation(
        source="Smriti Memory",
        object_name="Gemini_POC.smriti_memory_chunks",
        date_window_ist=created_at_iso,
        row_count=saved_count,
    )
    split_note = (
        f"\n- **Active Ruleset Override Indexed:** "
        f"`{int(l3.metrics_json['prospecting_pct'] * 100)}%` Prospecting / "
        f"`{int(l3.metrics_json['retargeting_pct'] * 100)}%` Retargeting"
        if "prospecting_pct" in l3.metrics_json
        else ""
    )
    md = (
        f"**Saved to Smriti Institutional Memory (`APPROVED_DECISION`)**\n\n"
        f"- **Domain Partition:** `performance_marketing`\n"
        f"- **Source Title:** `{l3.source_title}` (`{saved_count}` L1/L3 chunks indexed)\n"
        f"- **Entity Tags:** `{', '.join(l3.entity_tags)}`\n"
        f"- **Approved By:** `{caller_wif}`\n"
        f"- **Recorded Fact:** {l3.content_text}{split_note}\n\n"
        f"[Source: Smriti Memory {cite.object_name} · {created_at_iso}]"
    )
    return SmritiQueryResponse(
        headline=f"Saved to Smriti Memory · {l3.source_title}",
        answer_markdown=audit_rendered_markdown(md),
        citations=[cite],
        degraded_sources=[],
        latency_ms=0,
        trace_id=trace_id,
    )


def render_memory_recall_report(
    chunks: Sequence[MemoryChunk],
    *,
    query_tags: Sequence[str],
    today_str: str,
    trace_id: str,
) -> SmritiQueryResponse:
    """Render recalled BRDs, Post-Mortems, Excel Rulesets, and Approved Decisions with citations."""
    scope = ", ".join(query_tags) if query_tags else "all marketing categories"
    if not chunks:
        cite = Citation(
            source="Smriti Memory",
            object_name="Gemini_POC.smriti_memory_chunks",
            date_window_ist=today_str,
            row_count=0,
        )
        md = (
            f"No verified Institutional Memory chunks found yet for **{scope}** in "
            "`performance_marketing`.\n\n"
            "- **To Add Official Docs / Rulesets:** Upload `.pdf`, `.docx`, `.md`, `.xlsx`, or "
            "`.csv` files via `POST /v1/memory/ingest` (or `scripts/ingest_memory.py`).\n"
            "- **To Save an Approved Decision in Chat:** Start your message with "
            "`Save to Smriti memory: <verified learning or rule>`.\n\n"
            f"[Source: Smriti Memory {cite.object_name} · {today_str}]"
        )
        return SmritiQueryResponse(
            headline=f"Institutional Memory Recall · {scope}",
            answer_markdown=audit_rendered_markdown(md, banned_words=BANNED_CAUSAL_WORDS),
            citations=[cite],
            degraded_sources=[],
            latency_ms=0,
            trace_id=trace_id,
        )

    cites: list[Citation] = []
    lines = [
        f"#### Verified Institutional Memory (`{len(chunks)}` Matching Chunks)",
        "| Source Document / Decision | Tier | Section | Tags | Verified Learning / Rule |",
        "|---|---|---|---|---|",
    ]
    seen_sources: set[str] = set()
    for ch in chunks:
        safe_txt = ch.content_text.replace("|", "/").replace("\n", " ")[:220]
        for banned in BANNED_CAUSAL_WORDS:
            safe_txt = re.sub(rf"\b{re.escape(banned)}\b", "[observed]", safe_txt, flags=re.I)
        tag_str = ", ".join(ch.entity_tags[:4]) or "general"
        lines.append(
            f"| `{ch.source_title}` | `{ch.trust_tier}` | `{ch.section_type}` | "
            f"`{tag_str}` | {safe_txt} |"
        )
        if ch.source_title not in seen_sources:
            seen_sources.add(ch.source_title)
            cites.append(
                Citation(
                    source="Smriti Memory",
                    object_name=f"{ch.source_title} ({ch.trust_tier})",
                    date_window_ist=ch.created_at_iso[:10],
                    row_count=1,
                )
            )
    lines.append(
        f"\n[Source: Smriti Memory Gemini_POC.smriti_memory_chunks · Verified as of {today_str}]"
    )
    verified = audit_rendered_markdown("\n".join(lines), banned_words=BANNED_CAUSAL_WORDS)
    return SmritiQueryResponse(
        headline=f"Institutional Memory Recall · {scope}",
        answer_markdown=verified,
        citations=cites,
        degraded_sources=[],
        latency_ms=0,
        trace_id=trace_id,
    )
