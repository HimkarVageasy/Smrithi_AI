# Smriti v2 — Final Low-Level Design (`LOW_LEVEL_DESIGN.md`)

> **Updated:** Nov 25, 2026 (Synchronized with Live Slice 0 Cloud Run + A2A Deployment)
> **Runtime:** Python 3.12+, FastAPI, Pydantic v2, `google-cloud-bigquery`, `httpx` (`asyncio`), `sqlglot`, Google GenAI SDK (`google-genai`)
> **Deployment:** Google Cloud Run (`europe-west1` / `eu`), connected directly via **Agent2Agent (A2A v0.3.0)** protocol (`core/a2a.py`) + REST (`POST /v1/query`) to Gemini Enterprise (`Apps > pilot > Agents`)

---

## 1. Gemini Enterprise <-> Cloud Run API Contract (`core/app.py` & `core/a2a.py`)

Gemini Enterprise invokes Smriti v2 directly over HTTPS using Google's native **Custom agent via A2A** bridge (`GET /.well-known/agent.json` discovery + `POST /` JSON-RPC 2.0 `message/send`), authenticated at the Cloud Run IAM perimeter via `X-Serverless-Authorization` OIDC (`roles/run.invoker` granted to the Discovery Engine service agent). For automated golden evaluations and direct HTTP testing, `POST /v1/query` exposes the exact same pipeline over typed REST.

### Request & Response Schemas (`core/schemas.py`)
```python
from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class SmritiQueryRequest(BaseModel):
    question: str = Field(..., min_length=2, description="Natural language user request from Gemini Enterprise chat")
    domain_hint: Optional[str] = Field(default="performance_marketing")
    session_id: Optional[str] = None


class Citation(BaseModel):
    source: Literal[
        "BigQuery",
        "Mixpanel",
        "Meta Ads Account",
        "Google Ads Account",
        "Meta Ad Library",
        "Google Ads Transparency",
        "Smriti Memory",
        "Excel Ruleset",
        "Google Search",
    ]
    object_name: str          # e.g. "Gemini_POC.ge_family_monthly" or "Account 774668588585301"
    date_window_ist: str      # e.g. "1 Aug 2026 – 31 Oct 2026 IST"
    row_count: Optional[int] = None
    note: Optional[str] = None


class SmritiQueryResponse(BaseModel):
    headline: str             # Rule 14 / 25: e.g. "Net ROAS · October 2026 · Meta account"
    answer_markdown: str      # Verified prose + Markdown tables with inline [Source · Window] tags
    citations: list[Citation]
    degraded_sources: list[str] = Field(default_factory=list)  # Populated if a non-critical API timed out
    latency_ms: int
    trace_id: str
```

### Workforce Identity Normalization (`core/auth.py`)
```python
def canonicalize_wif_principal(raw_principal: str) -> str:
    """Prevents case-mismatch bugs across ge-pilot-wif principals."""
    return raw_principal.strip().lower()
```

---

## 2. Pluggable Multi-Domain Interface (`domains/base.py`)

Every business use case implements `DomainPlugin` so `core/` stays 100% reusable:

```python
from typing import Protocol


class DomainPlugin(Protocol):
    domain_id: str

    def check_known_refusal(self, parsed_intent: dict) -> str | None:
        """Returns immediate <1s polite refusal + valid alternative if query hits a Known Refusal."""
        ...

    async def collect_parallel(self, parsed_intent: dict) -> dict:
        """Dispatches domain connectors concurrently via core.runner.run_with_timeouts()."""
        ...

    def compute_verified_metrics(self, parsed_intent: dict, raw_bundle: dict) -> dict:
        """Pure Python arithmetic: ratios, MoM/WoW/DoD/YoY deltas, phased budgets."""
        ...

    async def render_response(self, verified_payload: dict) -> SmritiQueryResponse:
        """Passes locked JSON numbers to narrator prompt + runs output guardrail audit."""
        ...
```

---

## 3. Domain #1 Schemas (`domains/performance_marketing/schemas.py`)

