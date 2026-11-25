# SMRITI v2 — Production Architecture (`ARCHITECTURE.md`)

> **Status:** Finalized v1.0
> **Platform Target:** Google Cloud (Gemini Enterprise EU + Cloud Run + BigQuery + Vertex AI Search)
> **Core Mission:** Deterministic Enterprise Intelligence + Compounding Organizational Memory ("Smriti"), starting with **Domain #1: Performance Marketing** and architected to plug in future business domains without rewriting the core engine.

---

## 1. Why Smriti v2 Exists (Lessons From v0 & v1)

| Version | What Worked (Keep) | What Broke (Replace) |
|---|---|---|
| **v0 (`voice-rag-master` local MVP)** | Hierarchical 3-level knowledge tree (Summary -> Section -> Atomic Fact); strict SQL AST guardrails; rich domain vocabulary. | 324k-line monolith, 5 competing routers, local SQLite/Chroma files, mock header auth. |
| **v1 (Low-Code GE Workflow)** | Clean `Gemini_POC` BigQuery views; 28 sharp business rules; zero-setup SSO chat UI in Gemini Enterprise. | **15–44 min latency** & `Plaque::Run [DEADLINE_EXCEEDED]` timeouts from sequential LLM tool loops; Meta-only; zero institutional memory retention; single-owner editing lock. |
| **v2 (High-Code Hybrid — This Design)** | Keeps GE Chat UI + `Gemini_POC` views + 28 rules + 3-level Knowledge Memory. | Moves orchestration & math to **parallel Python on Cloud Run** (**4–15s** responses), adds Google Ads + BRD Memory + Multi-Domain plugin design + Git team collaboration. |

---

## 2. Core Architectural Principles

1. **90% Deterministic Python, 10% LLM:** LLMs classify intent and write plain-English narratives. LLMs **never** calculate ratios, sum rows, guess years, or run unconstrained tool loops.
2. **Gemini Enterprise as the Face, Cloud Run as the Brain:** Marketing & business teams use the clean Gemini Enterprise web chat (`Agents > Smriti`). Behind it, a single HTTPS/ADK tool call invokes our FastAPI/Python engine on Google Cloud Run.
3. **Parallel I/O Over Sequential Agent Loops:** All independent data reads (BigQuery, Mixpanel, Meta Ads, Google Ads, Memory Store) execute concurrently via `asyncio.gather` with hard per-connector timeouts (8s), eliminating 44-minute `DEADLINE_EXCEEDED` failures.
4. **Core Platform vs. Domain Packs:** Authentication, parallel execution, guardrails, citations, and **Smriti Memory** live in `core/`. Business-specific SQL views, connectors, KPI formulas, and refusal rules live in `domains/<domain_name>/`.
5. **Governed Memory ("Smriti"), Not Raw Chat Dumping:** Chat questions read organizational memory automatically, but **writing** into company memory requires explicit structure + verification so hallucinations never become "facts."

---

## 3. High-Level System Architecture

