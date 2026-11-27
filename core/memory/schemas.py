"""Domain-agnostic Pydantic v2 contracts for L1/L2/L3 Institutional Memory (`core/memory/`)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TrustTier = Literal["OFFICIAL_DOC", "APPROVED_DECISION"]
ChunkLevel = Literal[1, 2, 3]


def new_chunk_uuid() -> str:
    """Generate a URL-safe UUID4 identifier for a memory chunk."""
    return uuid.uuid4().hex


class MemoryChunk(BaseModel):
    """Single L1 Summary, L2 Section, or L3 Atomic Fact row in `smriti_memory_chunks`."""

    model_config = ConfigDict(frozen=True)

    chunk_uuid: str = Field(default_factory=new_chunk_uuid, min_length=8)
    parent_chunk_uuid: str | None = None
    root_chunk_uuid: str = Field(..., min_length=8)
    level: ChunkLevel
    domain_id: str = Field(..., min_length=2, max_length=64)
    trust_tier: TrustTier
    entity_tags: list[str] = Field(default_factory=list)
    section_type: str = Field(default="General", min_length=1, max_length=64)
    content_text: str = Field(..., min_length=3, max_length=8000)
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    source_title: str = Field(..., min_length=2, max_length=200)
    gcs_uri: str | None = None
    created_by_wif: str = Field(..., min_length=3)
    approved_by_wif: str = Field(..., min_length=3)
    created_at_iso: str = Field(..., min_length=10)

    @field_validator("domain_id", "created_by_wif", "approved_by_wif")
    @classmethod
    def _normalize_lowercase_ids(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("Identifier cannot be blank.")
        return cleaned

    @field_validator("entity_tags")
    @classmethod
    def _normalize_tags(cls, tags: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in tags:
            norm = raw.strip().lower()
            if norm and norm not in seen:
                seen.append(norm)
        return seen


class MemoryIngestRequest(BaseModel):
    """Governed document / spreadsheet ingestion payload (`POST /v1/memory/ingest`)."""

    model_config = ConfigDict(frozen=True)

    domain_id: str = Field(..., min_length=2, max_length=64)
    filename: str = Field(..., min_length=3, max_length=200)
    content_base64: str | None = None
    text_content: str | None = None
    entity_tags: list[str] = Field(default_factory=list)
    trust_tier: TrustTier = "OFFICIAL_DOC"


class MemoryIngestResponse(BaseModel):
    """Summary returned after archiving to GCS and indexing L1/L2/L3 chunks into BigQuery."""

    model_config = ConfigDict(frozen=True)

    domain_id: str
    source_title: str
    gcs_uri: str | None = None
    chunks_indexed: int = Field(..., ge=0)
    root_chunk_uuid: str
    trace_id: str
