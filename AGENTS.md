# AGENTS.md — Smriti v2 Engineering & AI Constitution

> Read this file first in every session. Every rule here is a hard invariant learned from Smriti v0 (`voice-rag-master`) and Smriti v1 (Low-Code Gemini Enterprise POC).

---

## 1. What We Are Building

**Smriti v2** is a High-Code, multi-domain Enterprise Intelligence & Organizational Memory platform deployed on **Google Cloud Run** and surfaced to business users through **Google Gemini Enterprise (`Agents > Smriti`)**.

- **Domain #1 (Active):** Performance Marketing (`domains/performance_marketing/`) for AGEasy / Antara Senior Care.
- **Platform Goal:** Keep `core/` 100% domain-agnostic (Auth, Router, Parallel Runner, Smriti Memory, Guardrails, Citations) so future company domains (CRM/Leads, Ops, Finance, Inventory) plug in cleanly under `domains/`.

---

## 2. Non-Negotiable Architecture Rules

1. **90% Python, 10% LLM:**
   - Python fetches data, validates schemas, computes **100% of arithmetic** (ROAS, CAC, CPM, `%` deltas, MoM/WoW/DoD/YoY, budget phasing), checks refusals, and enforces guardrails.
   - LLMs (`temperature=0` for routing/extraction) are ONLY used for:
     1. Fast intent & entity extraction (`core/router.py`)
     2. Structuring approved knowledge chunks during ingestion (`core/memory/`)
     3. Turning pre-computed, verified JSON numbers into executive prose (`narrator`)
   - **NEVER** ask an LLM to sum columns, divide ratios, or run a BigQuery `SELECT` just to do division.

2. **Parallel Execution Only — Zero Sequential Tool Loops:**
   - Independent connector calls MUST execute concurrently via `asyncio.gather` inside `core/runner.py` with strict per-connector timeouts (`<= 8s`).
   - Target wall-clock latency: **`3–6s`** for KPI/time-grain queries, **`10–18s`** for full multi-source Campaign Plans.
   - If one non-critical live connector (e.g., Ad Library or Mixpanel) times out, degrade gracefully and note the unavailable source rather than failing the request.

3. **Strict Source-of-Truth Separation (The 6 Core Connectors):**
   - **BigQuery (`bigquery_poc.py`):** ONLY source of truth for Revenue, Delivered Orders (`Status_ = 'DELIVERED'`), RTO, Historical Spend, Net ROAS, and Net CAC.
   - **Mixpanel (`mixpanel_live.py`):** ONLY for website sessions and 3-step funnel progression. Never read orders or revenue from Mixpanel.
   - **Meta Ads Account API (`meta_ads_account.py`):** Live status, budgets, Opportunity Score, and real-time CTR/CPC/CPM on **our own** Meta ads. Never use for Net ROAS/CAC.
   - **Google Ads Account API (`google_ads_account.py`):** Live status, budgets, search terms, Impression Share, and real-time CTR/CPC/Spend on **our own** Google ads. Never use for Net ROAS/CAC.
   - **Meta Ad Library (`meta_ad_library.py`):** Public rival active Meta ads (creatives, hooks, copy, formats). Contains **zero** spend/performance metrics—never rank rival ads by performance.
   - **Google Ads Transparency (`google_ad_transparency.py`):** Public rival active Google Search/YouTube/Display ads (headlines, formats, offers). Contains **zero** spend/performance metrics—never rank rival ads by performance.

4. **Strict Read-Only External Connectors:**
   - Smriti NEVER creates, edits, pauses, deletes, or launches ads, budgets, or Mixpanel/warehouse records.
   - Only **Smriti Memory (`core/memory/`)** has a governed write path, restricted exclusively to verified organizational knowledge (`OFFICIAL_DOC` uploads or explicit `APPROVED_DECISION` saves).

5. **Identity & Security Invariants:**
   - Workforce Identity Federation (`ge-pilot-wif`) principals MUST be normalized via `.strip().lower()` at the API gateway before any permission or memory lookup.
   - Every SQL query MUST pass `sqlglot` AST validation (`SELECT` only, allowlisted tables/views only, `maximum_bytes_billed` set) and go through a single BigQuery client entry point.
   - Strip all PII (phone numbers, emails, customer names, street addresses) at both the SQL projection layer and output regex guardrail layer.

6. **100% Cloud-Native State — Zero Local Databases or Files:**
   - **NEVER** create local `SQLite`, local `ChromaDB`, local `.pkl`/JSON state files, or local disk caches (Cloud Run containers are stateless and wipe local disk).
   - **Short-Term Chat Memory:** Managed natively by Gemini Enterprise (`session_id` + thread history).
   - **Vector DB & Document RAG:** **Google Cloud Storage (GCS)** + **Vertex AI Search** (`Connected data stores` in Gemini Enterprise).
   - **Structured "Smriti" Facts:** **BigQuery** (`Gemini_POC.smriti_memory_chunks` with L1/L2/L3 hierarchy + native `VECTOR_SEARCH` when needed).
   - **Caching:** BigQuery native 24h query cache (`use_query_cache=True`) + lightweight 5–10 min TTL cache (`core/cache.py`, upgradable to Firestore/Cloud Memorystore Redis via config without code changes).
   - Local laptop runs ONLY Python code + offline `pytest` mocks (or connects to GCP `dev` resources via `gcloud auth application-default login`).

---

## 3. Mathematical & Formatting Invariants

- **Never Average Ratios:** Always compute `ROAS = SUM(delivered_revenue) / SUM(performance_spend)` and `CAC = SUM(performance_spend) / SUM(delivered_orders)`.
- **Brand Exclusion:** Brand awareness spend NEVER enters ROAS or CAC denominators.
- **CPM Formula:** `SUM(spend) / SUM(impressions) * 1000` (assert `CPM >= 1.0` when spend & impressions > 0 to catch missing `* 1000`).
- **Currency & Locale:** Format INR using Indian grouping (`Rs 3,00,000` or `₹3,00,000` consistently per view), timezone `Asia/Kolkata` (`IST`).
- **Inline Citations Mandatory:** Every table and key metric block MUST declare its exact source and date window (e.g., `[Source: BigQuery ge_family_monthly · Aug–Oct 2026]`, `[Source: Mixpanel · 27 Oct–22 Nov 2026 IST]`).

---

## 4. How We Build (Workflow Rules for Humans & AI Agents)

1. **One Vertical Slice at a Time:** Build, unit-test, and verify one end-to-end slice before starting the next (see `docs/ROADMAP.md`). Never generate untested scaffolding across 20 files at once.
2. **No God Files:** Keep every module focused (`< 300 lines` target). Keep `core/` free of any marketing-specific words (`ROAS`, `Nebulizer`, `Meta` belong strictly inside `domains/performance_marketing/`).
3. **Every Connector Gets Offline Unit Tests First:** Mock external HTTP/BigQuery responses with realistic fixtures in `tests/unit/` so the entire test suite runs in `< 5 seconds` with zero cloud credentials required.
4. **Docs Stay Synced:** If a schema, business rule, or known refusal changes, update `docs/DOMAIN_PERF_MARKETING.md` in the same commit.
