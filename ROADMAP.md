# Smriti v2 — Incremental Build Roadmap (`ROADMAP.md`)

> **Guiding Rule:** Build one vertical slice at a time. Every slice ends with passing offline unit tests + a live verification check before starting the next slice.

---

## Slice 0: Clean Repo Bootstrap & Core Skeleton — ✅ COMPLETED (Nov 25, 2026)
- Initialized GitHub repo (`HimkarVageasy/Smrithi_AI`) with `pyproject.toml`, `Dockerfile`, `.env.example`, `.gitignore`, GitHub Actions CI, `CODEBASE_MAP.md`, and the synchronized root Specification Pack.
- Built `core/app.py` (`/health`, `POST /v1/query`), `core/a2a.py` (A2A v0.3.0 `/.well-known/agent.json` + JSON-RPC `message/send`), `core/auth.py` (WIF & Cloud Run IAM OIDC `.strip().lower()` identity normalizer), and `DomainPlugin` base interface (`24/24` offline unit tests passing in `< 2.5s`).
- Deployed `smriti-v2-dev` (`https://smriti-v2-dev-988560645054.europe-west1.run.app`) with Continuous Deployment from `main` on **Google Cloud Run** (`europe-west1`) and connected it via **Custom agent via A2A** (`Smriti-v2-Dev`) in **Gemini Enterprise**.
- **Verified Live:** `Ping Smriti v2!` in Gemini Enterprise returned a 1-second verified ping with normalized identity, GCP Cloud Trace ID, and IST citation.

---

## Slice 1: BigQuery Engine + Deterministic Math + Known Refusals — ✅ COMPLETED (Nov 25, 2026)
- Implemented `core/guardrails/sql_ast.py` (`sqlglot` single-SELECT allowlist + `sales_master_data` PII column block + `500 MB` `maximum_bytes_billed`) and `core/guardrails/output_audit.py` (PII scrubber + causal/margin word blocker + citation gate).
- Implemented `domains/performance_marketing/collectors/bigquery_poc.py` against verified `gemini-poc-503210.Gemini_POC` schemas (`ge_account_monthly`, `ge_account_closed_months`, `ge_month_status`, `ge_family_monthly`, `ge_product_demand_monthly`, `ge_city_product_demand_monthly`, `sales_master_data`).
- Implemented `rules.py` (`< 1s` hard blocks for Mutations/Brand ROAS + Answer-First hybrid grain boundaries for Product/City/Daily ROAS) and `math_engine.py` (`DoD`, `WoW`, `MoM`, `YoY`, `SUM/SUM` ratios, reversal-aware headlines, Indian `Rs` formatting).
- **Verified Live:** 3-month MoM Account + Ad-Family query returned verified `SUM/SUM` tables and caught real Sep->Oct reversal in seconds on `Smriti-v2-Dev`, with full offline unit test coverage.

---

## Slice 2: Live Funnel & Ad Account Connectors (Parallel Execution)
- Implement `core/runner.py` (`asyncio.gather` with 8s per-connector timeouts and graceful partial-result circuit breakers).
- Plug in `mixpanel_live.py` (3-step funnel, `24 Feb 2026` & `18 Sep 2026` date rules, cross-source CVR labeling).
- Plug in `meta_ads_account.py` (Account `774668588585301`: live campaigns, creative CTR/CPC/CPM, Opportunity Score) and `google_ads_account.py` (live Search/PMax/YouTube CTR/CPC/Spend/Search Terms).
- **Done When:** Live diagnostic queries combine BigQuery Net ROAS + Mixpanel Funnel + Meta/Google real-time CTR/CPC in **`< 8 seconds`** with full offline mock tests.

---

## Slice 3: Competitor Ad Libraries & Campaign Planning Engine
- Plug in `meta_ad_library.py` (50-ad rival creative sampler) + `google_ad_transparency.py` (rival Google Search/YouTube creative sampler) + `web_competitor.py`.
- Implement deterministic Campaign Budget & Phasing allocator in `math_engine.py` (scale-up multiple check, feasibility pushback, Meta/Google split, 3-phase ramp, 80/20 funnel split, 14-day A/B test math summing strictly to 100% of budget).
- Wire `prompts/narrator.md` + inline `[Source · Period]` citation auditor.
- **Done When:** The `"Plan a winter campaign for Nebulizer with Rs 3,00,000"` query (and `"Need to run..."` variant) finishes in **`12–18 seconds`** instead of 15 minutes, with Meta + Google splits and verified citations.

---

## Slice 4: "Smriti" Institutional Memory (Knowledge Retention)
- Build `core/memory/` backed by **BigQuery (`smriti_memory_chunks`) + Vertex AI Search Datastore** (zero extra database servers to maintain).
- Support governed ingestion of:
  1. Past BRDs / Post-Mortem docs (`OFFICIAL_DOC`)
  2. Excel Media Rulesets / Channel Policies (`ruleset_excel.py`)
  3. Explicit `"Save Approved Plan / Learning"` action from authorized users (`APPROVED_DECISION`) using the L1 Summary -> L2 Section -> L3 Atomic Fact hierarchy.
- Wire automatic `< 500ms` memory retrieval into Campaign Planning and Memory Recall intents.
- **Done When:** Uploading/saving a past campaign post-mortem immediately enriches the next Campaign Brief with cited historical learnings (`[Memory: <Doc>, Verified]`).

---

## Slice 5: Golden Eval Gate, Observability & Org Cutover
- Complete automated `tests/evals/` suite (all 6 Golden Scenarios + adversarial prompt/SQL injection checks) wired into GitHub Actions CI.
- Verify GCP Cloud Trace dashboards (`Apps > pilot > Agents > Traces`) for latency & cost per query.
- Switch the main `Smriti` agent in Gemini Enterprise (`pilot` / production app) to the Cloud Run backend and open access to the marketing team.

---

## Future Horizon: Plugging In Domain #2
- Copy `domains/_template/` -> `domains/<second_use_case>/` (e.g., Antara Senior Living Lead & CRM Intelligence).
- Reuse 100% of `core/` (GE Gateway, Auth, Parallel Runner, Smriti Memory, Guardrails, Citations) with zero changes to `performance_marketing`.
