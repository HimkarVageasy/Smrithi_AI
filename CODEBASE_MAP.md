# Smriti v2 — Annotated Codebase Map (`CODEBASE_MAP.md`)

> **Living Repository Map:** Mirrors the exact live file tree of `Smrithi_AI` with a self-explanatory 1–2 line summary per file.
> **Auto-Verified in CI:** `tests/unit/test_codebase_map.py` enforces that every file added, moved, or removed in the repo is updated here before merge.

```text
Smrithi_AI/
├── .github/
│   └── workflows/
│       └── ci.yml                        # GitHub Actions pipeline running Ruff lint + offline pytest on Python 3.12 on every push/PR.
│                                         # Protects main from broken math, schema regressions, or domain leaks across contributors.
├── .env.example                          # Template of stateless runtime environment variables (GCP project, region, auth toggle, default domain).
│                                         # Lets developers configure local dev without ever committing secrets or credentials.
├── .gitignore                            # Git exclusion rules blocking virtualenvs, caches, .env secrets, and forbidden local DB files (.sqlite/.pkl).
├── AGENTS.md                             # Non-negotiable engineering & AI constitution (90% Python / 10% LLM, read-only connectors, SUM/SUM math).
│                                         # Loaded first in every developer and AI agent session to prevent architectural drift.
├── ARCHITECTURE.md                       # Production system architecture detailing Layer 1–3 topology, L1–L3 Smriti Memory, and latency targets.
│                                         # Explains how v2 eliminates v0's monolith bloat and v1's 44-minute sequential tool timeouts.
├── CODEBASE_MAP.md                       # This visual directory guide mapping every live file in the repository to its exact role and business value.
│                                         # Kept 100% in sync automatically via unit tests so new teammates onboard in seconds.
├── DOMAIN_PERF_MARKETING.md              # Authoritative business specification for Domain #1 (AGEasy / Antara Performance Marketing).
│                                         # Defines the 6 connector boundaries, settlement rules, instant Known Refusals, and 6 Golden Evals.
├── Dockerfile                            # Hardened, non-root Python 3.12 container definition for stateless deployment on Google Cloud Run.
├── HIGH_LEVEL_DESIGN.md                  # Executive architecture overview showing how Gemini Enterprise chat connects to the Cloud Run Python brain.
│                                         # Clarifies the exact boundary of every connector and specialist Python module for stakeholders.
├── LOW_LEVEL_DESIGN.md                   # Detailed implementation blueprint: A2A & REST contracts, DomainPlugin protocol, BigQuery DDL, and 3 guardrail gates.
├── README.md                             # Repository landing page with core architectural pillars, spec links, and quick-start local test commands.
├── ROADMAP.md                            # Incremental vertical-slice delivery plan (Slice 0 through Slice 5 + Domain #2 expansion).
│                                         # Ensures each end-to-end capability is unit-tested and verified live before starting the next slice.
├── pyproject.toml                        # Python 3.12+ package manifest, dependencies (FastAPI, Pydantic v2, sqlglot), pytest, and Ruff settings.
├── core/                                 # 100% domain-agnostic platform engine (reusable across Marketing, CRM, Ops, Finance—zero marketing terms).
│   ├── __init__.py                       # Marks core as the shared platform package; kept free of domain imports.
│   ├── a2a.py                            # Agent2Agent (A2A v0.3.0) Agent Card + JSON-RPC message/send adapter for Gemini Enterprise direct Cloud Run routing.
│   │                                     # Eliminates extra Dialogflow/LLM wrapper hops while sharing the exact same verified query pipeline.
│   ├── app.py                            # FastAPI gateway (/health, A2A /, POST /v1/query) bridging Gemini Enterprise calls to DomainPlugins.
│   │                                     # Stamps GCP Cloud Trace IDs, normalizes caller identity, and short-circuits Known Refusals in <1s.
│   ├── auth.py                           # Workforce Identity & Cloud Run IAM OIDC extractor (X-Serverless-Authorization / Bearer) with .strip().lower() normalization.
│   │                                     # Prevents case-mismatch permission/memory bugs and enforces 401 rejection in production mode.
│   ├── cache.py                          # Stateless bounded LRU + 5-min TTL RAM cache for live connector calls (upgradable to Firestore/Redis).
│   ├── config.py                         # Immutable AppConfig model reading runtime flags strictly from environment variables.
│   │                                     # Guarantees stateless Cloud Run execution with zero local config state.
│   ├── guardrails/                       # Deterministic pure-Python pre-query, math, and output safety gates.
│   │   ├── __init__.py                   # Guardrails package marker.
│   │   ├── output_audit.py               # Regex PII scrubber (Indian phones/emails), causal/margin word blocker, and mandatory [Source · Window] check.
│   │   └── sql_ast.py                    # sqlglot AST validator enforcing single-SELECT queries, table allowlists, PII blocks, and 500 MB scan cap.
│   │                                     # Prevents warehouse mutations, unapproved table scans, and accidental PII leaks before BigQuery runs.
│   ├── router.py                         # Domain-agnostic <1ms deterministic time-grain (DoD/WoW/MoM/YoY) and lookback window extractor.
│   ├── runner.py                         # Parallel asyncio.gather task executor with <=8.0s per-connector timeouts and circuit-breaker degradation.
│   └── schemas.py                        # Domain-agnostic Pydantic v2 contracts (SmritiQueryRequest, SmritiQueryResponse, Citation, HealthResponse).
│                                         # Shared canonical data contract across both A2A JSON-RPC messages and REST (/v1/query) calls.
├── domains/                              # Pluggable business use-case packs implementing DomainPlugin without modifying core/.
│   ├── __init__.py                       # Root package for all pluggable company domain modules.
│   ├── base.py                           # Defines the runtime-checkable DomainPlugin protocol and in-memory DomainRegistry.
│   │                                     # Allows future domains (CRM Leads, Inventory, Finance) to plug in cleanly via 4 standard hooks.
│   ├── bootstrap.py                      # Instantiates and registers active domain plugins into DomainRegistry at gateway startup.
│   │                                     # Decouples core/app.py from importing specific business domain packages directly.
│   └── performance_marketing/            # Domain #1: AGEasy / Antara Senior Care Performance Marketing intelligence pack.
│       ├── __init__.py                   # Package marker for the Performance Marketing domain pack.
│       ├── collectors/                   # Strictly read-only external data connectors with timeouts and schema validation.
│       │   ├── __init__.py               # Collectors subpackage marker.
│       │   ├── bigquery_poc.py           # Sole financial/order truth connector querying allowlisted Gemini_POC views via sqlglot + 24h BQ cache.
│       │   │                             # Fetches Account, Closed Months, Ad-Family, Product/City Demand, and non-PII daily orders concurrently.
│       │   ├── google_ads_account.py     # Read-only Google Ads SearchStream connector (dormant while GOOGLE_ADS_ENABLED=false; ready for future activation).
│       │   ├── meta_ads_account.py       # Read-only Meta Graph API connector locked strictly to Ad Account 774668588585301 (live CTR/CPC/CPM & Opportunity Score).
│       │   └── mixpanel_live.py          # Read-only Mixpanel 3-step funnel connector enforcing M1..M6 rules and 2026-02-24 / 2026-09-18 IST cutoffs.
│       ├── demand_presenter.py           # Verified Markdown report builder for Catalogue Product/City Delivered Demand and DoD/WoW order tables.
│       ├── intent_parser.py              # Deterministic marketing query classifier extracting focus, ad-family, and city scope in <1ms.
│       ├── kpi_presenter.py              # Verified Account & Ad-Family report builder computing 100% of SUM/SUM ROAS, CAC, and MoM deltas in Python.
│       │                                 # Flags provisional/settling months and stamps inline [Source: BigQuery ...] citations.
│       ├── live_presenter.py             # Multi-source presenter combining BigQuery financial truth, Mixpanel 3-step funnel, Cross-Source CVR, and live ad pulse.
│       ├── math_engine.py                # Pure-Python calculator for SUM/SUM Net ROAS & CAC, CPM, DoD/WoW/MoM/YoY deltas, part-month clipping, and Rs formatting.
│       │                                 # Ensures LLMs never compute ratios, average rates, or include Brand awareness spend in ROAS/CAC.
│       ├── plugin.py                     # DomainPlugin entry point for Performance Marketing.
│       │                                 # Orchestrates <1s refusal checks, parallel core.runner execution, Python math, and cited output.
│       ├── rules.py                      # Deterministic <1s Known Refusal interceptor (Product/City/Daily/Brand ROAS, mutations) and settlement status classifier.
│       │                                 # Turns impossible queries that previously timed out after 44 minutes into instant helpful explanations.
│       └── schemas.py                    # Strict Pydantic v2 models for marketing intents, campaign intake, and PhasedBudgetPlan.
│                                         # Enforces mathematical invariants at the schema level (e.g., phased rupee rows must sum to 100% of budget).
└── tests/                                # Automated verification suite (offline unit tests run in <5s with zero cloud credentials).
    ├── __init__.py                       # Root test package marker.
    └── unit/                             # Fast, deterministic unit & architectural guardrail tests.
        ├── __init__.py                   # Unit test subpackage marker.
        ├── test_a2a.py                   # Verifies A2A /.well-known/agent.json discovery, JSON-RPC message/send, and X-Serverless-Authorization OIDC auth.
        ├── test_app_slice0.py            # Verifies /health, OpenAPI contract, /v1/query WIF + trace propagation, and <1s refusal short-circuiting.
        │                                 # Also enforces AGENTS.md AST invariants: <300 lines/file, zero marketing words in core/, zero local DB imports.
        ├── test_auth.py                  # Tests WIF principal case/whitespace normalization, GCP IAP prefix stripping, and 401 auth enforcement.
        ├── test_bigquery_slice1.py       # End-to-end offline tests for Golden Scenario #1 (3m MoM), #2 (Product ROAS trap), PII blocks, and output audit.
        ├── test_codebase_map.py          # Parses CODEBASE_MAP.md and verifies every live repository file is documented and nothing stale remains.
        ├── test_known_refusals.py        # Verifies <10ms interception of Product/City/Daily/Brand ROAS & ad mutations without blocking Campaign Plans.
        ├── test_live_ad_connectors.py    # Tests Meta Account 774668588585301 lock, Rule F3, dormant Google Ads, and end-to-end Live Diagnostic degradation.
        ├── test_math_engine.py           # Tests SUM/SUM ratios, Brand exclusion, CPM >= 1.0 rule, <5% flat deltas, reversals, and Indian Rs formatting.
        ├── test_mixpanel_rules.py        # Tests Mixpanel forbidden Purchase events, 2026-02-24 & 2026-09-18 cutoffs, 1-SKU fan-out, and M6 Cross-Source CVR.
        ├── test_runner_and_cache.py      # Tests InMemoryTTLCache LRU/TTL behavior and parallel runner <=8s circuit-breaker timeouts.
        ├── test_schemas.py               # Validates request constraints and PhasedBudgetPlan exact 100% rupee sum enforcement (including A/B carve-outs).
        └── test_sql_guardrails.py        # Tests sqlglot DDL/DML blocking, unallowlisted table rejection, CTE handling, and PII column / SELECT * blocks.
```
