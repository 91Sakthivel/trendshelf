# TrendShelf -- CPG Retail Intelligence Platform

> **Consumer Packaged Goods demand-gap analytics pipeline for Kroger DFW stores.**
> Built on real API data, dbt transformations, and a Streamlit dashboard with a 6-layer scoring engine.

---

## Overview

TrendShelf is an end-to-end analytics pipeline that ingests live data from five sources, transforms it
through a multi-layer dbt model, and surfaces actionable category-level pricing and stocking
recommendations for Kroger stores in the Dallas-Fort Worth area.

The pipeline answers one question: **which product categories, in which stores, represent the
highest-confidence expansion or pricing opportunity right now?**

---

## Architecture

```
Data Sources (5 APIs)
      |
      v
collect_apis.py  -->  BigQuery bronze layer (raw tables)
      |
      v
dbt (19 models)
  +-- Staging (5 models)      -- type-cast, rename, filter
  +-- Intermediate (7 models) -- join, enrich, score components
  \-- Marts (7 models)        -- final scoring, action queue, intelligence
      |
      v
Streamlit Dashboard (4 pages)
```

---

## Data Sources

| Source | What it provides | Cadence |
|--------|-----------------|---------|
| **Kroger API** | Live shelf prices across 20 DFW stores, 10 categories | Monthly |
| **SerpAPI (Walmart)** | Competitor pricing at Walmart DFW #2105 | Monthly |
| **FRED API** | Producer Price Index (food manufacturing) | Monthly |
| **BLS API** | Consumer Price Index by category | Monthly |
| **Google Trends** | Search demand signals by category keyword | Monthly |

---

## Scoring Engine (6 Layers)

Each store x category pair receives scores across six independent dimensions, then combined into a
single `overall_opportunity_score` (0-100):

| Layer | Model | Weight | What it measures |
|-------|-------|--------|-----------------|
| **Demand Gap** | `mart_demand_gap_analysis` | 25% | Google Trends + BLS demand momentum vs. current shelf presence |
| **Expansion Readiness** | `mart_expansion_readiness` | 20% | Store-level capacity indicators and cross-store benchmarking |
| **Pricing Intelligence** | `mart_pricing_intelligence` | 20% | Price position vs. Walmart competitor; markdown safety margin |
| **Confidence** | `mart_confidence_layer` | 15% | Data completeness and source agreement |
| **Risk** | `mart_risk_assessment` | 10% | Supply chain signals from FRED PPI volatility |
| **Margin Risk** | `mart_margin_risk` | 10% | Margin pressure from input cost trends |

### Opportunity Tiers

```
Prime  >= 75   -- Act now, high confidence
Solid  55-74   -- Strong case, plan this quarter
Watch  35-54   -- Monitor, data improving
Low     < 35   -- Deprioritize
```

All thresholds are centralised in `dbt_project.yml` `vars:` block -- no hardcoding in SQL.

---

## dbt Model Map

```
models/
  staging/
    stg_bls_cpi.sql
    stg_fred_ppi.sql
    stg_google_trends.sql
    stg_kroger_prices.sql
    stg_serpapi_prices.sql

  intermediate/
    int_demand_signals.sql
    int_price_comparison.sql
    int_store_category_base.sql
    int_cost_pressure.sql
    int_category_trends.sql
    int_competitive_position.sql
    int_data_quality.sql

  marts/
    mart_action_queue.sql          <- primary output (store x category, 200 rows)
    mart_confidence_layer.sql
    mart_demand_gap_analysis.sql
    mart_expansion_readiness.sql
    mart_margin_risk.sql
    mart_pricing_intelligence.sql
    mart_risk_assessment.sql
```

**Test coverage:** 93/94 tests passing (1 pre-existing WARN: `price_regular` nulls on weight-sold
products -- expected behaviour).

---

## Dashboard (4 Pages)

### Page 1 -- Intelligence Summary
- 7 KPI metrics in 2 rows: Opportunities, High Confidence, Need Pricing, Prime Opps /
  Expansion Score, Confidence, Data Age
