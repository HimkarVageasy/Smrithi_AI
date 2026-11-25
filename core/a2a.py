"""Domain-agnostic Agent2Agent (A2A) JSON-RPC 2.0 & Agent Card adapter for Gemini Enterprise."""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import Request

from core.schemas import SmritiQueryRequest, SmritiQueryResponse


def build_agent_card(request: Request, *, service_name: str, version: str) -> dict[str, Any]:
    """Construct the A2A v0.3.0 Agent Card served at /.well-known/agent.json."""
    configured_url = os.getenv("SMRITI_PUBLIC_URL", "").strip()
    if configured_url:
        base_url = configured_url.rstrip("/") + "/"
    else:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", request.url.netloc)
        base_url = f"{proto}://{host}/"

    return {
        "protocolVersion": "0.3.0",
        "name": service_name,
        "description": (
            "High-code, domain-agnostic Enterprise Intelligence and Organizational Memory "
            "engine hosted on Google Cloud Run."
        ),
        "url": base_url,
        "version": version,
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
        },
        "defaultInputModes": ["text/plain", "text"],
        "defaultOutputModes": ["text/plain", "text"],
        "skills": [
            {
                "id": "smriti_enterprise_query",
                "name": "Smriti Enterprise Intelligence",
                "description": (
                    "Answers deterministic enterprise KPI, planning, competitor, and "
                    "institutional memory queries with verified citations."
                ),
                "tags": ["enterprise", "analytics", "memory"],
                "examples": ["Ping Smriti v2"],
            }
        ],
    }


def extract_a2a_user_text_and_context(params: dict[str, Any]) -> tuple[str, str]:
    """Extract user question text and contextId from an A2A message/send params dict."""
    message_obj = params.get("message")
    if not isinstance(message_obj, dict):
        message_obj = {}

    context_id = (
        str(message_obj.get("contextId") or params.get("contextId") or params.get("id") or "")
        .strip()
        or uuid.uuid4().hex
    )

    collected_texts: list[str] = []
    parts = message_obj.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_piece = part["text"].strip()
                if text_piece:
                    collected_texts.append(text_piece)

    if not collected_texts:
        content_obj = message_obj.get("content")
        if isinstance(content_obj, dict) and isinstance(content_obj.get("text"), str):
            fallback_piece = content_obj["text"].strip()
            if fallback_piece:
                collected_texts.append(fallback_piece)

    return "\n".join(collected_texts).strip(), context_id


def build_a2a_jsonrpc_success(
    *,
    rpc_id: str | int | None,
    context_id: str,
    query_response: SmritiQueryResponse,
) -> dict[str, Any]:
    """Wrap a verified SmritiQueryResponse into an A2A v0.3.0 JSON-RPC message result."""
    full_markdown = f"### {query_response.headline}\n\n{query_response.answer_markdown}"
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "kind": "message",
            "messageId": uuid.uuid4().hex,
            "contextId": context_id,
            "role": "agent",
            "parts": [
                {
                    "kind": "text",
                    "text": full_markdown,
                }
            ],
        },
    }


def build_a2a_jsonrpc_error(
    *,
    rpc_id: str | int | None,
    code: int,
    message: str,
) -> dict[str, Any]:
    """Build a standard JSON-RPC 2.0 error envelope."""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def to_smriti_request(question_text: str, context_id: str) -> SmritiQueryRequest:
    """Convert extracted A2A text + context into a validated SmritiQueryRequest."""
    padded_question = question_text if len(question_text) >= 2 else f"{question_text} ?"
    return SmritiQueryRequest(question=padded_question, session_id=context_id)
