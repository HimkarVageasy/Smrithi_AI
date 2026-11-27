"""Gemini Embedding client & pure-Python cosine similarity (`gemini-embedding-001`)."""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

EmbeddingTaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]
EmbedBatchCallable = Callable[[Sequence[str], EmbeddingTaskType], Awaitable[list[list[float]]]]


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Compute exact cosine similarity in [-1.0, 1.0] in pure Python (`0.0` if empty)."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a <= 1e-12 or norm_b <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


class GeminiEmbedder:
    """Stateless wrapper around `gemini-embedding-001` with graceful offline/IAM fallback."""

    MODEL_ID: str = "gemini-embedding-001"
    DIMENSIONS: int = 768

    def __init__(
        self,
        *,
        project_id: str | None = None,
        location: str | None = None,
        api_key: str | None = None,
        embed_fn: EmbedBatchCallable | None = None,
    ) -> None:
        self._project_id = (project_id or os.getenv("GCP_PROJECT_ID", "gemini-poc-503210")).strip()
        self._location = (location or os.getenv("GCP_LOCATION", "europe-west1")).strip()
        raw_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self._api_key = raw_key.strip()
        self._embed_fn = embed_fn
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai  # type: ignore[import-not-found]

            if self._api_key:
                self._client = genai.Client(api_key=self._api_key)
            else:
                self._client = genai.Client(
                    vertexai=True,
                    project=self._project_id,
                    location=self._location,
                )
        return self._client

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        task_type: EmbeddingTaskType = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        """Generate 768-d embeddings; return empty vectors cleanly if SDK/API is unavailable."""
        cleaned = [t.strip()[:4000] or " " for t in texts]
        if not cleaned:
            return []

        if self._embed_fn is not None:
            return await self._embed_fn(cleaned, task_type)

        if os.getenv("SMRITI_ENV", "dev").strip().lower() == "dev" and not self._api_key:
            # Avoid slow ADC timeouts during unauthenticated local runs unless explicitly enabled.
            if os.getenv("SMRITI_ENABLE_VERTEX_EMBEDDINGS", "").strip().lower() not in {
                "1",
                "true",
                "yes",
            }:
                return [[] for _ in cleaned]

        def _call_sync() -> list[list[float]]:
            from google.genai import types  # type: ignore[import-not-found]

            client = self._get_client()
            resp = client.models.embed_content(
                model=self.MODEL_ID,
                contents=list(cleaned),
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self.DIMENSIONS,
                ),
            )
            vectors: list[list[float]] = []
            for emb in resp.embeddings or []:
                vals = [round(float(x), 6) for x in (emb.values or [])]
                vectors.append(vals)
            while len(vectors) < len(cleaned):
                vectors.append([])
            return vectors

        try:
            return await asyncio.wait_for(asyncio.to_thread(_call_sync), timeout=3.0)
        except Exception:
            return [[] for _ in cleaned]