```python
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


IntentType = Literal[
    "KPI_SINGLE_OR_TREND",     # DoD, WoW, MoM, YoY, or single closed month
    "CAMPAIGN_PLAN",           # Full brief ("plan", "need to run", "launch", "design")
    "LIVE_AD_DIAGNOSTIC",      # Current running Meta/Google ad CTR, CPC, Opportunity Score
    "COMPETITOR_INTEL",        # Rival ads across Meta Ad Library + Google Transparency
    "MEMORY_RECALL",           # Past BRDs, festive post-mortems, historical learnings
    "MEMORY_SAVE",             # Explicit user approval to save a brief/learning
    "WRITE_ACTION_REFUSAL",    # Pause/edit/create live ads -> refuse cleanly
]


class CampaignPlanIntake(BaseModel):
    product_query: str                         # Matched to ge_family_monthly + ge_product_demand_monthly
    region: str = "All India"
    region_assumed: bool = True
    budget_inr: int = Field(..., gt=0)
    target_roas: Optional[float] = None
    target_cac_inr: Optional[float] = None
    target_assumed: bool = True
    window_label: str                          # e.g. "December 2026"
    external_premise: Optional[str] = None     # e.g. "Winter air quality" -> tagged "your premise, not our data"


class BudgetPhaseRow(BaseModel):
    phase_name: str
    channel: Literal["Meta Ads", "Google Ads", "Blended"]
    funnel_stage: Literal["Prospecting (80%)", "Retargeting (20%)", "A/B Test Arm"]
    amount_inr: int
    daily_run_rate_inr: int
    date_range: str
    scale_condition: str


class PhasedBudgetPlan(BaseModel):
    total_budget_inr: int
    scale_multiple_vs_last_closed: Optional[float]
    rows: list[BudgetPhaseRow]

    @model_validator(mode="after")
    def verify_exact_budget_sum(self) -> "PhasedBudgetPlan":
        allocated = sum(r.amount_inr for r in self.rows if r.funnel_stage != "A/B Test Arm")
        if allocated != self.total_budget_inr:
            raise ValueError(f"Allocated Rs {allocated} != Total Budget Rs {self.total_budget_inr}")
        return self
```

---

## 4. The 6 Connector Interfaces (`domains/performance_marketing/collectors/`)

All 6 connectors are **strictly Read-Only**, async-compatible, capped at an `8.0s` timeout via `core/runner.py`, and mocked in `tests/unit/` for offline testing.

```python
# 1. BigQuery Warehouse (`bigquery_poc.py`) — ONLY via validated read_query()
class BigQueryPocCollector:
    ALLOWLISTED_VIEWS = frozenset({
        "Gemini_POC.ge_account_monthly",
        "Gemini_POC.ge_account_closed_months",
        "Gemini_POC.ge_month_status",
        "Gemini_POC.ge_family_monthly",
        "Gemini_POC.ge_product_demand_monthly",
        "Gemini_POC.ge_city_demand_monthly",
        "Gemini_POC.ge_city_product_demand_monthly",
        "Gemini_POC.vw_meta_channel_monthly",
        "Gemini_POC.vw_meta_campaign_monthly",
        "Gemini_POC.sales_master_data",
    })
    async def fetch_family_history(self, family: str, months: int = 4) -> list[dict]: ...
    async def fetch_product_and_city_demand(self, product: str, city: str | None) -> dict: ...
    async def fetch_time_grain_comparison(self, grain: str, entity: str, window: int) -> dict: ...

# 2. Mixpanel Live (`mixpanel_live.py`) — Enforces M1..M6 & 24 Feb / 18 Sep 2026 cutoffs
class MixpanelLiveCollector:
    MIN_START_DATE = date(2026, 2, 24)
    CHECKOUT_CUTOFF_DATE = date(2026, 9, 18)
    FORBIDDEN_EVENTS = frozenset({"Purchase", "Order Placed", "product_purchase", "mp_order_complete"})
    async def fetch_3step_funnel(self, combo_skus: list[str], start: date, end: date) -> dict: ...

# 3. Meta Ads Account (`meta_ads_account.py`) — Locked to Ad Account 774668588585301
class MetaAdsAccountCollector:
    ALLOWED_ACCOUNT_ID = "774668588585301"
    async def fetch_live_ads_and_opportunity_score(self, family_keyword: str | None) -> dict: ...

# 4. Google Ads Account (`google_ads_account.py`) — Read-Only SearchStream
class GoogleAdsAccountCollector:
    async def fetch_live_campaigns_and_search_terms(self, product_keyword: str | None) -> dict: ...

# 5. Meta Ad Library (`meta_ad_library.py`) — Public rival creatives (<= 50 sample, zero rank claims)
class MetaAdLibraryCollector:
    MAX_SAMPLE = 50
    async def search_active_rival_ads(self, query_terms: list[str], country: str = "IN") -> dict: ...

# 6. Google Ads Transparency (`google_ad_transparency.py`) — Public rival Search/YT/Display creatives
class GoogleAdTransparencyCollector:
    async def search_active_rival_creatives(self, advertiser_or_keyword: str, region: str = "IN") -> dict: ...
```

---

## 5. Cloud-Native Memory, Vector Store & Caching (`core/memory/` & `core/cache.py`)

