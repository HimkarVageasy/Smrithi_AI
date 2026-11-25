"""Domain-agnostic API request and response contracts for Gemini Enterprise <-> Cloud Run."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SmritiQueryRequest(BaseModel):
    """Inbound query payload from Gemini Enterprise OpenAPI tool invocation."""

    question: str = Field(
        ...,
        min_length=2,
        description="Natural language user request from Gemini Enterprise chat",
    )
    domain_hint: str | None = Field(
        default=None,
        description=(
            "Optional target domain identifier; uses registered default domain when omitted"
        ),
    )
    session_id: str | None = Field(
        default=None,
        description=(
            "Optional Gemini Enterprise session identifier for short-term thread continuity"
        ),
    )


class Citation(BaseModel):
    """Mandatory source provenance and IST date window tag."""

    source: str = Field(
        ...,
        min_length=1,
        description="Canonical data connector or governed memory store name",
    )
    object_name: str = Field(
        ...,
        min_length=1,
        description="Exact view, table, account, or document identifier queried",
    )
    date_window_ist: str = Field(
        ...,
        min_length=1,
        description="Evaluated Asia/Kolkata (IST) date window",
    )
    row_count: int | None = Field(default=None, ge=0)
    note: str | None = None


class SmritiQueryResponse(BaseModel):
    """Verified, cited response payload returned to Gemini Enterprise."""

    headline: str = Field(..., min_length=1, description="Concise executive scope headline")
    answer_markdown: str = Field(
        ...,
        min_length=1,
        description="Verified prose and Markdown tables with inline [Source · Window] tags",
    )
    citations: list[Citation] = Field(default_factory=list)
    degraded_sources: list[str] = Field(
        default_factory=list,
        description="Non-critical live sources that timed out or degraded gracefully",
    )
    latency_ms: int = Field(..., ge=0)
    trace_id: str = Field(..., min_length=1)


class HealthResponse(BaseModel):
    """Cloud Run readiness and liveness probe payload."""

    status: Literal["ok"] = "ok"
    service: str
    version: str
    registered_domains: list[str]
    timestamp_ist: str
