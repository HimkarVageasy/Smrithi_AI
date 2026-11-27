"""Domain-agnostic Cloud-Native Memory Store (`BigQuery smriti_memory_chunks` + `GCS` archive)."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from core.cache import CacheBackend, build_default_cache
from core.guardrails.output_audit import scrub_pii_text
from core.guardrails.sql_ast import validate_readonly_sql
from core.memory.schemas import MemoryChunk

MemoryQueryFn = Callable[[str, Sequence[tuple[str, str, Any]]], Awaitable[list[dict[str, Any]]]]
MemoryInsertFn = Callable[[list[dict[str, Any]]], Awaitable[None]]
GcsUploadFn = Callable[[str, str, bytes], Awaitable[str]]


class MemoryWriteForbiddenError(PermissionError):
    """Raised when an unauthorized caller attempts to write to Institutional Memory."""


def is_memory_write_authorized(caller_wif: str, *, approvers_raw: str | None = None) -> bool:
    """Verify normalized caller principal against `SMRITI_MEMORY_APPROVERS` allowlist."""
    norm_caller = caller_wif.strip().lower()
    if not norm_caller or norm_caller == "anonymous":
        return False

    cfg = (
        approvers_raw
        if approvers_raw is not None
        else os.getenv("SMRITI_MEMORY_APPROVERS", "")
    ).strip().lower()
    if not cfg:
        return os.getenv("SMRITI_ENV", "dev").strip().lower() == "dev"
    if cfg == "*":
        return True

    entries = [item.strip() for item in cfg.split(",") if item.strip()]
    for entry in entries:
        if entry.startswith("@") and norm_caller.endswith(entry):
            return True
        if norm_caller == entry:
            return True
    return False


class CloudMemoryStore:
    """Stateless `domain_id`-isolated memory engine backed by BigQuery + GCS."""

    TABLE_NAME: str = "smriti_memory_chunks"

    def __init__(
        self,
        *,
        project_id: str | None = None,
        dataset_id: str | None = None,
        gcs_bucket: str | None = None,
        approvers_raw: str | None = None,
        cache: CacheBackend | None = None,
        query_fn: MemoryQueryFn | None = None,
        insert_fn: MemoryInsertFn | None = None,
        gcs_upload_fn: GcsUploadFn | None = None,
    ) -> None:
        self._project_id = (project_id or os.getenv("GCP_PROJECT_ID", "gemini-poc-503210")).strip()
        self._dataset_id = (dataset_id or os.getenv("BIGQUERY_DATASET", "Gemini_POC")).strip()
        self._gcs_bucket = (
            gcs_bucket if gcs_bucket is not None else os.getenv("SMRITI_GCS_BUCKET", "")
        ).strip()
        self._approvers_raw = approvers_raw
        self._cache = cache or build_default_cache()
        self._query_fn = query_fn
        self._insert_fn = insert_fn
        self._gcs_upload_fn = gcs_upload_fn
        self._bq_client: Any = None
        self._table_ensured: bool = False

    @property
    def fq_table(self) -> str:
        return f"`{self._project_id}.{self._dataset_id}.{self.TABLE_NAME}`"

    @property
    def allowlisted_tables(self) -> frozenset[str]:
        short = f"{self._dataset_id}.{self.TABLE_NAME}"
        full = f"{self._project_id}.{short}"
        return frozenset({short, full})

    def _get_bq_client(self) -> Any:
        if self._bq_client is None:
            from google.cloud import bigquery  # type: ignore[import-untyped]

            self._bq_client = bigquery.Client(project=self._project_id)
        return self._bq_client

    def _ensure_table_sync(self) -> None:
        if self._table_ensured:
            return
        client = self._get_bq_client()
        tbl_ref = f"{self._project_id}.{self._dataset_id}.{self.TABLE_NAME}"
        try:
            client.get_table(tbl_ref)
            self._table_ensured = True
            return
        except Exception:
            pass
        ddl = (
            f"CREATE TABLE IF NOT EXISTS {self.fq_table} ("
            "chunk_uuid STRING NOT NULL, parent_chunk_uuid STRING, root_chunk_uuid STRING NOT NULL,"
            " level INT64 NOT NULL, domain_id STRING NOT NULL, trust_tier STRING NOT NULL,"
            " entity_tags ARRAY<STRING>, section_type STRING, content_text STRING NOT NULL,"
            " metrics_json STRING, source_title STRING NOT NULL, gcs_uri STRING,"
            " created_by_wif STRING NOT NULL, approved_by_wif STRING NOT NULL,"
            " created_at_iso STRING NOT NULL) CLUSTER BY domain_id, level"
        )
        client.query(ddl).result(timeout=8.0)
        self._table_ensured = True

    async def archive_raw_file_to_gcs(
        self,
        *,
        domain_id: str,
        subfolder: str,
        filename: str,
        raw_bytes: bytes,
    ) -> str | None:
        """Archive uploaded official doc/spreadsheet under `gs://<bucket>/domains/<domain_id>/`."""
        clean_domain = domain_id.strip().lower()
        safe_name = os.path.basename(filename.strip()).replace(" ", "_")
        object_path = f"domains/{clean_domain}/{subfolder.strip('/')}/{safe_name}"

        if self._gcs_upload_fn is not None:
            bkt = self._gcs_bucket or "mock-bucket"
            return await self._gcs_upload_fn(bkt, object_path, raw_bytes)
        if not self._gcs_bucket:
            return None

        def _upload_sync() -> str:
            from google.cloud import storage  # type: ignore[import-untyped]

            st_client = storage.Client(project=self._project_id)
            bucket = st_client.bucket(self._gcs_bucket)
            blob = bucket.blob(object_path)
            blob.upload_from_string(raw_bytes)
            return f"gs://{self._gcs_bucket}/{object_path}"

        return await asyncio.wait_for(asyncio.to_thread(_upload_sync), timeout=8.0)

    async def save_chunks(self, chunks: Sequence[MemoryChunk], *, caller_wif: str) -> int:
        """Authorize caller, scrub PII, and persist chunks to `smriti_memory_chunks`."""
        if not is_memory_write_authorized(caller_wif, approvers_raw=self._approvers_raw):
            raise MemoryWriteForbiddenError(
                f"Caller '{caller_wif.strip().lower()}' is not in SMRITI_MEMORY_APPROVERS."
            )
        if not chunks:
            return 0

        rows: list[dict[str, Any]] = []
        domains_touched: set[str] = set()
        for ch in chunks:
            domains_touched.add(ch.domain_id)
            rows.append(
                {
                    "chunk_uuid": ch.chunk_uuid,
                    "parent_chunk_uuid": ch.parent_chunk_uuid,
                    "root_chunk_uuid": ch.root_chunk_uuid,
                    "level": int(ch.level),
                    "domain_id": ch.domain_id,
                    "trust_tier": ch.trust_tier,
                    "entity_tags": list(ch.entity_tags),
                    "section_type": ch.section_type,
                    "content_text": scrub_pii_text(ch.content_text),
                    "metrics_json": json.dumps(ch.metrics_json, sort_keys=True),
                    "source_title": ch.source_title,
                    "gcs_uri": ch.gcs_uri,
                    "created_by_wif": ch.created_by_wif,
                    "approved_by_wif": ch.approved_by_wif,
                    "created_at_iso": ch.created_at_iso,
                }
            )

        if self._insert_fn is not None:
            await self._insert_fn(rows)
        else:

            def _insert_sync() -> None:
                self._ensure_table_sync()
                client = self._get_bq_client()
                tbl_ref = f"{self._project_id}.{self._dataset_id}.{self.TABLE_NAME}"
                errors = client.insert_rows_json(tbl_ref, rows)
                if errors:
                    raise RuntimeError(f"BigQuery memory insert failed: {errors}")

            await asyncio.wait_for(asyncio.to_thread(_insert_sync), timeout=8.0)

        self._cache.clear()
        return len(rows)

    async def recall(
        self,
        *,
        domain_id: str,
        entity_tags: Sequence[str] = (),
        keywords: Sequence[str] = (),
        limit: int = 8,
    ) -> list[MemoryChunk]:
        """Retrieve `domain_id`-isolated memory chunks ranked by tag & keyword relevance."""
        norm_domain = domain_id.strip().lower()
        norm_tags = sorted({t.strip().lower() for t in entity_tags if t.strip()})
        norm_kws = sorted({k.strip().lower() for k in keywords if len(k.strip()) >= 3})
        cache_key = f"mem:{norm_domain}:{','.join(norm_tags)}:{','.join(norm_kws)}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return [MemoryChunk.model_validate(item) for item in cached]

        sql = f"""
        SELECT
            chunk_uuid, parent_chunk_uuid, root_chunk_uuid, level, domain_id,
            trust_tier, entity_tags, section_type, content_text, metrics_json,
            source_title, gcs_uri, created_by_wif, approved_by_wif, created_at_iso
        FROM {self.fq_table}
        WHERE domain_id = @domain_id
        ORDER BY created_at_iso DESC
        LIMIT 80
        """
        validated = validate_readonly_sql(sql, allowlisted_tables=self.allowlisted_tables)
        params: list[tuple[str, str, Any]] = [("domain_id", "STRING", norm_domain)]

        if self._query_fn is not None:
            raw_rows = await self._query_fn(validated, params)
        else:

            def _query_sync() -> list[dict[str, Any]]:
                from google.cloud import bigquery  # type: ignore[import-untyped]

                self._ensure_table_sync()
                client = self._get_bq_client()
                q_param = bigquery.ScalarQueryParameter("domain_id", "STRING", norm_domain)
                cfg = bigquery.QueryJobConfig(
                    query_parameters=[q_param],
                    use_query_cache=True,
                    maximum_bytes_billed=100_000_000,
                )
                res_iter = client.query(validated, job_config=cfg).result(timeout=4.0)
                return [dict(r.items()) for r in res_iter]

            raw_rows = await asyncio.wait_for(asyncio.to_thread(_query_sync), timeout=4.5)

        scored: list[tuple[int, MemoryChunk]] = []
        for r in raw_rows:
            if str(r.get("domain_id", "")).strip().lower() != norm_domain:
                continue
            raw_m = r.get("metrics_json")
            parsed_m = json.loads(raw_m) if isinstance(raw_m, str) and raw_m else (raw_m or {})
            chunk = MemoryChunk(
                chunk_uuid=str(r["chunk_uuid"]),
                parent_chunk_uuid=r.get("parent_chunk_uuid"),
                root_chunk_uuid=str(r["root_chunk_uuid"]),
                level=int(r["level"]),  # type: ignore[arg-type]
                domain_id=norm_domain,
                trust_tier=r["trust_tier"],
                entity_tags=list(r.get("entity_tags") or []),
                section_type=str(r.get("section_type") or "General"),
                content_text=str(r["content_text"]),
                metrics_json=parsed_m if isinstance(parsed_m, dict) else {},
                source_title=str(r["source_title"]),
                gcs_uri=r.get("gcs_uri"),
                created_by_wif=str(r["created_by_wif"]),
                approved_by_wif=str(r["approved_by_wif"]),
                created_at_iso=str(r["created_at_iso"]),
            )
            tag_hits = sum(3 for t in norm_tags if t in chunk.entity_tags)
            low_txt = f"{chunk.section_type} {chunk.content_text}".lower()
            kw_hits = sum(1 for k in norm_kws if k in low_txt)
            lvl_bonus = 2 if chunk.level == 3 else (1 if chunk.level == 1 else 0)
            score = tag_hits + kw_hits + lvl_bonus
            if not norm_tags and not norm_kws:
                score += 1
            if score > 0 or not norm_tags:
                scored.append((score, chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        selected = [c for _, c in scored[:limit]]
        self._cache.set(cache_key, [c.model_dump() for c in selected])
        return selected
