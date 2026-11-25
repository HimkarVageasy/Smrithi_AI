# Domain Pack #1 Specification — Performance Marketing (`DOMAIN_PERF_MARKETING.md`)

> Authoritative domain reference for AGEasy (Antara Senior Care) Performance Marketing. Implements all battle-tested rules from `Gemini_POC` plus multi-channel (Meta + Google) and Smriti Memory extensions.

---

## 1. Business Inputs & Outputs Contract

### Inputs (`PlanningIntake`)
| Parameter | Description | If Missing in Prompt |
|---|---|---|
| `product` | Ad-side family (e.g. `nebulizer`) or Catalogue SKU/Product (`Product_`) | Required (ask if totally absent) |
| `region` | `All India` or specific city/tier (e.g. `DELHI`, Tier-1 North) | Default `"All India (assumed)"` |
| `budget_inr` | Total planned spend in INR (e.g. `300000`) | Required for planning |
| `target_kpi` | Target Net Delivered ROAS or Max Net CAC | Default historical closed-month P50 (`"assumed"`) |
| `season_window` | Target month / season (e.g. `December 2026`, `Winter`) | Default next calendar month (`"assumed"`) |
| `festival_reason` | Event window or external premise (e.g. `Diwali`, `Winter Air Quality`) | Optional; tag external premises `"your premise, not our data"` |

### Core Outputs
1. **Time-Grain Comparisons:** `DoD` (Day-on-Day), `WoW` (Week-on-Week), `MoM` (Month-on-Month), `YoY` (Year-on-Year).
2. **Structured Campaign Brief & Phased Plan:** Verdict, Historical Table, Funnel vs. Sitewide, Channel & Phased Budget Table (summing to 100%), Live Ad Insights, Competitor Creative Snapshot, 14-day A/B Test, Assumptions (<=3 questions), and Risks.
3. **Competitor & Creative Intelligence:** Active rival ad themes/formats across Meta Ad Library + Google Ads Transparency + Open Web.
4. **Core KPI & Funnel Analytics:** Net ROAS, Net CAC, RTO %, Spend (Perf vs. Brand), CPM, CTR, CPC, CVR, and Cross-Source Funnel progression.

---

## 2. The 6 Data Connectors + Memory Sources

### Connector 1: BigQuery (`Gemini_POC` Dataset — Financial & Order Truth)
**Priority Rule:** Always query curated `Gemini_POC` views first. Fall back to `vw_meta_channel_monthly`, `vw_meta_campaign_monthly`, or `sales_master_data` ONLY when a curated view lacks the required grain.

| View / Table | Grain & Purpose | Key Columns & Rules |
|---|---|---|
| `ge_account_monthly` | Account x Month (`performance_spend`, `brand_spend`, `net_revenue`, `net_orders`, `performance_impressions`, `performance_clicks`, `settle_state`, `is_provisional`) | Includes current provisional month; recompute blended totals via `SUM/SUM`. |
| `ge_account_closed_months` | Account x Closed Months only | **Mandatory** for direction/trend questions (`>= 3` closed months). |
| `ge_month_status` | Month settlement status (`month`, `settle_state`, `is_provisional`, `is_latest_closed`) | Identifies `provisional`, `settling` (before 20th of next month), or `mostly settled` (after 20th). |
| `ge_family_monthly` | Ad-side `product_family` x Month (e.g. `nebulizer`, `allproducts`) | Has `spend`, `net_revenue`, `net_orders`, `campaigns` at **ad-family** grain. |
| `ge_product_demand_monthly` | Catalogue `catalogue_product` x Month | Delivered demand/orders (`net_orders`, `gross_orders`, `net_revenue`) by catalogue product (no ad-level spend). |
| `ge_city_demand_monthly` | `city` x Month | Total city demand across catalogue (`net_orders`, `gross_orders`, `net_revenue`). |
| `ge_city_product_demand_monthly` | `city` x `catalogue_product` x Month | City share of a specific product (`DELHI` = Delhi rows). **Never sum across products.** |
| `sales_master_data` | Order line-item grain (`sale_order_code`, `Order_Date`, `Status_`, `Product_`, `Combo_SKU`, `selling_price`) | `Status_ = 'DELIVERED'` is net revenue/orders. `Combo_SKU` joins to Mixpanel `sku`. Blocks PII (`Customer_Name`, `Phone_`, `notification_email`, `address_line_1/2`, `pincode`, `employee_details`). |

