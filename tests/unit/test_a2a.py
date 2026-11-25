"""Unit tests for Gemini Enterprise Agent2Agent (A2A) protocol endpoints (`core/a2a.py`)."""

from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from core.app import create_app
from core.config import AppConfig


def test_well_known_agent_card_endpoints() -> None:
    client = TestClient(create_app())

    for path in ("/.well-known/agent.json", "/.well-known/agent-card.json"):
        response = client.get(
            path,
            headers={"x-forwarded-proto": "https", "host": "smriti.run.app"},
        )
        assert response.status_code == 200
        card = response.json()
        assert card["protocolVersion"] == "0.3.0"
        assert card["url"] == "https://smriti.run.app/"
        assert "text/plain" in card["defaultInputModes"]
        assert len(card["skills"]) == 1


def test_a2a_message_send_executes_smriti_pipeline_with_serverless_auth() -> None:
    cfg = AppConfig(env="prod", require_auth=True, trust_cloud_run_iam_bearer=True)
    client = TestClient(create_app(config=cfg))

    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(
                {"email": "Service-988560645054@gcp-sa-discoveryengine.iam.gserviceaccount.com"}
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    serverless_token = f"Bearer {header}.{payload}.sig"

    rpc_payload = {
        "jsonrpc": "2.0",
        "id": "req-101",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "msg-1",
                "contextId": "ctx-ge-session-1",
                "role": "user",
                "parts": [{"kind": "text", "text": "Ping Smriti v2"}],
            }
        },
    }

    response = client.post(
        "/",
        json=rpc_payload,
        headers={"X-Serverless-Authorization": serverless_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == "req-101"
    result = body["result"]
    assert result["kind"] == "message"
    assert result["role"] == "agent"
    assert result["contextId"] == "ctx-ge-session-1"
    reply_text = result["parts"][0]["text"]
    assert "Hello Smriti v2" in reply_text
    assert "service-988560645054@gcp-sa-discoveryengine.iam.gserviceaccount.com" in reply_text


def test_a2a_rejects_unknown_jsonrpc_method() -> None:
    client = TestClient(create_app())
    response = client.post("/", json={"jsonrpc": "2.0", "id": "9", "method": "unknown/method"})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32601
