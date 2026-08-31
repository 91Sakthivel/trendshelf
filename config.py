"""
config.py — Central configuration for TrendShelf.
All hardcoded values live here; all other modules import from this file.
Reads credentials and flags from .env at project root.
"""

from dotenv import load_dotenv
import os

# Load .env from project root regardless of working directory
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── BigQuery ───────────────────────────────────────────────────────────────────
PROJECT_ID       = os.getenv("GCP_PROJECT_ID")
DATASET          = os.getenv("GCP_DATASET", "bronze")
CREDENTIALS_PATH = os.getenv("GCP_CREDENTIALS_PATH", "credentials.json")

# Resolve relative credential paths against project root
if not os.path.isabs(CREDENTIALS_PATH):
    CREDENTIALS_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), CREDENTIALS_PATH
    )

# ── APIs ───────────────────────────────────────────────────────────────────────
KROGER_CLIENT_ID     = os.getenv("KROGER_CLIENT_ID")
KROGER_CLIENT_SECRET = os.getenv("KROGER_CLIENT_SECRET")
SERPAPI_KEY          = os.getenv("SERPAPI_KEY")
FRED_API_KEY         = os.getenv("FRED_API_KEY")

# ── Collection flags ───────────────────────────────────────────────────────────
COLLECT_GOOGLE_TRENDS = os.getenv("COLLECT_GOOGLE_TRENDS", "False") == "True"
COLLECT_SERPAPI       = os.getenv("COLLECT_SERPAPI",       "True")  == "True"
COLLECT_KROGER        = os.getenv("COLLECT_KROGER",        "True")  == "True"
COLLECT_FRED          = os.getenv("COLLECT_FRED",          "True")  == "True"
COLLECT_BLS           = os.getenv("COLLECT_BLS",           "True")  == "True"

# ── Walmart DFW competitor stores ──────────────────────────────────────────────
# Mirrors KROGER_STORES' shape (hardcoded here, not read from .env, same as Kroger's
# list) so collect_serpapi() can loop over stores the same way collect_kroger_prices()
# already does. Kept at ONE entry deliberately -- this is Tier 2 collector-capability
# prep, not the store rollout. See docs/threshold_decisions.md #7.18.
# Verified: Walmart Supercenter, 4122 LBJ Fwy, Dallas TX 75244
# Source: walmart.com/store/2105-dallas-tx
WALMART_STORES = [
    {"id": "2105", "city": "Dallas - LBJ Fwy"},
]

# Backward-compat alias: dashboard/app.py and dashboard/config.py import this name
# directly (display-only, not collection logic) and are out of scope for this fix.
# Derived from the list above so it can't drift from it.
WALMART_DFW_STORE_ID = WALMART_STORES[0]["id"]

# ── FRED PPI series ──────────────────────────────────────────────────────────
# FRED_SCORING_PPI_SERIES_ID must match dbt_project.yml's scoring_ppi_series_id.
# If they drift, tests/assert_ppi_series_resolves.sql fails (stg_fred_ppi returns
# zero rows for the configured var). See docs/threshold_decisions.md #7.7.
FRED_SCORING_PPI_SERIES_ID = "PCU311311"
# SCORING SERIES — "PPI by Industry: Food Manufacturing." A producer-side
# input-cost index. Swapped in from PCU42440042440012 (see below); a fetch
# failure on this series aborts the whole collector write, since dbt scores it.

FRED_SUPPLEMENTARY_PPI_SERIES = ["PCU42440042440012"]
# Diagnostic only, not wired into scoring. "PPI by Industry: Grocery and Related
# Product Merchant Wholesalers: Wholesaling of Packaged Frozen and Canned Foods."
# A wholesale-trade margin index — the prior scoring series, retained for
# comparison. A fetch failure here only warns and is skipped.

# ── Dashboard deployment facts ─────────────────────────────────────────────────
TOTAL_DBT_MODELS = 19

