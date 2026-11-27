"""Domain-agnostic document & spreadsheet ingestion pipeline (`POST /v1/memory/ingest`)."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from core.memory.doc_parser import (
    chunk_document_hierarchy,
    extract_document_text,
    extract_spreadsheet_rows,
)
from core.memory.schemas import (
    MemoryChunk,
    MemoryIngestRequest,
    MemoryIngestResponse,
    new_chunk_uuid,
)
from core.memory.store import CloudMemoryStore
from domains.base import DomainPlugin

_IST = timezone(timedelta(hours=5, minutes=30), name="IST")


async def ingest_domain_document(
    payload: MemoryIngestRequest,
    *,
    plugin: DomainPlugin,
    store: CloudMemoryStore,
    caller_wif: str,
    trace_id: str,
) -> MemoryIngestResponse:
    """Archive raw bytes to GCS `domains/<domain_id>/` and index L1/L2/L3 chunks into BigQuery."""
    if payload.content_base64:
        raw_bytes = base64.b64decode(payload.content_base64)
    elif payload.text_content is not None:
        raw_bytes = payload.text_content.encode("utf-8")
    else:
        raise ValueError("Either `content_base64` or `text_content` must be provided.")

    fname = payload.filename.strip()
    is_sheet = fname.lower().endswith((".xlsx", ".csv"))
    subfolder = "rulesets" if is_sheet else "docs"

    gcs_uri = await store.archive_raw_file_to_gcs(
        domain_id=plugin.domain_id,
        subfolder=subfolder,
        filename=fname,
        raw_bytes=raw_bytes,
    )

    now_iso = datetime.now(tz=_IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")
    custom_ingest = getattr(plugin, "ingest_document", None)
    if callable(custom_ingest):
        chunks: list[MemoryChunk] = custom_ingest(
            filename=fname,
            raw_bytes=raw_bytes,
            entity_tags=list(payload.entity_tags),
            trust_tier=payload.trust_tier,
            caller_wif=caller_wif,
            created_at_iso=now_iso,
            gcs_uri=gcs_uri,
        )
    elif is_sheet:
        rows = extract_spreadsheet_rows(fname, raw_bytes)
        lines = [" · ".join(f"{k}: {v}" for k, v in r.items() if v) for r in rows]
        chunks = chunk_document_hierarchy(
            domain_id=plugin.domain_id,
            source_title=fname,
            raw_text="\n".join(lines),
            entity_tags=list(payload.entity_tags),
            caller_wif=caller_wif,
            created_at_iso=now_iso,
            trust_tier=payload.trust_tier,
            gcs_uri=gcs_uri,
        )
    else:
        doc_text = extract_document_text(fname, raw_bytes)
        chunks = chunk_document_hierarchy(
            domain_id=plugin.domain_id,
            source_title=fname,
            raw_text=doc_text,
            entity_tags=list(payload.entity_tags),
            caller_wif=caller_wif,
            created_at_iso=now_iso,
            trust_tier=payload.trust_tier,
            gcs_uri=gcs_uri,
        )

    saved = await store.save_chunks(chunks, caller_wif=caller_wif)
    root_id = chunks[0].root_chunk_uuid if chunks else new_chunk_uuid()
    return MemoryIngestResponse(
        domain_id=plugin.domain_id,
        source_title=fname,
        gcs_uri=gcs_uri,
        chunks_indexed=saved,
        root_chunk_uuid=root_id,
        trace_id=trace_id,
    )
