"""Offline unit tests for Slice 4: Smriti Memory (L1-L3, XLSX/DOCX, ACLs) & Multi-Domain Router."""

from __future__ import annotations

import base64
import io
import zipfile
from collections.abc import Sequence
from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from core.app import create_app
from core.config import AppConfig
from core.memory.store import CloudMemoryStore
from core.schemas import Citation, SmritiQueryResponse
from domains.base import DomainRegistry
from domains.performance_marketing.collectors.bigquery_poc import (
    BigQueryPocCollector,
    QueryParamTuple,
)
from domains.performance_marketing.collectors.google_ad_transparency import (
    GoogleAdTransparencyCollector,
)
from domains.performance_marketing.collectors.google_ads_account import GoogleAdsAccountCollector
from domains.performance_marketing.collectors.meta_ad_library import MetaAdLibraryCollector
from domains.performance_marketing.collectors.meta_ads_account import MetaAdsAccountCollector
from domains.performance_marketing.collectors.mixpanel_live import (
    MixpanelLiveCollector,
    PaidChannelFilter,
)
from domains.performance_marketing.plugin import PerformanceMarketingPlugin


def _build_minimal_xlsx_bytes(headers: list[str], row_values: list[str]) -> bytes:
    """Create a valid in-memory `.xlsx` OpenXML zip without external libraries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        all_strs = headers + row_values
        ss_items = "".join(f"<si><t>{val}</t></si>" for val in all_strs)
        zf.writestr(
            "xl/sharedStrings.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><sst>{ss_items}</sst>',
        )
        r1 = "".join(
            f'<c r="{chr(65 + i)}1" t="s"><v>{i}</v></c>' for i in range(len(headers))
        )
        r2 = "".join(
            f'<c r="{chr(65 + i)}2" t="s"><v>{len(headers) + i}</v></c>'
            for i in range(len(row_values))
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<worksheet><sheetData><row r=\"1\">{r1}</row>"
            f"<row r=\"2\">{r2}</row></sheetData></worksheet>",
        )
    return buf.getvalue()


def _build_minimal_docx_bytes(paragraphs: list[str]) -> bytes:
    """Create a valid in-memory `.docx` OpenXML zip without external libraries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        body_xml = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body_xml}</w:body></w:document>",
        )
    return buf.getvalue()


def _build_in_memory_store(
    *, approvers_raw: str = "himkar.v.ageasy@antaraseniorcare.com"
) -> tuple[CloudMemoryStore, list[dict[str, Any]], list[str]]:
    stored_rows: list[dict[str, Any]] = []
    gcs_paths: list[str] = []

    async def _insert(rows: list[dict[str, Any]]) -> None:
        stored_rows.extend(rows)

    async def _query(sql: str, params: Sequence[tuple[str, str, Any]]) -> list[dict[str, Any]]:
        dom = next((val for name, _, val in params if name == "domain_id"), "")
        return [r for r in stored_rows if r["domain_id"] == dom]

    async def _gcs(bucket: str, obj_path: str, raw: bytes) -> str:
        uri = f"gs://{bucket}/{obj_path}"
        gcs_paths.append(uri)
        return uri

    store = CloudMemoryStore(
        gcs_bucket="smriti-test-bucket",
        approvers_raw=approvers_raw,
        query_fn=_query,
        insert_fn=_insert,
        gcs_upload_fn=_gcs,
    )
    return store, stored_rows, gcs_paths


def _build_marketing_plugin(store: CloudMemoryStore) -> PerformanceMarketingPlugin:
    async def _bq_exec(sql: str, params: Sequence[QueryParamTuple]) -> list[dict[str, Any]]:
        if "ge_family_monthly" in sql.lower():
            return [
                {
                    "month": "2026-10-01",
                    "settle_state": "mostly settled",
                    "product_family": "diaper",
                    "spend": 100_000.0,
                    "net_revenue": 185_000.0,
                    "net_orders": 370,
                }
            ]
        return []

    async def _mp_step(
        step: str, start: date, end: date, sku: str | None, channel: PaidChannelFilter
    ) -> int:
        return 8_000 if step == MixpanelLiveCollector.STEP_PRODUCT_VIEW else 1_000

    return PerformanceMarketingPlugin(
        bq_collector=BigQueryPocCollector(query_executor=_bq_exec),
        mixpanel_collector=MixpanelLiveCollector(step_fetcher=_mp_step),
        meta_collector=MetaAdsAccountCollector(access_token=""),
        google_collector=GoogleAdsAccountCollector(enabled=False),
        meta_library_collector=MetaAdLibraryCollector(access_token=""),
        google_transparency_collector=GoogleAdTransparencyCollector(enabled=False),
        memory_store=store,
    )