**Zero Local Disk State:** Local SQLite, ChromaDB, and local disk caches are strictly forbidden.
1. **Short-Term Session Memory:** Handled natively by Gemini Enterprise (`session_id`).
2. **Raw Docs & Vector RAG:** Uploaded BRDs/PDFs/Excels land in **GCS (`gs://<project>-smriti-docs/`)** and auto-sync into **Vertex AI Search** (`Connected data stores`).
3. **Structured Organizational Memory:** Stored in BigQuery (`Gemini_POC.smriti_memory_chunks`) with native `VECTOR_SEARCH` support:

```sql
CREATE TABLE IF NOT EXISTS `Gemini_POC.smriti_memory_chunks` (
  chunk_uuid        STRING NOT NULL,
  parent_chunk_uuid STRING,                -- NULL for L1 Summary; L1 UUID for L2; L2 UUID for L3
  root_chunk_uuid   STRING NOT NULL,
  level             INT64 NOT NULL,        -- 1 = Summary, 2 = Section, 3 = Atomic Fact
  domain_id         STRING NOT NULL,       -- e.g. 'performance_marketing'
  trust_tier        STRING NOT NULL,       -- 'OFFICIAL_DOC' | 'APPROVED_DECISION'
  entity_tags       ARRAY<STRING>,         -- e.g. ['nebulizer', 'AENB200103', 'winter', 'delhi']
  section_type      STRING,                -- 'Objective' | 'Budget' | 'Experiment' | 'Learning' | 'Risk'
  content_text      STRING NOT NULL,
  metrics_json      JSON,                  -- Typed KPIs {roas, cac_inr, spend_inr}
  source_title      STRING NOT NULL,       -- e.g. 'Dec-2025-Respi-PostMortem.pdf'
  created_by_wif    STRING NOT NULL,       -- Normalized lowercase principal
  approved_by_wif   STRING NOT NULL,
  created_at        TIMESTAMP NOT NULL
);
```

### Stateless Caching Interface (`core/cache.py`)
- **Warehouse Queries:** `QueryJobConfig(use_query_cache=True)` leverages BigQuery's free 24-hour cache automatically.
- **Live API Calls (Mixpanel / Meta / Google Ads):** Wrapped in `CacheBackend` (`300s` default TTL in Cloud Run memory for Phase 1; config-switchable to Firestore / Cloud Memorystore Redis at scale).

---

## 6. Guardrail Pipeline (`core/guardrails/`)

Every request passes **3 deterministic Python gates**:

1. **Pre-Query Gate (`sql_ast.py`):**
   - Parses SQL via `sqlglot.parse_one(sql, read="bigquery")`.
   - Rejects anything other than a single `exp.Select` (blocks `INSERT`, `UPDATE`, `DELETE`, `DROP`, `MERGE`, `CALL`).
   - Verifies every table is in `ALLOWLISTED_VIEWS` and blocks PII columns (`customer_name`, `phone`, `mobile`, `email`, `shipping_address`).
   - Attaches `QueryJobConfig(maximum_bytes_billed=500_000_000)` (`500 MB` safety cap).
2. **Math Integrity Gate (`math_audit.py`):**
   - Computes `ROAS = sum_delivered_revenue / sum_perf_spend` (raises error if `brand_spend` is included).
   - Asserts `cpm >= 1.0` whenever `spend > 0 and impressions > 0` (Rule #9).
   - Verifies phased campaign tables sum to `total_budget_inr`.
3. **Output & PII Gate (`output_audit.py`):**
   - Regex-strips Indian phone numbers (`+91...` / 10-digit mobile) and email addresses.
   - Blocks banned causal words (`"caused"`, `"drove"`, `"profitable"`) per Rule #17.
   - Verifies every table carries a `[Source: ... · ...]` citation line.

---

## 7. Unit Testing & Golden Eval Blueprint (`tests/`)

All unit tests run offline in `< 5 seconds` via `pytest`:
- `tests/unit/test_sql_guardrails.py` — Tests DDL/DML rejection, PII column rejection, un-allowlisted table rejection.
- `tests/unit/test_math_engine.py` — Tests `SUM/SUM` ROAS, Brand spend exclusion, `<5%` `"flat"` rule, part-month day clipping, Rs Indian number formatting, and exact budget phasing sums.
- `tests/unit/test_mixpanel_rules.py` — Tests `2026-02-24` start clipping, `2026-09-18` checkout step cutoff, and forbidden Purchase event rejection.
- `tests/unit/test_known_refusals.py` — Verifies `<10ms` interception of Product ROAS, City ROAS, Daily Net ROAS, and Ad-Mutation prompts.
- `tests/evals/test_golden_queries.py` — Runs the 6 Golden Scenarios end-to-end and asserts `< 6s` KPI latency and `< 18s` Campaign Plan latency.