```
====================================================================================
 LAYER 1: USER & IDENTITY LAYER (Google Gemini Enterprise — EU Region)
====================================================================================
  [ Business Users: Marketing, Leadership, Future Teams ]
                         |
                         |  SSO Login (Workforce Pool: ge-pilot-wif)
                         |  *Python normalizes principal to .lower() to prevent case bugs*
                         v
  +------------------------------------------------------------------------------+
  | GEMINI ENTERPRISE PORTAL (vertexaisearch.cloud.google.com)                   |
  |  - Agents > Smriti (Thin Wrapper Agent)                                      |
  |  - Built-in Session History, Pinning, Access Control & GCP Cloud Traces      |
  +--------------------------------------+---------------------------------------+
                                         |
                                         | HTTPS / OIDC Authenticated Tool Call
                                         v
====================================================================================
 LAYER 2: SMRITI CORE ENGINE (`core/` — Domain-Agnostic, Hosted on Cloud Run)
====================================================================================
  +------------------------------------------------------------------------------+
  | 1. GATEWAY & SECURITY MIDDLEWARE                                             |
  |    - WIF User Identity Extractor (.lower() canonicalization)                 |
  |    - Request Trace ID + Domain Scope Resolver + Rate Limiter                 |
  +--------------------------------------+---------------------------------------+
                                         |
                                         v
  +------------------------------------------------------------------------------+
  | 2. FAST DETERMINISTIC ROUTER (< 800ms, Gemini Flash @ temp=0 + Rules)        |
  |    Classifies request into:                                                  |
  |    [A] KPI / Time-Grain Comparison (DoD, WoW, MoM, YoY)                      |
  |    [B] Structured Planning / Brief Generation                                |
  |    [C] Competitor / Market Intelligence                                      |
  |    [D] Institutional Memory Recall ("What worked last Diwali?")              |
  |    [E] Memory Capture ("Save this approved brief / learning")                |
  |    [F] Immediate Known-Refusal / Write-Action Block (< 1s polite refusal)    |
  +------------------+---------------------------------------+-------------------+
                     |                                       |
                     v                                       v
  +-------------------------------------+   +------------------------------------+
  | 3. PARALLEL DAG RUNNER + TTL CACHE  |   | 4. "SMRITI" MEMORY ENGINE          |
  |    - Dispatches Domain Collectors   |   |    (100% GCP — Zero Local DBs)     |
  |      in PARALLEL (max 8s timeout)   |   |    - GCS + Vertex AI Search (RAG)  |
  |    - 5–10m TTL Cache + BQ 24h Cache |   |    - BigQuery (`smriti_memory`)    |
  |    - Circuit-breaker per connector  |   |    - L1 Summary / L2 Section /     |
  +------------------+------------------+   |      L3 Atomic Fact hierarchy      |
                     |                      |    - Scoped by Domain + Product    |
                     +----------+-----------+    - Governed Write-Back (HITL)    |
                                |           +------------------------------------+
                                v
  +------------------------------------------------------------------------------+
  | 5. UNIVERSAL GUARDRAIL & CITATION GATE (Pure Python — Zero LLM)              |
  |    - SQL Read-Only AST Validator + Max Bytes Billed Cap                      |
  |    - PII Scrubber (strips phones, emails, addresses before LLM & output)     |
  |    - Ratio & Sum Auditor (blocks AVG-of-ratios, verifies table totals)       |
  |    - Source & Date-Window Citation Stamper (e.g. [BQ: ge_family_monthly])    |
  +--------------------------------------+---------------------------------------+
                                         |
                                         v
====================================================================================
 LAYER 3: PLUGGABLE DOMAIN PACKS (`domains/` — Use-Case Specific Logic)
====================================================================================
  +------------------------------------------+  +--------------------------------+
  | DOMAIN #1: `performance_marketing`       |  | FUTURE DOMAINS (Plug-and-Play) |
  |                                          |  |                                |
  | 1. BigQuery (`Gemini_POC` + Master)      |  | - `senior_living_leads` (CRM)  |
  | 2. Mixpanel Live Connector (Funnel)      |  | - `product_ops_inventory`      |
  | 3. Meta Ads Account (Our Live Metrics)   |  | - `finance_mis`                |
  | 4. Google Ads Account (Our Live Metrics) |  | - `customer_care_insights`     |
  | 5. Meta Ad Library (Rival Creatives)     |  |                                |
  | 6. Google Ad Transparency (Rival Ads)    |  | Each implements `DomainPlugin` |
  | + Excel Rulesets + Web Search + Math     |  | without changing `core/`!      |
  +------------------------------------------+  +--------------------------------+
```

---

## 4. How "Smriti" Institutional Memory Works (Knowledge Retention)

Originally, Smriti was conceived so company knowledge **compounds** instead of getting lost across chats, spreadsheets, and departing employees. In v2, Memory is a **first-class `core/memory/` subsystem** usable by every domain:

```
                   HOW KNOWLEDGE ENTERS & SERVES SMRITI
                   ====================================

  SOURCES OF KNOWLEDGE                        GOVERNED INGESTION PIPELINE
  --------------------                        ---------------------------
  1. Uploaded BRDs / Post-Mortems (PDF/Docx) ─┐
  2. Excel Media Plans & Business Rulesets  ──┼─► Chunker & Fact Extractor
  3. Approved Plans from Chat ("Save Plan") ──┤     ├── L1: Executive Summary
  4. Verified Q&A Insights (Thumbs-up/Pin)  ──┘     ├── L2: Logical Sections
                                                    └── L3: Atomic KPIs & Learnings
                                                               |
                                                               v
                                              +----------------------------------+
                                              | HYBRID KNOWLEDGE STORE (GCP)     |
                                              | - BigQuery (`smriti_memory`)     |
                                              |   for typed metadata, metrics &  |
                                              |   exact L1->L2->L3 tree filters  |
                                              | - Vertex AI Search Datastore     |
                                              |   for native GE semantic search  |
                                              +----------------+-----------------+
                                                               |
                     +-----------------------------------------+
                     | Auto-retrieved during future queries (< 500ms)
                     v
  "Last December's respi campaign hit saturation above Rs 8,000/day in Tier-2;
   video hook SV_CoughAK held 4.48% CTR [Memory: Dec-2025-Respi-BRD, Verified]."
```