*(Note: As Google Ads warehouse views `ge_google_account_monthly` / `ge_blended_monthly` land in `Gemini_POC`, register them in `bigquery_poc.py` table registry.)*

---

### Connector 2: Mixpanel Live Connector (Website Behavior & Funnel Truth)
- **Read-Only Scope:** Sessions and funnel progression ONLY. **Forbidden events:** `Purchase`, `Order Placed`, `product_purchase`, `mp_order_complete`, `Revenue` (orders come strictly from BigQuery).
- **Paid Channel Session Filter (`M1`):**
  - Meta sessions: `utm_source = "paid"` AND `utm_medium = "meta"` (case-insensitive). Count **sessions**, not raw events.
  - Google sessions: `utm_source = "paid"` (or `"google"`) AND `utm_medium` in `("cpc", "ppc", "google")` per live UTM convention.
- **Exact 3-Step Funnel (`M2`):**
  1. Product Page View (`page_variant = "products"`)
  2. Checkout Start (`mp_begin_checkout`)
  3. Payment Options Reached (`mp_navigation_payment_options`)
  *(Note: There is NO unified cart step—Add to Cart and Buy Now are separate paths.)*
- **SKU & Campaign Join (`M3`):** Storefront `sku` == `Combo_SKU` in `sales_master_data`. Campaign/ad names match `utm_campaign` and `utm_content`.
- **Query Constraints (`M4`):** Max 1 value per filter and max 2 breakdowns per API call; fan out in parallel Python calls and sum counts in Python if multi-SKU.
- **Hard Date Boundaries (`M5`):**
  - Timezone `IST`, complete weeks or longer ending **yesterday**.
  - **Clip start date to `>= 2026-02-24`** (and state when clipped).
  - **Checkout instrumentation cutoff `2026-09-18`:** If a range spans `2026-09-18`, compute checkout steps ONLY for dates after `2026-09-18` and note it.
  - If sessions == 0, state `"No sessions recorded in period"`—never print `0%`.
- **Cross-Source CVR (`M6`):** Always label `BigQuery Delivered Orders / Mixpanel Sessions` as `"Cross-source conversion"` alongside raw session & order counts.

---

### Connector 3: Meta Ads Account Connector (Our Live Meta Ads)
- **Scope:** Ad Account **`774668588585301`** ONLY (ignore all other ad accounts; strictly Read-Only).
- **Used For:** Live campaign/adset/ad status, daily budgets, active creative names/formats (e.g. `SV_CoughAK`, `SI_NewPrice1299`), real-time CTR/CPC/CPM on active ads, and Meta Opportunity Score recommendations.
- **Regional Spend Caveat (`F3`):** Query 1 month per call for regional spend; if regional sum != account monthly total, discard regional breakdown and report mismatch. Deleted campaigns are invisible to live campaign reads—never present live campaign sums as historical account spend.

---

### Connector 4: Google Ads Account Connector (Our Live Google Ads)
- **Scope:** Official AGEasy Google Ads customer ID(s), strictly Read-Only (`GoogleAdsService.SearchStream`).
- **Used For:** Live Search, Performance Max, and YouTube campaign status, daily budgets, top converting/high-intent search queries, Impression Share lost to budget/rank, and real-time CTR, CPC, and Spend.
- **Boundary:** Like Meta, never use Google Ads conversion value as Net Revenue or Net ROAS—always reconcile net revenue via BigQuery `DELIVERED` orders.

---

### Connector 5: Meta Ad Library Connector (Competitor Live Meta Ads)
- **Used For:** Rival brand active creatives, ad copy hooks, offers, and format mix (9:16 Reels vs. Static vs. Carousel).
- **Hard Caveat (`F2`):** Returns at most **50 ads per query** with **zero** spend, impressions, or conversion metrics. Always state `"from a sample of up to 50 active ads"` and **never** claim one rival ad outperformed another.

---

### Connector 6: Google Ads Transparency Connector (Competitor Live Google Ads)
- **Used For:** Rival brand active Search text headlines, Shopping/PMax tiles, and YouTube video ad formats in India.
- **Hard Caveat:** Public transparency data contains **zero** CPC, spend, or conversion metrics. Report active messaging themes, offers, and formats only; **never** rank rival ads by performance.

