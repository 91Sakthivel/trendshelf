"""
Source registry — one entry per document TrendShelf's corpus should contain.

Each entry declares its own fetch method. `run_ingest.py` iterates this list
and processes every source independently (same per-source failure policy as
`collect_apis.py`'s price collectors — one source failing does not block the
others). Nothing here is fetched implicitly; adding a document means adding
a row here.
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# fetch = "internal_file"  -> read straight from the repo
# fetch = "sec_edgar"      -> ingestion.fetch_sec
# fetch = "fred_api"       -> ingestion.fetch_gov
# fetch = "http_page"      -> ingestion.fetch_gov (generic requests+bs4, defensive)
# fetch = "manual"         -> ingestion.manual_sources/ + manifest, see run_ingest

SOURCES = [
    # ── Internal (authoritative) ─────────────────────────────────────────────
    {
        "document_id": "internal_threshold_decisions",
        "source_class": "internal",
        "source_tier": "internal_doc",
        "doc_title": "TrendShelf — Threshold and Prior Decisions",
        "fetch": "internal_file",
        "path": os.path.join(REPO_ROOT, "docs", "threshold_decisions.md"),
        "source_url": None,
    },
    {
        "document_id": "internal_scoring_methodology",
        "source_class": "internal",
        "source_tier": "internal_doc",
        "doc_title": "TrendShelf — Scoring Methodology",
        "fetch": "internal_file",
        "path": os.path.join(REPO_ROOT, "docs", "scoring_methodology.md"),
        "source_url": None,
    },
    {
        "document_id": "internal_signal_stability_backtest",
        "source_class": "internal",
        "source_tier": "internal_doc",
        "doc_title": "TrendShelf — Signal-Stability Backtest, Phase 0",
        "fetch": "internal_file",
        "path": os.path.join(REPO_ROOT, "docs", "signal_stability_backtest.md"),
        "source_url": None,
    },
    {
        "document_id": "internal_readme",
        "source_class": "internal",
        "source_tier": "internal_doc",
        "doc_title": "TrendShelf — README",
        "fetch": "internal_file",
        "path": os.path.join(REPO_ROOT, "README.md"),
        "source_url": None,
    },

    # ── External, scripted (reliable, official/stable APIs) ──────────────────
    {
        "document_id": "kroger_10k",
        "source_class": "external",
        "source_tier": "sec_filing",
        "doc_title": "The Kroger Co. — Form 10-K (Item 1, 1A, 7)",
        "fetch": "sec_edgar",
        "cik": 56873,
        "ticker": "KR",
    },
    {
        "document_id": "walmart_10k",
        "source_class": "external",
        "source_tier": "sec_filing",
        "doc_title": "Walmart Inc. — Form 10-K (Item 1, 1A, 7)",
        "fetch": "sec_edgar",
        "cik": 104169,
        "ticker": "WMT",
    },
    {
        "document_id": "fred_pcu311311_methodology",
        "source_class": "external",
        "source_tier": "gov_methodology",
        "doc_title": "FRED — PCU311311 Series Metadata and Notes",
        "fetch": "fred_api",
        "series_id": "PCU311311",
        "source_url": "https://fred.stlouisfed.org/series/PCU311311",
    },
    {
        "document_id": "usda_ers_food_price_outlook",
        "source_class": "external",
        "source_tier": "gov_methodology",
        "doc_title": "USDA ERS — Food Price Outlook",
        "fetch": "http_page",
        "url": "https://www.ers.usda.gov/data-products/food-price-outlook/",
    },

    # ── External, manual placement (scripted fetch not reliable — see report) ─
    # bls.gov returns 403 to scripted requests regardless of User-Agent (bot
    # protection, not a URL-stability problem) — moved here from the STEP 1
    # proposal's "scriptable" list after actually attempting the fetch.
    {
        "document_id": "bls_cpi_methodology",
        "source_class": "external",
        "source_tier": "gov_methodology",
        "doc_title": "BLS — CPI Handbook of Methods",
        "fetch": "manual",
        "note": "bls.gov returns HTTP 403 to scripted requests (bot-protected). "
                "Manually save the CPI Handbook of Methods page as text/HTML into "
                "manual_sources/ and add a manifest entry.",
    },
    {
        "document_id": "kroger_earnings_call_1",
        "source_class": "external",
        "source_tier": "earnings_call",
        "doc_title": "Kroger — Earnings Call Transcript (placeholder slot 1)",
        "fetch": "manual",
        "note": "No stable official transcript API exists. Manually place a "
                "transcript (Kroger IR prepared remarks, or a reputable "
                "aggregator) and add a manifest entry.",
    },
    {
        "document_id": "kroger_earnings_call_2",
        "source_class": "external",
        "source_tier": "earnings_call",
        "doc_title": "Kroger — Earnings Call Transcript (placeholder slot 2)",
        "fetch": "manual",
        "note": "Same as kroger_earnings_call_1.",
    },
    {
        "document_id": "industry_research_1",
        "source_class": "external",
        "source_tier": "industry_research",
        "doc_title": "FMI/NielsenIQ Category Trend Report (industry commentary, placeholder slot 1)",
        "fetch": "manual",
        "note": "FMI/NielsenIQ reports are lead-gated PDF downloads, no stable "
                "direct-fetch URL. Manually place the PDF and add a manifest entry.",
    },
    {
        "document_id": "industry_research_2",
        "source_class": "external",
        "source_tier": "industry_research",
        "doc_title": "FMI/NielsenIQ Category Trend Report (industry commentary, placeholder slot 2)",
        "fetch": "manual",
        "note": "Same as industry_research_1.",
    },
]