class _DummyCrmPlugin:
    """Second company domain verifying single-agent behind-the-scenes routing & isolation."""

    domain_id = "senior_living_crm"

    def __init__(self, memory_store: CloudMemoryStore) -> None:
        self.memory_store = memory_store

    def score_domain_match(self, question: str) -> int:
        low = question.lower()
        return 10 if any(k in low for k in ("tour", "lead", "antara noida", "residency")) else 0

    def check_known_refusal(self, parsed_intent: dict[str, Any]) -> str | None:
        return None

    async def collect_parallel(self, parsed_intent: dict[str, Any]) -> dict[str, Any]:
        chunks = await self.memory_store.recall(domain_id=self.domain_id, limit=5)
        return {"chunks": chunks, "trace_id": parsed_intent["trace_id"]}

    def compute_verified_metrics(
        self, parsed_intent: dict[str, Any], raw_bundle: dict[str, Any]
    ) -> dict[str, Any]:
        return raw_bundle

    async def render_response(self, verified_payload: dict[str, Any]) -> SmritiQueryResponse:
        cnt = len(verified_payload["chunks"])
        cite = Citation(
            source="Smriti Memory",
            object_name="senior_living_crm",
            date_window_ist="Nov 2026 IST",
            row_count=cnt,
        )
        return SmritiQueryResponse(
            headline="Senior Living CRM Leads",
            answer_markdown=(
                f"CRM domain active with `{cnt}` CRM memory chunks. "
                "[Source: Smriti Memory senior_living_crm · Nov 2026 IST]"
            ),
            citations=[cite],
            degraded_sources=[],
            latency_ms=0,
            trace_id=str(verified_payload["trace_id"]),
        )


def test_xlsx_ruleset_ingest_archives_to_gcs_and_overrides_campaign_plan_split() -> None:
    store, _, gcs_paths = _build_in_memory_store()
    reg = DomainRegistry()
    reg.register(_build_marketing_plugin(store), is_default=True)
    client = TestClient(create_app(registry=reg, memory_store=store))

    xlsx_bytes = _build_minimal_xlsx_bytes(
        ["product_family", "prospecting_pct", "retargeting_pct", "rule_note"],
        ["adult diapers", "70%", "30%", "Repeat buyers convert strongly in 7d retargeting"],
    )
    ingest_resp = client.post(
        "/v1/memory/ingest",
        headers={"X-Goog-Authenticated-User-Email": "Himkar.V.Ageasy@AntaraSeniorCare.com"},
        json={
            "domain_id": "performance_marketing",
            "filename": "Diaper_Ruleset_2026.xlsx",
            "content_base64": base64.b64encode(xlsx_bytes).decode("ascii"),
        },
    )
    assert ingest_resp.status_code == 200
    ing_body = ingest_resp.json()
    assert ing_body["chunks_indexed"] == 2  # L1 Summary + L3 Channel_Ruleset
    assert gcs_paths == [
        "gs://smriti-test-bucket/domains/performance_marketing/rulesets/Diaper_Ruleset_2026.xlsx"
    ]

    plan_resp = client.post(
        "/v1/query",
        json={
            "question": (
                "plan an ad campaign for this winter for adult diaper pants "
                "with budget of rupees 4 lakhs"
            )
        },
    )
    assert plan_resp.status_code == 200
    md = plan_resp.json()["answer_markdown"]
    assert "Prospecting (70%)" in md
    assert "Retargeting (30%)" in md
    assert "Diaper_Ruleset_2026.xlsx" in md
    assert "Institutional Memory & Ruleset Learnings" in md
    assert "Rs 4,00,000" in md