---

## 3. Deterministic Business & Refusal Rules (`rules.py`)

### Deterministic Refusals & Answer-First Grain Boundaries (`rules.py`)
1. **Answer-First Grain Boundaries (Return Valid Tables + Scope Note in `< 3s`, Never Loop!):**
   When a query mixes answerable warehouse metrics with an uncomputable sub-grain, Smriti **answers 100% of the valid tables first** via parallel `asyncio.gather` and appends a clear `Scope Boundary — What Could Not Be Computed & Why` note:
   - **Product / SKU-Level ROAS or CAC** *(Ad spend is loaded at ad-family grain in `ge_family_monthly`, not SKU/catalogue-product grain; `allproducts` and `catalogue` campaigns span multiple SKUs).* -> Returns **Account MoM (`Total Spend`, `Placed Orders`, `Delivered Orders`, `Net ROAS`)** + **Ad-Family Spend & Net ROAS** + **Catalogue Product Placed & Delivered Orders**, followed by the Product-ROAS boundary explanation.
   - **City-Level or State-Level ROAS / CAC** *(No city-level delivered ad spend attribution exists).* -> Returns **City Placed & Delivered Demand (`ge_city_product_demand_monthly`)** + **National Ad-Family Net ROAS**, followed by the City-ROAS boundary explanation.
   - **Daily Net ROAS or Daily Net CAC** *(Delivery + RTO settlement takes days/weeks, making daily net ROAS misleading).* -> Returns **Daily (`DoD`) Placed & Delivered Orders** + **Monthly Account Net ROAS & Settlement Status**, followed by the Daily-ROAS boundary explanation.
2. **Instant `< 1s` Hard Refusals (Zero Warehouse Queries):**
   - **Brand Campaign ROAS or CAC** *(Brand spend is awareness-only; excluded from ROAS/CAC).*
   - **Creative-Level Historical Warehouse CPM** *(Query live Meta/Google Ads Account connector for active creative delivery metrics instead).*
   - **Any Write / Mutate Request** (*"Pause this ad"*, *"Increase daily budget"*) -> Route *"need to run / launch a campaign"* to **Read-Only Campaign Planning**; refuse live ad-account mutations cleanly.

### Period & Settlement Rules
- **Provisional Month:** Current calendar month is ALWAYS flagged `provisional` (RTOs still in transit -> inflated early ROAS).
- **Settling Month:** Previous month before the 20th of the current month -> flag `settling`; after the 20th -> `mostly settled; ratios can still move`.
- **Part-Month Rule:** Compare day `1..N` of current month ONLY against day `1..N` of prior month(s), never against a full 30/31-day month.
- **Direction Rule:** `< 5%` change is labeled `"flat"`. Reversals in the latest closed month must state both the multi-month trend and the latest-month reversal in sentence 1 (`< 25 words`).
- **Causal Language Ban:** Report observed metrics only; never write *"Creative X caused/drove orders"* and never call an ad `"profitable"` from ROAS alone (margin is not in warehouse).

---

## 4. Golden Evaluation Suite (`tests/evals/`)

Every deployment must pass these 6 golden scenarios automatically:
1. **3-Month MoM Account & Family Trend:** Completes in `< 6s`, flags November as `provisional` and October status from `ge_month_status`, computes `SUM/SUM` ROAS.
2. **Product-ROAS Trap (`"Delivered ROAS by product"`):** Intercepts in `< 2s` (zero timeout!), explains Family vs. Catalogue Product boundary, and returns Family ROAS + Product Delivered Orders cleanly.
3. **Winter Nebulizer Rs 3,00,000 Plan:** Runs BQ + Mixpanel + Meta + Google + Memory in parallel (`< 18s`), computes exact scale-up multiple (`4.76x`), outputs non-overlapping Phased + Channel budget table summing strictly to `Rs 3,00,000`, includes inline `[Source · Period]` citations.
4. **Unrealistic 6.0x ROAS Feasibility Pushback:** Rejects blind scaling using closed-month historical ROAS baseline.
5. **Intent Ambiguity (`"Need to run a winter campaign..."`):** Routes cleanly to Campaign Planning instead of crashing on write-tool refusal.
6. **Rival Ad Library Audit:** Summarizes rival hooks/formats across Meta Ad Library + Google Transparency without fabricating performance rankings.