### Critical Memory Guardrail (Preventing "Memory Poisoning")
- **Raw unverified LLM chat replies are NEVER auto-saved as facts.**
- Memory entries carry a strict `trust_tier`:
  1. `OFFICIAL_DOC` — Uploaded BRDs, post-mortems, policy sheets (stored in **GCS** and auto-indexed in **Vertex AI Search**).
  2. `APPROVED_DECISION` — A campaign brief or insight explicitly saved/approved by an authorized user (`Save to Smriti Memory` -> **BigQuery `smriti_memory_chunks`**).
  3. `SESSION_EPHEMERAL` — Short-term conversation context managed natively by **Gemini Enterprise** (never shared org-wide).

### Stateless Cloud-Native Storage & Caching (Zero Local SQLite / ChromaDB)
- **No Local Disk State:** Cloud Run containers are ephemeral; local SQLite, ChromaDB, or disk caches are strictly forbidden.
- **Two-Layer Cache (`core/cache.py`):**
  1. **BigQuery Native 24h Cache (`use_query_cache=True`):** Identical warehouse queries return in `< 100ms` at zero byte-scan cost.
  2. **Live Connector TTL Cache (`5–10 min TTL`):** Caches live Mixpanel/Meta/Google API responses in Cloud Run memory during Phase 1, with a 1-line config swap to **Firestore / Cloud Memorystore (Redis)** when multi-instance traffic scales.

---

## 5. Execution Flows & Target Latency

### Flow A: Metrics & Time-Grain Queries (DoD / WoW / MoM / YoY) — **Target: 3 to 6 Seconds**
1. **Router (0.6s):** Detects `KPI_COMPARISON` (`grain=MoM`, `window=3m`, `entity=family`).
2. **Known-Refusal Pre-Check (0.01s Python):** Checks Rule #18 *before* touching any database!
   - *Example:* If user asks for *"Product-level ROAS"* or *"City-level ROAS"*, Python immediately returns a clean explanation + offers *Ad-Family ROAS (`ge_family_monthly`)* + *Catalogue Product Delivered Orders (`ge_product_demand_monthly`)* in **1 second** (instead of looping for 44 minutes!).
