"""Performance Marketing domain plugin (Slice 0 verified Cloud Run <-> GE gateway ping)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.schemas import Citation, SmritiQueryResponse

_IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class PerformanceMarketingPlugin:
    """Domain #1 plugin implementing the pluggable DomainPlugin contract."""

    domain_id: str = "performance_marketing"

    def check_known_refusal(self, parsed_intent: dict[str, Any]) -> str | None:
        # Full deterministic refusal rules (`rules.py`) plug in during Slice 1.
        return None

    async def collect_parallel(self, parsed_intent: dict[str, Any]) -> dict[str, Any]:
        now_ist = datetime.now(tz=_IST).strftime("%d %b %Y %H:%M:%S IST")
        return {
            "collected_at_ist": now_ist,
            "degraded_sources": [],
        }

    def compute_verified_metrics(
        self,
        parsed_intent: dict[str, Any],
        raw_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "question": parsed_intent["question"],
            "caller_wif": parsed_intent["caller_wif"],
            "trace_id": parsed_intent["trace_id"],
            "collected_at_ist": raw_bundle["collected_at_ist"],
            "degraded_sources": raw_bundle.get("degraded_sources", []),
        }

    async def render_response(self, verified_payload: dict[str, Any]) -> SmritiQueryResponse:
        collected_at = verified_payload["collected_at_ist"]
        caller_wif = verified_payload["caller_wif"]
        trace_id = verified_payload["trace_id"]

        citation = Citation(
            source="Smriti Gateway",
            object_name=f"domains.{self.domain_id} (Slice 0 Ping)",
            date_window_ist=collected_at,
            row_count=1,
            note="Verified Cloud Run gateway connectivity and WIF normalization.",
        )
        answer_md = (
            f"**Hello Smriti v2** — Cloud Run high-code engine is online.\n\n"
            f"- **Normalized User ID:** `{caller_wif}`\n"
            f"- **Active Domain:** `{self.domain_id}`\n"
            f"- **Trace ID:** `{trace_id}`\n\n"
            f"[Source: {citation.source} {citation.object_name} · {citation.date_window_ist}]"
        )
        return SmritiQueryResponse(
            headline=f"System Connectivity Ping · {self.domain_id}",
            answer_markdown=answer_md,
            citations=[citation],
            degraded_sources=verified_payload["degraded_sources"],
            latency_ms=0,
            trace_id=trace_id,
        )
