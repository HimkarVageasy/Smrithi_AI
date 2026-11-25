"""Domain-agnostic FastAPI gateway for Google Gemini Enterprise <-> Cloud Run."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request, status

from core.auth import extract_caller_principal
from core.config import AppConfig
from core.schemas import Citation, HealthResponse, SmritiQueryRequest, SmritiQueryResponse
from domains.base import DomainRegistry
from domains.bootstrap import build_default_registry

_IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _extract_trace_id(headers: Mapping[str, str]) -> str:
    """Preserve GCP X-Cloud-Trace-Context trace ID when available, else generate UUID4."""
    cloud_trace = headers.get("x-cloud-trace-context") or headers.get("X-Cloud-Trace-Context")
    if cloud_trace:
        trace_part = cloud_trace.split("/", 1)[0].strip()
        if trace_part:
            return trace_part
    return uuid.uuid4().hex


def create_app(
    *,
    registry: DomainRegistry | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    """Create a stateless Smriti v2 FastAPI application instance."""
    cfg = config or AppConfig.from_env()
    domain_registry = registry or build_default_registry()

    application = FastAPI(
        title="Smriti v2 Enterprise Intelligence API",
        version=cfg.version,
        description=(
            "High-code, domain-agnostic Enterprise Intelligence & Organizational Memory "
            "gateway invoked via OpenAPI 3.0 from Google Gemini Enterprise."
        ),
    )

    @application.get(
        "/health",
        response_model=HealthResponse,
        operation_id="healthCheck",
        summary="Cloud Run readiness and liveness probe",
    )
    async def health_check() -> HealthResponse:
        now_ist = datetime.now(tz=_IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")
        return HealthResponse(
            service=cfg.service_name,
            version=cfg.version,
            registered_domains=domain_registry.list_domains(),
            timestamp_ist=now_ist,
        )

    @application.post(
        "/v1/query",
        response_model=SmritiQueryResponse,
        operation_id="querySmriti",
        summary="Execute a deterministic Smriti enterprise query",
    )
    async def query_smriti(
        payload: SmritiQueryRequest,
        request: Request,
    ) -> SmritiQueryResponse:
        started_ns = time.perf_counter_ns()
        trace_id = _extract_trace_id(request.headers)
        caller_wif = extract_caller_principal(
            request.headers,
            require_auth=cfg.require_auth,
            trust_cloud_run_iam_bearer=cfg.trust_cloud_run_iam_bearer,
        )

        try:
            plugin = domain_registry.resolve(
                payload.domain_hint,
                fallback_default=cfg.default_domain,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

        parsed_intent = {
            "question": payload.question.strip(),
            "domain_id": plugin.domain_id,
            "session_id": payload.session_id,
            "caller_wif": caller_wif,
            "trace_id": trace_id,
        }

        refusal_text = plugin.check_known_refusal(parsed_intent)
        if refusal_text is not None:
            now_ist = datetime.now(tz=_IST).strftime("%d %b %Y %H:%M:%S IST")
            elapsed_ms = max(0, (time.perf_counter_ns() - started_ns) // 1_000_000)
            refusal_citation = Citation(
                source="Deterministic Guardrail",
                object_name=f"domains.{plugin.domain_id}.known_refusals",
                date_window_ist=now_ist,
                note="Intercepted before any external connector call.",
            )
            return SmritiQueryResponse(
                headline=f"Scope Boundary · {plugin.domain_id}",
                answer_markdown=(
                    f"{refusal_text}\n\n"
                    f"[Source: {refusal_citation.source} {refusal_citation.object_name} · "
                    f"{refusal_citation.date_window_ist}]"
                ),
                citations=[refusal_citation],
                degraded_sources=[],
                latency_ms=elapsed_ms,
                trace_id=trace_id,
            )

        raw_bundle = await plugin.collect_parallel(parsed_intent)
        verified_payload = plugin.compute_verified_metrics(parsed_intent, raw_bundle)
        rendered = await plugin.render_response(verified_payload)

        elapsed_ms = max(0, (time.perf_counter_ns() - started_ns) // 1_000_000)
        return rendered.model_copy(
            update={
                "latency_ms": elapsed_ms,
                "trace_id": trace_id,
            }
        )

    return application


app = create_app()