3. **Parallel Data Fetch (1.5s):** Runs exact parameterized SQL against `Gemini_POC` views (`ge_account_closed_months`, `ge_family_monthly`, `ge_month_status`).
4. **Python Math Engine (0.01s):** Computes exact `SUM(num)/SUM(den)`, MoM/WoW/DoD/YoY `%` deltas, flags `<5%` as `"flat"`, attaches provisional/settling month caveats (Rule #10).
5. **LLM Formatter (1.5s):** Renders concise executive summary + Markdown table + `"How I got this"` citation block.

---

### Flow B: Campaign Planning & Briefs — **Target: 10 to 18 Seconds**
1. **Router & Intake Extractor (0.8s):** Extracts `(Product, Region, Budget, Target, Season/Festival)`. Applies sensible labeled defaults (`"assumed"`) for missing inputs (Rule #22).
2. **Parallel Collector Fan-Out via `asyncio.gather` (3–6s wall-clock total):**
   - **Task 1 (BigQuery):** Family 3-closed-months + provisional (`ge_family_monthly`), Product demand (`ge_product_demand_monthly`), City demand share (`ge_city_product_demand_monthly`), Last-Year same-month check.
   - **Task 2 (Mixpanel):** Product SKU funnel (`page_variant="products"` -> `mp_begin_checkout` -> `mp_navigation_payment_options`) vs. Sitewide baseline (respecting `24 Feb 2026` & `18 Sep 2026` cutoffs).
   - **Task 3 (Meta + Google Ads):** Active campaigns, top creative CTR/CPC, Meta Opportunity Score, Google Search keyword volume/CPC.
   - **Task 4 (Smriti Memory):** Past BRDs, festive learnings, and uploaded Excel channel rulesets for that product/season.
3. **Deterministic Strategy & Math Engine in Python (0.05s):**
   - Computes exact scale-up multiple (`Budget / Last_Closed_Month_Spend`).
   - Checks target ROAS/CAC feasibility against historical P50/P75 performance (pushes back if unrealistic).
   - Computes Phase 1 / Phase 2 / Phase 3 rupee splits, Meta vs. Google channel splits, 80/20 prospecting/retargeting, and A/B test arms so **every table strictly sums to 100% of Budget** (zero arithmetic calls to BigQuery needed!).
4. **Strategist Narrative + Guardrail Check (4–6s):** Synthesizes the locked JSON numbers into the crisp manager layout with inline `[Source · Period]` citations and <= 3 confirmation questions.

---

## 6. How Multi-Use-Case Extensibility Works (`DomainPlugin` Contract)

To add a second use case later (e.g., **Antara Senior Living Lead Funnel** or **Inventory & Supply Chain**), a developer only creates a new folder under `domains/<new_domain>/` implementing 5 standard hooks:

```python
class DomainPlugin(Protocol):
    domain_id: str                       # e.g., "performance_marketing"
    intents: list[IntentSpec]            # Supported query types
    known_refusals: list[RefusalRule]    # Instant deterministic refusals (Rule #18)

    async def collect(self, plan: CollectionPlan) -> EvidenceBundle: ...
    def compute_metrics(self, bundle: EvidenceBundle) -> VerifiedMetrics: ...
    def validate_output(self, draft: ResponseDraft, metrics: VerifiedMetrics) -> AuditResult: ...
```

`core/` handles Gemini Enterprise auth, parallel execution, timeouts, PII scrubbing, memory storage/retrieval, citations, and OpenTelemetry logs automatically for every domain.

---

## 7. Security, Guardrails & Reliability

| Layer | Control | Implementation |
|---|---|---|
| **Identity & Access** | WIF Case-Insensitive Canonicalization | Extracts `ge-pilot-wif` subject and normalizes `.lower()` so `Himkar.V...` and `himkar.v...` never mismatch. |
| **BigQuery Safety** | Read-Only + Cost Cap | `sqlglot` AST check allows single `SELECT` only on allowlisted `Gemini_POC.*` / `sales_master_data` tables + `maximum_bytes_billed` cap per query. |
| **Ad & Analytics Safety** | Strict Read-Only Credentials | Meta, Google Ads, and Mixpanel service tokens scoped to Read-Only; zero write/mutate endpoints exist in codebase. |
| **PII Protection** | Dual-Layer Redaction | Customer name/phone/email/address columns blocked in SQL allowlist + regex scrubber on all tool outputs (Rule #19). |
| **Graceful Degradation** | Per-Tool Circuit Breakers | If Mixpanel or Meta API is slow (>8s), Python still delivers the BigQuery + Memory plan and notes `"Mixpanel live funnel timed out"` — **never** crashes the whole response. |
| **Team Collaboration** | Git + CI/CD (No Single-Owner Lock) | Multiple engineers edit simultaneously via Git PRs; automated `pytest` eval suite runs before deploying to Cloud Run. |

---

## 8. Proposed Clean Repository Structure (`smriti-v2/`)

```text
smriti-v2/
├── AGENTS.md                        # AI & developer constitution (coding + math invariants)
├── pyproject.toml                   # Python 3.12+, FastAPI, Pydantic v2, google-cloud-bigquery, sqlglot
├── Dockerfile                       # Cloud Run production container
├── docs/
│   ├── ARCHITECTURE.md              # This document
│   ├── DOMAIN_PERF_MARKETING.md     # Exact Gemini_POC schemas, 28 rules, Mixpanel/Meta specs
│   └── ROADMAP.md                   # Vertical-slice build plan
├── core/                            # REUSABLE ACROSS ALL COMPANY USE CASES
│   ├── app.py                       # FastAPI entry point + GE OpenAPI / ADK endpoints
│   ├── auth.py                      # OIDC + WIF principal normalization
│   ├── router.py                    # Fast intent & domain classifier
│   ├── runner.py                    # Parallel asyncio collector with timeouts & circuit breakers
│   ├── memory/                      # "Smriti" Knowledge Retention (L1/L2/L3 chunking + retrieval)
│   ├── guardrails/                  # SQL AST check, PII scrubber, ratio/sum validator, citations
│   └── observability/               # Structured GCP Cloud Logging & OpenTelemetry traces
├── domains/                         # PLUGGABLE BUSINESS DOMAINS
│   ├── base.py                      # DomainPlugin protocol
│   └── performance_marketing/       # USE CASE #1
│       ├── plugin.py                # Registers intents, refusal rules, and workflows
│       ├── rules.py                 # Deterministic implementation of the 28 business rules
│       ├── math_engine.py           # Exact ROAS/CAC, MoM/WoW/DoD/YoY, budget phasing calculator
│       ├── collectors/
│       │   ├── bigquery_poc.py            # 1. Gemini_POC views + sales_master_data
│       │   ├── mixpanel_live.py           # 2. Live sessions & 3-step funnel (M1–M6)
│       │   ├── meta_ads_account.py        # 3. Our live Meta metrics & Opportunity Score
│       │   ├── google_ads_account.py      # 4. Our live Google Search/PMax/YT metrics
│       │   ├── meta_ad_library.py         # 5. Rival active Meta ads (up to 50 sample)
│       │   ├── google_ad_transparency.py  # 6. Rival active Google Search/YT/Display ads
│       │   ├── ruleset_excel.py           # Media plan / policy Excel parser
│       │   └── web_competitor.py          # Sanitized Google Search benchmark collector
│       └── prompts/
│           └── narrator.md          # Thin formatting prompt (receives pre-computed JSON only)
└── tests/
    ├── unit/                        # Math engine, refusal pre-checks, SQL AST, Mixpanel date clipping
    └── evals/                       # Golden QA benchmark (MoM, Nebulizer Rs 3L plan, Known Refusals)
```