# ── Kroger DFW stores ──────────────────────────────────────────────────────────
# Real store IDs from Kroger API (50-mile radius, zip 75201)
# Verified 2026-06-08 via GET /v1/locations
KROGER_STORES = [
    {"id": "01100002", "city": "Denton"},
    {"id": "03500529", "city": "Dallas - Capitol Ave"},
    {"id": "03500528", "city": "Dallas - Cedar Springs"},
    {"id": "03500509", "city": "Dallas - Maple Ave"},
    {"id": "03500518", "city": "Dallas"},
    {"id": "03500213", "city": "Dallas - Wynnewood"},
    {"id": "03500511", "city": "Dallas - Northview"},
    {"id": "03500588", "city": "Dallas - Forest Lane"},
    {"id": "03500495", "city": "Irving - South"},
    {"id": "03500450", "city": "Mesquite - Towne Crossing"},
    {"id": "03500429", "city": "Irving - Story"},
    {"id": "03500527", "city": "Duncanville"},
    {"id": "03500526", "city": "Richardson - Buckingham"},
    {"id": "03500492", "city": "Balch Springs"},
    {"id": "03500209", "city": "Mesquite - Kroger Plaza"},
    {"id": "03500517", "city": "Richardson - Coit"},
    {"id": "03500870", "city": "Addison"},
    {"id": "03500402", "city": "Irving - Northgate Hills"},
    {"id": "03500559", "city": "Garland"},
    {"id": "03500545", "city": "Desoto"},
]

# ── Product categories ─────────────────────────────────────────────────────────
CATEGORIES = [
    "beverages",
    "snacks",
    "dairy",
    "frozen foods",
    "breakfast cereal",
    "meat seafood",
    "produce",
    "personal care",
    "household",
    "coffee tea",
]

# ── Walmart search query per category ─────────────────────────────────────────
# Specific terms chosen to return single grocery items, not bundles or non-food
# "bagged salad mix" avoids gardening/nursery results for "produce"
WALMART_QUERIES = {
    "beverages":        "energy drinks",
    "snacks":           "chips snacks",
    "dairy":            "yogurt",
    "frozen foods":     "frozen meals",
    "breakfast cereal": "breakfast cereal",
    "meat seafood":     "fresh chicken",
    "produce":          "bagged salad mix",
    "personal care":    "shampoo",
    "household":        "paper towels",
    "coffee tea":       "ground coffee",
}

# ── Google Trends keyword per category ────────────────────────────────────────
# Category-level terms to avoid brand noise and double-counting
GOOGLE_TRENDS_KEYWORDS = {
    "beverages":        "energy drinks",
    "snacks":           "chips snacks",
    "dairy":            "yogurt dairy",
    "frozen foods":     "frozen meals",
    "breakfast cereal": "breakfast cereal",
    "meat seafood":     "fresh chicken",
    "produce":          "fresh vegetables",
    "personal care":    "shampoo conditioner",
    "household":        "paper towels",
    "coffee tea":       "coffee beans",
}

# ── Agent (Phase 2) ──────────────────────────────────────────────────────────
# Read-only against bronze (marts) and rag_corpus. Uses a DEDICATED service
# account with roles/aiplatform.user + roles/bigquery.dataViewer +
# roles/bigquery.jobUser only -- no write role, so "the agent never writes to
# BigQuery" is an IAM boundary, not app-code discipline. That SA doesn't exist
# yet (see the Phase 2 build report for the exact gcloud commands to create
# it); until it does, AGENT_CREDENTIALS_PATH falls back to the same key the
# collector uses, which happens to have read access to the tables the agent
# needs. Swap the env var once the dedicated key exists -- no code change.
AGENT_CREDENTIALS_PATH = os.getenv("AGENT_GCP_CREDENTIALS_PATH", CREDENTIALS_PATH)
if not os.path.isabs(AGENT_CREDENTIALS_PATH):
    AGENT_CREDENTIALS_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), AGENT_CREDENTIALS_PATH
    )

RAG_CORPUS_DATASET = os.getenv("RAG_CORPUS_DATASET", "rag_corpus")

# Safety cap on every BigQuery call a tool makes. Marts are ~400 rows total;
# 100 MB is generous headroom, not a real limit -- same hygiene as the 10 GiB
# dbt-level cap (see the CI commit), just sized to what a tool query should
# ever actually touch.
AGENT_MAX_BYTES_BILLED = 100 * 1024 * 1024

# Placeholder, not a derived value -- same status as retail_healthy_pct_divisor
# (docs/threshold_decisions.md #7.13) and the industry_research staleness
# window (#7.22). Phase 4 gives real turn-count distributions to derive this
# from; until then it's a guess accepted as a starting point, not a measurement.
AGENT_MAX_TOOL_ITERATIONS = 8
