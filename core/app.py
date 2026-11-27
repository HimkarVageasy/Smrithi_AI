"""Domain-agnostic FastAPI gateway for Google Gemini Enterprise (A2A & REST) <-> Cloud Run."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status

from core.a2a import (
    build_a2a_jsonrpc_error,
    build_a2a_jsonrpc_success,
    build_agent_card,
    extract_a2a_user_text_and_context,
    to_smriti_request,
)
from core.auth import extract_caller_principal
from core.config import AppConfig
from core.domain_router import DomainAccessDeniedError, resolve_domain_for_query
from core.memory.ingest import ingest_domain_document
from core.memory.schemas import MemoryIngestRequest, MemoryIngestResponse
from core.memory.store import CloudMemoryStore, MemoryWriteForbiddenError
from core.schemas import Citation, HealthResponse, SmritiQueryRequest, SmritiQueryResponse
from domains.base import DomainRegistry
from domains.bootstrap import build_default_registry

_IST = timezone(timedelta(hours=5, minutes=30), name="IST")
_SUPPORTED_A2A_METHODS = frozenset({"message/send", "tasks/send", "SendMessage"})


def _extract_trace_id(headers: Mapping[str, str]) -> str:
    """Preserve GCP X-Cloud-Trace-Context trace ID when available, else generate UUID4."""
    cloud_trace = headers.get("x-cloud-trace-context") or headers.get("X-Cloud-Trace-Context")
    if cloud_trace:
        trace_part = cloud_trace.split("/", 1)[0].strip()
        if trace_part:
            return trace_part
    return uuid.uuid4().hex


async def _run_domain_pipeline(
    *,
    payload: SmritiQueryRequest,
    headers: Mapping[str, str],
    cfg: AppConfig,
    domain_registry: DomainRegistry,
) -> SmritiQueryResponse:
    started_ns = time.perf_counter_ns()
    trace_id = _extract_trace_id(headers)
    caller_wif = extract_caller_principal(
        headers,
        require_auth=cfg.require_auth,
        trust_cloud_run_iam_bearer=cfg.trust_cloud_run_iam_bearer,
    )

    try:
        plugin = resolve_domain_for_query(
            payload.question,
            domain_hint=payload.domain_hint,
            caller_wif=caller_wif,
            registry=domain_registry,
            default_domain=cfg.default_domain,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DomainAccessDeniedError as exc:
        now_ist = datetime.now(tz=_IST).strftime("%d %b %Y %H:%M:%S IST")
        elapsed_ms = max(0, (time.perf_counter_ns() - started_ns) // 1_000_000)
        acl_cite = Citation(
            source="Deterministic Guardrail",
            object_name="core.domain_router.SMRITI_DOMAIN_ACL",
            date_window_ist=now_ist,
        )
        return SmritiQueryResponse(
            headline="Domain Access Restricted",
            answer_markdown=(
                f"**Department Access Boundary:** {exc}\n\n"
                f"[Source: {acl_cite.source} {acl_cite.object_name} · {now_ist}]"
            ),
            citations=[acl_cite],
            degraded_sources=[],
            latency_ms=elapsed_ms,
            trace_id=trace_id,
        )

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
    return rendered.model_copy(update={"latency_ms": elapsed_ms, "trace_id": trace_id})


def create_app(
    *,
    registry: DomainRegistry | None = None,
    config: AppConfig | None = None,
    memory_store: CloudMemoryStore | None = None,
) -> FastAPI:
    """Create a stateless Smriti v2 FastAPI application instance."""
    cfg = config or AppConfig.from_env()
    domain_registry = registry or build_default_registry()
    shared_memory = memory_store or CloudMemoryStore()

    application = FastAPI(
        title="Smriti v2 Enterprise Intelligence API",
        version=cfg.version,
        description=(
            "High-code, domain-agnostic Enterprise Intelligence & Organizational Memory "
            "gateway invoked via A2A or OpenAPI 3.0 from Google Gemini Enterprise."
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

    @application.get("/.well-known/agent.json", include_in_schema=False)
    @application.get("/.well-known/agent-card.json", include_in_schema=False)
    async def a2a_agent_card(request: Request) -> dict[str, Any]:
        return build_agent_card(request, service_name=cfg.service_name, version=cfg.version)

    @application.post("/", include_in_schema=False)
    @application.post("/a2a", include_in_schema=False)
    async def a2a_jsonrpc(request: Request) -> dict[str, Any]:
        try:
            rpc_body = await request.json()
        except Exception:
            return build_a2a_jsonrpc_error(rpc_id=None, code=-32700, message="Invalid JSON body")

        if not isinstance(rpc_body, dict):
            return build_a2a_jsonrpc_error(rpc_id=None, code=-32600, message="Invalid Request")

        rpc_id = rpc_body.get("id")
        method = str(rpc_body.get("method") or "")
        if method not in _SUPPORTED_A2A_METHODS:
            return build_a2a_jsonrpc_error(
                rpc_id=rpc_id,
                code=-32601,
                message=f"Unsupported A2A method '{method}'",
            )

        params = rpc_body.get("params") if isinstance(rpc_body.get("params"), dict) else {}
        question_text, context_id = extract_a2a_user_text_and_context(params)
        if not question_text:
            return build_a2a_jsonrpc_error(
                rpc_id=rpc_id,
                code=-32602,
                message="A2A message contains no text parts.",
            )

        query_req = to_smriti_request(question_text, context_id)
        query_resp = await _run_domain_pipeline(
            payload=query_req,
            headers=request.headers,
            cfg=cfg,
            domain_registry=domain_registry,
        )
        return build_a2a_jsonrpc_success(
            rpc_id=rpc_id,
            context_id=context_id,
            query_response=query_resp,
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
        return await _run_domain_pipeline(
            payload=payload,
            headers=request.headers,
            cfg=cfg,
            domain_registry=domain_registry,
        )

    @application.post(
        "/v1/memory/ingest",
        response_model=MemoryIngestResponse,
        operation_id="ingestDomainMemory",
        summary="Ingest an official document or spreadsheet into domain-isolated Smriti Memory",
    )
    async def ingest_memory(
        payload: MemoryIngestRequest,
        request: Request,
    ) -> MemoryIngestResponse:
        trace_id = _extract_trace_id(request.headers)
        caller_wif = extract_caller_principal(
            request.headers,
            require_auth=cfg.require_auth,
            trust_cloud_run_iam_bearer=cfg.trust_cloud_run_iam_bearer,
        )
        try:
            plugin = domain_registry.resolve(payload.domain_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        target_store = getattr(plugin, "memory_store", None) or shared_memory
        try:
            return await ingest_domain_document(
                payload,
                plugin=plugin,
                store=target_store,
                caller_wif=caller_wif,
                trace_id=trace_id,
            )
        except MemoryWriteForbiddenError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    return application


app = create_app()