- Avg Opportunity Score by Category -- horizontal bar chart with Prime (75) and Solid (55) threshold lines
- Top action queue table with float columns rounded to 2dp

### Page 2 -- Demand Gap Analysis
- Store-level demand gap scores by category
- Demand signal distribution and trend momentum

### Page 3 -- Pricing Intelligence
- Kroger vs. Walmart price position per category
- Pricing action recommendations (Raise / Maintain / Reduce / Avoid Discount)
- Markdown safety scoring

### Page 4 -- Store Rankings
- Overall opportunity score per store
- Expansion readiness and confidence rankings
- Near-zero delta caption (expected with 1 month of data; spreads with 3+ months)

---

## Project Structure

```
trendshelf/
  collect_apis.py          -- Data ingestion (5 sources -> BigQuery)
  config.py                -- Central config; all values from .env
  .env.example             -- Template (copy to .env and fill in)
  .gitignore
  requirements.txt
  SETUP.md

  models/
    staging/
    intermediate/
    marts/
    schema.yml

  dbt_project.yml          -- vars block: all scoring thresholds
  profiles.yml             -- env_var() -- no hardcoded credentials

  dashboard/
    app.py                 -- Streamlit app (4 pages)
    config.py              -- Imports from root config.py
    queries.py             -- BigQuery query functions (cached ttl=3600)

  docs/
    screenshots/
```

---

## Setup

See [SETUP.md](SETUP.md) for full instructions. Quick start:

```bash
# 1. Clone and create virtual environment
git clone https://github.com/91Sakthivel/trendshelf.git
cd trendshelf
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env
# Edit .env -- fill in GCP_PROJECT_ID, GCP_CREDENTIALS_PATH, KROGER_CLIENT_ID,
# KROGER_CLIENT_SECRET, SERPAPI_KEY, FRED_API_KEY
# Place credentials.json in the project root

# 4. Configure dbt
cp profiles.yml.example profiles.yml
# profiles.yml reads from .env automatically via env_var()

# 5. Run dbt
dbt deps
dbt build

# 6. Launch dashboard
streamlit run dashboard/app.py
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GCP_PROJECT_ID` | Google Cloud project ID | required |
| `GCP_DATASET` | BigQuery dataset name | `bronze` |
| `GCP_CREDENTIALS_PATH` | Path to service account JSON | `credentials.json` |
| `KROGER_CLIENT_ID` | Kroger API OAuth client ID | required |
| `KROGER_CLIENT_SECRET` | Kroger API OAuth client secret | required |
| `SERPAPI_KEY` | SerpAPI key (Walmart scraping) | required |
| `FRED_API_KEY` | FRED API key (PPI data) | required |
| `WALMART_DFW_STORE_ID` | Walmart store ID for competitor pricing | `2105` |
| `COLLECT_KROGER` | Enable Kroger data collection | `True` |
| `COLLECT_SERPAPI` | Enable SerpAPI collection | `True` |
| `COLLECT_FRED` | Enable FRED PPI collection | `True` |
| `COLLECT_BLS` | Enable BLS CPI collection | `True` |
| `COLLECT_GOOGLE_TRENDS` | Enable Google Trends collection | `False` |

---

## Scoring Thresholds (dbt vars)

All thresholds live in `dbt_project.yml` under `vars:`. No SQL hardcoding.

```yaml
vars:
  # Opportunity tier cutoffs
  opp_tier_prime:  75
  opp_tier_solid:  55
  opp_tier_watch:  35

  # Composite score weights (must sum to 1.0)
  opp_weight_demand:      0.25
  opp_weight_expansion:   0.20
  opp_weight_pricing:     0.20
  opp_weight_confidence:  0.15
  opp_weight_risk:        0.10
  opp_weight_margin:      0.10

  # Demand signal thresholds
  demand_high_threshold:    65
  demand_medium_threshold:  45

  # Confidence level thresholds
  confidence_high:    75
  confidence_medium:  50

  # Action logic thresholds
  expand_readiness_threshold:        80
  expand_confidence_threshold:       70
  expand_margin_threshold:           70
  avoid_margin_pressure_threshold:   80
  avoid_markdown_safety_threshold:   40
  investigate_confidence_threshold:  45
```

