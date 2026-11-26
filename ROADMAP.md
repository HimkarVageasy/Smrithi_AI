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

## Slice 2: Live Funnel & Ad Account Connectors (Parallel Execution) — ✅ COMPLETED (Nov 26, 2026)
- Implemented `core/runner.py` (`asyncio.gather` with `<= 8.0s` per-connector timeouts and graceful partial-result circuit breakers), `core/cache.py` (`5-min` stateless LRU/TTL cache), and `core/guardrails/math_audit.py` (Gate #2 cross-table reconciliation & funnel monotonicity auditor with structured Cloud Logging alerts).
- Plugged in `mixpanel_live.py` (`eu.mixpanel.com` project `3992118`, `<= 4` concurrent call semaphore, `Page Viewed` + `24 Feb 2026` & `18 Sep 2026` date rules, forbidden Purchase block, and channel-matched `M6` Cross-Source CVR).
- Plugged in `meta_ads_account.py` (Account `774668588585301`: live campaigns, creative CTR/CPC/CPM, Opportunity Score, `Rule F3`) and dormant-ready `google_ads_account.py` (`GOOGLE_ADS_ENABLED=false` until org turns on Google Ads).
- **Verified Live:** Combined BigQuery (`Oct + Nov` truth) + Mixpanel EU (`159,932 -> 16,994 -> 10,209`, `2.04%` Meta Cross-Source CVR) + graceful Meta degradation in `< 6s`.

---

## Slice 3: Competitor Ad Libraries & Campaign Planning Engine — ✅ BUILT (Pending Live Verify)
- Plugged in `meta_ad_library.py` (`<= 50` rival creative sampler per `Rule F2`) + `google_ad_transparency.py` + `web_competitor.py`.
- Implemented deterministic Campaign Strategist & Phasing allocator in `campaign_planner.py` (exact scale-up multiple, `6.0x` ROAS feasibility pushback, channel & 3-phase ramp, `80/20` funnel split, 14-day A/B test carve-out summing strictly to `100%` of budget).
- Wired `plan_presenter.py` + `prompts/narrator.md` + inline `[Source · Period]` citation & causal-word auditor covering Golden Scenarios #3, #4, #5, and #6.

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
