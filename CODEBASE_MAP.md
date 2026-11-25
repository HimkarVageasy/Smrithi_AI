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
├── LOW_LEVEL_DESIGN.md                   # Detailed implementation blueprint: OpenAPI schemas, DomainPlugin contract, BigQuery DDL, and 3 guardrail gates.
├── README.md                             # Repository landing page with core architectural pillars, spec links, and quick-start local test commands.
├── ROADMAP.md                            # Incremental vertical-slice delivery plan (Slice 0 through Slice 5 + Domain #2 expansion).
│                                         # Ensures each end-to-end capability is unit-tested and verified live before starting the next slice.
├── openapi_gemini_enterprise.yaml        # Strict OpenAPI 3.0.3 tool specification ready to paste into Gemini Enterprise (Agents > Smriti-v2-Dev).
│                                         # Avoids FastAPI OpenAPI 3.1.0 incompatibilities with Google's OpenAPI tool validator.
├── pyproject.toml                        # Python 3.12+ package manifest, dependencies (FastAPI, Pydantic v2, sqlglot), pytest, and Ruff settings.
├── core/                                 # 100% domain-agnostic platform engine (reusable across Marketing, CRM, Ops, Finance—zero marketing terms).
│   ├── __init__.py                       # Marks core as the shared platform package; kept free of domain imports.
│   ├── app.py                            # FastAPI gateway (/health, POST /v1/query) bridging Gemini Enterprise OpenAPI calls to DomainPlugins.
│   │                                     # Stamps GCP Cloud Trace IDs, normalizes caller identity, and short-circuits Known Refusals in <1s.
│   ├── auth.py                           # Workforce Identity Federation (ge-pilot-wif) extractor and .strip().lower() principal normalizer.
│   │                                     # Prevents case-mismatch permission/memory bugs and enforces 401 rejection in production mode.
│   ├── config.py                         # Immutable AppConfig model reading runtime flags strictly from environment variables.
│   │                                     # Guarantees stateless Cloud Run execution with zero local config state.
│   └── schemas.py                        # Domain-agnostic Pydantic v2 contracts (SmritiQueryRequest, SmritiQueryResponse, Citation, HealthResponse).
│                                         # Generates the exact OpenAPI 3.0 schema imported by Google Gemini Enterprise (Agents > Smriti).
├── domains/                              # Pluggable business use-case packs implementing DomainPlugin without modifying core/.
│   ├── __init__.py                       # Root package for all pluggable company domain modules.
│   ├── base.py                           # Defines the runtime-checkable DomainPlugin protocol and in-memory DomainRegistry.
│   │                                     # Allows future domains (CRM Leads, Inventory, Finance) to plug in cleanly via 4 standard hooks.
│   ├── bootstrap.py                      # Instantiates and registers active domain plugins into DomainRegistry at gateway startup.
│   │                                     # Decouples core/app.py from importing specific business domain packages directly.
│   └── performance_marketing/            # Domain #1: AGEasy / Antara Senior Care Performance Marketing intelligence pack.
│       ├── __init__.py                   # Package marker for the Performance Marketing domain pack.
│       ├── plugin.py                     # DomainPlugin entry point for Performance Marketing (currently serving Slice 0 verified gateway ping).
│       │                                 # Orchestrates refusal checks, parallel collection, Python math, and cited response rendering.
│       └── schemas.py                    # Strict Pydantic v2 models for marketing intents, campaign intake, and PhasedBudgetPlan.
│                                         # Enforces mathematical invariants at the schema level (e.g., phased rupee rows must sum to 100% of budget).
└── tests/                                # Automated verification suite (offline unit tests run in <5s with zero cloud credentials).
    ├── __init__.py                       # Root test package marker.
    └── unit/                             # Fast, deterministic unit & architectural guardrail tests.
        ├── __init__.py                   # Unit test subpackage marker.
        ├── test_app_slice0.py            # Verifies /health, OpenAPI contract, /v1/query WIF + trace propagation, and <1s refusal short-circuiting.
        │                                 # Also enforces AGENTS.md AST invariants: <300 lines/file, zero marketing words in core/, zero local DB imports.
        ├── test_auth.py                  # Tests WIF principal case/whitespace normalization, GCP IAP prefix stripping, and 401 auth enforcement.
        ├── test_codebase_map.py          # Parses CODEBASE_MAP.md and verifies every live repository file is documented and nothing stale remains.
        └── test_schemas.py               # Validates request constraints and PhasedBudgetPlan exact 100% rupee sum enforcement (including A/B carve-outs).
```