---

## Reproducibility

- Zero hardcoded credentials or project IDs in any tracked file
- All config flows through `.env` -> `config.py` -> modules
- `profiles.yml` uses dbt `env_var()` -- compatible with CI/CD secret injection
- `credentials.json` and `.env` are gitignored
- `dbt build` is fully deterministic given the same source data

---

## Data Quality Notes

- **93/94 dbt tests passing** -- 1 WARN on `price_regular` nulls for weight-sold items (expected:
  Kroger API returns null price for items sold by weight, e.g. deli meat)
- **Grain**: `mart_action_queue` is one row per store x category (20 stores x 10 categories = 200 rows)
- **Freshness**: Kroger and Walmart data collected monthly; economic indicators (FRED/BLS) lag ~30 days
- **Single-month caveat**: Store ranking deltas are near-zero with one collection cycle -- meaningful
  spread appears at 3+ months

---

## Problems We Solved

Real engineering problems encountered and fixed during development.

### Problem 8 -- UTF-8 BOM in staging SQL files

**What happened:**
All 5 staging SQL files contained a UTF-8 BOM (Byte Order Mark) character at the start.
BigQuery rejected them with:
```
Syntax error: Illegal input character "\357"
```
This caused `dbt run` to fail on the entire staging layer, skipping all 14 downstream models.

**How we found it:**
`dbt run` error output showed `\357` illegal character on the first line of every staging model.
`\357` is octal for `0xEF` -- the first byte of the UTF-8 BOM sequence `0xEF 0xBB 0xBF`.

**How we fixed it:**
Stripped the BOM from all 5 staging files by reading raw bytes and rewriting without the
3-byte preamble. Verified with `[System.IO.File]::ReadAllBytes()` before and after.

**Lesson learned:**
Always save SQL files as UTF-8 without BOM when targeting BigQuery. Windows editors
(including some VS Code configurations) add BOM by default. Check with a hex viewer
if dbt fails with mysterious character encoding errors.

---

### Problem 9 -- Unicode characters breaking Windows console encoding

**What happened:**
`collect_apis.py` used Unicode arrow characters (`->`) in the progress banner.
Windows cp1252 console cannot encode these characters, causing:
```
UnicodeEncodeError: 'charmap' codec can't encode character '→'
```
This caused every collection run to crash before any data was collected.

**How we fixed it:**
Replaced all Unicode `->` with ASCII `->` throughout `collect_apis.py`.
Added `PYTHONIOENCODING=utf-8` as the environment variable for future runs
to prevent similar issues with any remaining Unicode in log output.

**Lesson learned:**
Always use ASCII-safe characters in console output for cross-platform compatibility.
Unicode decorative characters belong in dashboards, not terminal output.
Set `PYTHONIOENCODING=utf-8` in your shell profile if you need Unicode in logs.

---

## What I Would Do With More Time

- **ML scoring layer** -- XGBoost on 6+ months of data with feature importance to validate manual weights
- **Multi-retailer competitor pricing** -- Target, Instacart alongside Walmart for fuller competitive picture
- **Airflow DAGs** -- automated monthly collection pipeline
- **Docker Compose** -- containerized for deployment
- **FastAPI endpoints** -- /actions, /demand-gap, /pricing
- **Claude API narrative** -- Monday morning written summary generated from scoring data

---

## Author

Sakthi | University of North Texas
GitHub: [github.com/91Sakthivel](https://github.com/91Sakthivel)

---

*Built with real API data. No synthetic datasets.*
*Scoring: rule-based with documented assumptions.*
*Data quality: 93/94 dbt tests passing.*
