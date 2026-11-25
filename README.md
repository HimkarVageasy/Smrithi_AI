# Smriti v2 (`Smrithi_AI`)

High-code, multi-domain **Enterprise Intelligence & Organizational Memory** platform deployed on **Google Cloud Run** (`eu`) and surfaced to business teams through **Google Gemini Enterprise (`Agents > Smriti`)**.

## Core Architecture Principles
- **90% Deterministic Python, 10% LLM:** Python computes 100% of ratios, time-grain deltas (`DoD`, `WoW`, `MoM`, `YoY`), feasibility checks, and budget allocations. LLMs (`temperature=0` for routing/extraction) only classify intent, structure governed knowledge, and narrate verified JSON numbers.
- **Parallel I/O (`asyncio.gather`):** Concurrent read-only connectors with strict `<= 8s` timeouts and graceful degradation—eliminating sequential tool-loop timeouts.
- **100% Cloud-Native State:** Zero local SQLite, ChromaDB, or disk caches. Backed by BigQuery (`Gemini_POC`), GCS + Vertex AI Search, and stateless TTL caching.
- **Pluggable Domain Packs:** `core/` is 100% domain-agnostic; business domains plug in via `DomainPlugin` under `domains/` (launching with **Domain #1: `performance_marketing`**).

## Specification Pack
- [`CODEBASE_MAP.md`](./CODEBASE_MAP.md) — Live Annotated Directory Tree (every file + its role & value, CI-verified)
- [`AGENTS.md`](./AGENTS.md) — Engineering, Security & Math Constitution
- [`HIGH_LEVEL_DESIGN.md`](./HIGH_LEVEL_DESIGN.md) — Executive Topology & Specialist Roles
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — System Architecture, Memory Hierarchy & Execution Flows
- [`LOW_LEVEL_DESIGN.md`](./LOW_LEVEL_DESIGN.md) — API Schemas, `DomainPlugin` Contract, Connectors & Guardrails
- [`DOMAIN_PERF_MARKETING.md`](./DOMAIN_PERF_MARKETING.md) — Domain #1 Rules, 6 Read-Only Connectors & Golden Evals
- [`ROADMAP.md`](./ROADMAP.md) — Vertical-Slice Delivery Plan (Slice 0 -> Slice 5)

## Local Development & Offline Tests
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
uvicorn core.app:app --reload --port 8080
```
