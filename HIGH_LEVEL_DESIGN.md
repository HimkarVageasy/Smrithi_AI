# Smriti v2 — Final High-Level Design (`HIGH_LEVEL_DESIGN.md`)

> **Updated:** Nov 23, 2026 (Synchronized with Production v2 Context Pack)
> **Surface:** Google Gemini Enterprise (`Agents > Smriti`)
> **Engine:** High-Code Python on Google Cloud Run (`eu` multi-region)
> **Scope:** Reusable Enterprise Intelligence + Institutional Memory Platform (Launching with **Use Case #1: Performance Marketing**)

---

## 1. Executive Picture: How Gemini Enterprise + High-Code Work Together

```
+-----------------------------------------------------------------------------------+
|  1. CHAT & ACCESS LAYER — Google Gemini Enterprise (Web Portal)                   |
|                                                                                   |
|   Marketing / Business User  --->  Opens "Agents > Smriti"  --->  Asks Question   |
|   - Single Sign-On (`ge-pilot-wif`)                                               |
|   - Clean Google UI, conversation history, GCP Cloud Traces                       |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          | 1 Single Secure API Call (HTTPS / OIDC)
                                          v
+-----------------------------------------------------------------------------------+
|  2. HIGH-CODE BRAIN — Python Engine on Google Cloud Run (`core/`)                 |
|                                                                                   |
|   [A] Fast Router (<1s)      -> Decides intent (KPI vs Plan vs Rival vs Memory)   |
|                              -> Blocks impossible queries in 1s (Known Refusals)  |
|                                                                                   |
|   [B] Parallel Runner        -> Calls all needed connectors AT THE SAME TIME      |
|       (`asyncio.gather`)        (Finishes in 4–15 seconds instead of 44 minutes)  |
|                                                                                   |
|   [C] Python Math Engine     -> Computes 100% of ROAS, CAC, MoM/WoW/DoD/YoY,      |
|                                 and Rs budget phasing (LLM never guesses math)    |
|                                                                                   |
|   [D] Smriti Memory Engine   -> Recalls past BRDs & verified learnings; saves     |
|                                 approved briefs/learnings for the whole team      |
|                                                                                   |
|   [E] Guardrails & Citations -> Read-only SQL check, PII filter, [Source · Date]  |
+-----------------------------------------+-----------------------------------------+
                                          |
               +--------------------------+--------------------------+
               |                                                     |
               v                                                     v
+-------------------------------------------+   +-----------------------------------+
|  3A. DOMAIN #1: PERFORMANCE MARKETING     |   |  3B. FUTURE COMPANY DOMAINS       |
|      (6 Read-Only Data Connectors)        |   |      (Plug-and-Play Later)        |
|                                           |   |                                   |
|  1. BigQuery (`Gemini_POC` + Master)      |   |  - Senior Living CRM & Leads      |
|  2. Mixpanel Live (Sessions & Funnel)     |   |  - Inventory & Supply Chain       |
|  3. Meta Ads Account (Our Live Ads)       |   |  - Finance / MIS Reporting        |
|  4. Google Ads Account (Our Live Ads)     |   |  - Customer Support Insights      |
|  5. Meta Ad Library (Rival Creatives)     |   |                                   |
|  6. Google Transparency (Rival Ads)       |   |  Reuses 100% of Layer 1 & Layer 2 |
+-------------------------------------------+   +-----------------------------------+
```

---

## 2. Clear Role of Every Connector (No Overlap, Zero Confusion)

| # | Connector | Exact Role in Smriti | Never Used For |
|---|---|---|---|
| **1** | **BigQuery (`Gemini_POC`)** | **Financial & Order Truth:** Historical Spend, Delivered Orders (`DELIVERED`), Net Revenue, RTO %, Net ROAS, Net CAC, City Demand. | Live creative status or website click steps. |
| **2** | **Mixpanel Live** | **Website Funnel Truth:** Paid Sessions -> Product View -> Checkout Start -> Payment Reached. | Orders or Revenue (always BigQuery). |
| **3** | **Meta Ads Account API** | **Our Live Meta Pulse:** Active status, daily budgets, Opportunity Score, real-time CTR/CPC/CPM on *our* running Meta ads. | Net ROAS or Net CAC (ignores RTO returns). |
| **4** | **Google Ads Account API** | **Our Live Google Pulse:** Active Search/PMax/YouTube status, search terms, Impression Share, real-time CTR/CPC/Spend on *our* Google ads. | Net ROAS or Net CAC (ignores RTO returns). |
| **5** | **Meta Ad Library** | **Rival Meta Watch:** Up to 50 active competitor Meta creatives, hooks, copy, and video/static formats. | Performance ranking or spend (public library has none). |
| **6** | **Google Ads Transparency** | **Rival Google Watch:** Active competitor Search headlines, Display banners, and YouTube ad formats. | Performance ranking or CPC (public library has none). |
| **+** | **Smriti Memory (BQ + Vertex Search)** | **Organizational Memory:** Past BRDs, Excel media rulesets, post-mortems, and approved campaign plans saved by the team. | Saving unverified raw chat replies. |

---

## 3. Clear Role of the Internal "Agents" (Specialist Modules in Python)

Instead of slow, chatty LLM loops in the portal UI, our multi-agent workflow runs inside Cloud Run as **deterministic Python specialists**:

1. **Router & Refusal Gate:** Understands the question in `< 1s`. Immediately catches impossible asks (e.g. *"City ROAS"* or *"Product ROAS"*) and offers valid alternatives instead of timing out.
2. **Warehouse & Funnel Collectors (Parallel):** Fetch BigQuery `Gemini_POC` tables and Mixpanel funnel steps simultaneously.
3. **Live Ad & Competitor Collectors (Parallel):** Fetch our live Meta/Google ad health alongside rival creatives from Meta Ad Library and Google Transparency.
4. **Memory Historian ("Smriti"):** Pulls past seasonal BRDs, festive learnings, and Excel channel rulesets; stores newly approved briefs when requested.
5. **Deterministic Strategist & Math Engine:** Pure Python calculates `SUM/SUM` ratios, scale-up multiples, feasibility checks, and phased `Rs` tables that strictly add up to 100% of budget.
6. **Narrator & Citation Gate:** Uses Gemini (`temperature=0`) *only* to turn the verified JSON numbers into crisp manager-ready prose with `[Source · Date Window]` citations.