def test_docx_ingest_scrubs_pii_and_serves_recall_and_chat_approver_gate() -> None:
    store, stored_rows, _ = _build_in_memory_store()
    reg = DomainRegistry()
    reg.register(_build_marketing_plugin(store), is_default=True)
    client = TestClient(create_app(registry=reg, memory_store=store))

    docx_bytes = _build_minimal_docx_bytes(
        [
            "# Dec 2025 Respiratory Post-Mortem",
            "Nebulizer hook SV_CoughAK held 4.48% CTR during winter AQI spike. "
            " Escalation contact +91 9876543210.",
        ]
    )
    resp = client.post(
        "/v1/memory/ingest",
        headers={"X-Goog-Authenticated-User-Email": "himkar.v.ageasy@antaraseniorcare.com"},
        json={
            "domain_id": "performance_marketing",
            "filename": "Dec_2025_Respi_PostMortem.docx",
            "content_base64": base64.b64encode(docx_bytes).decode("ascii"),
        },
    )
    assert resp.status_code == 200
    assert all("9876543210" not in r["content_text"] for r in stored_rows)

    recall = client.post(
        "/v1/query",
        json={"question": "What worked last winter in our Nebulizer post-mortem?"},
    )
    assert recall.status_code == 200
    assert "SV_CoughAK held 4.48% CTR" in recall.json()["answer_markdown"]

    # Unauthorized user blocked from chat save
    blocked = client.post(
        "/v1/query",
        headers={"X-Goog-Authenticated-User-Email": "viewer@antaraseniorcare.com"},
        json={"question": "Save to Smriti memory: cap nebulizer Phase 1 at Rs 6,000/day"},
    )
    assert "Memory Write Governance Boundary" in blocked.json()["answer_markdown"]

    # Approved lead succeeds
    allowed = client.post(
        "/v1/query",
        headers={"X-Goog-Authenticated-User-Email": "Himkar.V.Ageasy@AntaraSeniorCare.com"},
        json={"question": "Save to Smriti memory: cap nebulizer Phase 1 at Rs 6,000/day"},
    )
    assert "Saved to Smriti Institutional Memory (`APPROVED_DECISION`)" in (
        allowed.json()["answer_markdown"]
    )


def test_single_agent_auto_routes_across_domains_with_strict_memory_and_acl_isolation(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("SMRITI_DOMAIN_ACL", "senior_living_crm:@crm.antara.com")
    store, _, _ = _build_in_memory_store(approvers_raw="*")
    reg = DomainRegistry()
    reg.register(_build_marketing_plugin(store), is_default=True)
    reg.register(_DummyCrmPlugin(store))
    client = TestClient(create_app(registry=reg, config=AppConfig(env="dev"), memory_store=store))

    # Ingest a CRM SOP under senior_living_crm
    client.post(
        "/v1/memory/ingest",
        headers={"X-Goog-Authenticated-User-Email": "lead@crm.antara.com"},
        json={
            "domain_id": "senior_living_crm",
            "filename": "Antara_Noida_Tour_SOP.md",
            "text_content": "# Tour SLA\nCall senior living inquiry within 10 minutes.",
            "entity_tags": ["nebulizer"],  # Even with colliding tag, domain_id blocks bleed!
        },
    )

    # Marketing recall NEVER sees CRM chunks
    mkt_recall = client.post(
        "/v1/query",
        headers={"X-Goog-Authenticated-User-Email": "mkt@ageasy.com"},
        json={"question": "Recall Smriti memory for nebulizer"},
    )
    assert "Antara_Noida_Tour_SOP.md" not in mkt_recall.json()["answer_markdown"]

    # Unauthorized marketing user asking CRM question hits Department Access Boundary
    denied_crm = client.post(
        "/v1/query",
        headers={"X-Goog-Authenticated-User-Email": "mkt@ageasy.com"},
        json={"question": "How many Antara Noida tour leads booked?"},
    )
    assert "Department Access Boundary" in denied_crm.json()["answer_markdown"]

    # Authorized CRM user gets auto-routed to senior_living_crm behind the single Smriti agent
    ok_crm = client.post(
        "/v1/query",
        headers={"X-Goog-Authenticated-User-Email": "lead@crm.antara.com"},
        json={"question": "How many Antara Noida tour leads booked?"},
    )
    assert "CRM domain active with `3` CRM memory chunks" in ok_crm.json()["answer_markdown"]
