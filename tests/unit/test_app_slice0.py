"""Slice 0 end-to-end gateway unit tests + AGENTS.md architectural invariant checks."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from core.app import create_app
from core.config import AppConfig
from core.schemas import SmritiQueryResponse
from domains.base import DomainPlugin, DomainRegistry
from domains.performance_marketing.plugin import PerformanceMarketingPlugin

REPO_ROOT = Path(__file__).resolve().parents[2]


class _RefusalDummyPlugin:
    """Test double verifying <1s known-refusal short-circuit without calling collectors."""

    domain_id = "dummy_domain"
    collect_called = False

    def check_known_refusal(self, parsed_intent: dict[str, Any]) -> str | None:
        if "impossible metric" in parsed_intent["question"].lower():
            return "Metric unavailable at requested grain. Offering valid alternative."
        return None

    async def collect_parallel(self, parsed_intent: dict[str, Any]) -> dict[str, Any]:
        self.collect_called = True
        return {}

    def compute_verified_metrics(
        self,
        parsed_intent: dict[str, Any],
        raw_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    async def render_response(self, verified_payload: dict[str, Any]) -> SmritiQueryResponse:
        raise AssertionError("render_response should not run on refusal")


def test_performance_marketing_plugin_satisfies_protocol() -> None:
    assert isinstance(PerformanceMarketingPlugin(), DomainPlugin)


def test_health_and_openapi_contract() -> None:
    client = TestClient(create_app())

    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert "performance_marketing" in body["registered_domains"]
    assert body["timestamp_ist"].endswith("+05:30")

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    spec = openapi.json()
    assert spec["paths"]["/v1/query"]["post"]["operationId"] == "querySmriti"


def test_slice0_verified_ping_normalizes_wif_and_propagates_trace_id() -> None:
    cfg = AppConfig(env="prod", require_auth=True)
    client = TestClient(create_app(config=cfg))

    response = client.post(
        "/v1/query",
        json={"question": "Ping Smriti v2"},
        headers={
            "X-Goog-Authenticated-User-Email": (
                "accounts.google.com:Himkar.V.Ageasy@AntaraSeniorCare.com"
            ),
            "X-Cloud-Trace-Context": "105445aa7843bc8bf206b12000100000/1;o=1",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "himkar.v.ageasy@antaraseniorcare.com" in data["answer_markdown"]
    assert data["trace_id"] == "105445aa7843bc8bf206b12000100000"
    assert data["latency_ms"] < 1000
    assert len(data["citations"]) == 1
    assert "[Source:" in data["answer_markdown"]


def test_known_refusal_short_circuits_without_collector_io() -> None:
    dummy = _RefusalDummyPlugin()
    registry = DomainRegistry()
    registry.register(dummy, is_default=True)
    client = TestClient(create_app(registry=registry))

    response = client.post("/v1/query", json={"question": "Give me impossible metric"})
    assert response.status_code == 200
    assert dummy.collect_called is False
    assert "Metric unavailable" in response.json()["answer_markdown"]


def test_unknown_domain_returns_404() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/v1/query",
        json={"question": "Check metrics", "domain_hint": "non_existent_domain"},
    )
    assert response.status_code == 404


def test_core_package_is_strictly_domain_agnostic_and_stateless() -> None:
    forbidden_marketing_terms = re.compile(
        r"\b(roas|cac|nebulizer|mixpanel|meta_ads|performance_marketing)\b",
        re.IGNORECASE,
    )
    forbidden_local_state_modules = {"sqlite3", "chromadb", "pickle", "shelve"}

    for py_file in (REPO_ROOT / "core").rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        line_count = len(source.splitlines())
        assert line_count < 300, f"{py_file.name} exceeds 300-line limit ({line_count} lines)"
        match = forbidden_marketing_terms.search(source)
        assert match is None, f"Domain term '{match.group(0)}' leaked into {py_file}"

    for package_dir in ("core", "domains"):
        for py_file in (REPO_ROOT / package_dir).rglob("*.py"):
            source = py_file.read_text(encoding="utf-8")
            assert len(source.splitlines()) < 300, f"{py_file} exceeds 300-line limit"
            tree = ast.parse(source, filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = {alias.name.split(".")[0] for alias in node.names}
                    assert not (imported & forbidden_local_state_modules), (
                        f"Forbidden local state import in {py_file}: {imported}"
                    )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root_mod = node.module.split(".")[0]
                    assert root_mod not in forbidden_local_state_modules, (
                        f"Forbidden local state import in {py_file}: {root_mod}"
                    )
