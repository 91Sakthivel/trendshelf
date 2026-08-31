"""
agent/schemas.py -- Pydantic I/O contracts for every agent tool.

Design rule (Phase 2 proposal, point 5): the 3 quant tools return typed
numeric fields (float/int/date); the 3 RAG tools return RetrievedChunk,
which has NO numeric "value" field anywhere on it. That separation is what
lets Phase 3's verifier trust a claim's source_tool without parsing prose
for numbers -- a claim whose source_tool is a RAG tool structurally cannot
carry a machine-checkable numeric value, because RAG results never had one
to begin with.

Every result type carries `error: str | None`. When error is set, no data
field should be trusted (tools populate one or the other, never both).
`found: bool` (on the two tools where "no data for this period" is a real,
valid outcome) is distinct from error -- a valid store/category with no row
for the requested period is found=False, error=None, NOT an error.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


# ── query_store_category ─────────────────────────────────────────────────

class StoreCategoryResult(BaseModel):
    store_id: str
    category: str
    found: bool
    error: Optional[str] = None
    data_as_of: Optional[date] = None

    recommended_price_action: Optional[str] = None
    price_gap_reliability: Optional[str] = None
    price_gap_confidence: Optional[str] = None
    directional_signal_confidence: Optional[str] = None
    premium_support_proxy_score: Optional[float] = None
    markdown_safety_score: Optional[float] = None
    competitive_intensity: Optional[str] = None
    price_position: Optional[str] = None
    price_reduction_intensity: Optional[str] = None
    action_confidence_level: Optional[str] = None
    category_sensitivity_tier: Optional[str] = None
    demand_signal: Optional[str] = None
    pricing_situation: Optional[str] = None
    kroger_private_label_share: Optional[float] = None
    competitor_price_staleness_days: Optional[int] = None


# ── get_price_history ────────────────────────────────────────────────────

class WeeklyPriceRow(BaseModel):
    kroger_collection_date: date
    price_gap_pct: Optional[float] = None
    price_gap_direction: str
    price_position: str
    competitor_reliability: str
    competitor_staleness_days: int
    kroger_product_count: int
    basket_mismatch_flag: bool


class PriceHistoryResult(BaseModel):
    store_id: str
    category: str
    found: bool
    error: Optional[str] = None
    rows: list[WeeklyPriceRow] = Field(default_factory=list)


# ── check_data_freshness ─────────────────────────────────────────────────

class DataFreshnessResult(BaseModel):
    error: Optional[str] = None
    kroger_hours_ago: Optional[int] = None
    trends_hours_ago: Optional[int] = None
    fred_hours_ago: Optional[int] = None
    bls_hours_ago: Optional[int] = None
    serpapi_hours_ago: Optional[int] = None
    source_count: Optional[int] = None
    collection_recency_score: Optional[float] = None
    distinct_freshness_combos: Optional[int] = None
    # Set only if distinct_freshness_combos != 1 -- see docs/threshold_decisions.md
    # #7.19: these fields are row-independent by design (one shared collector
    # run per snapshot). If that assumption ever breaks, this tool should say
    # so rather than silently picking one row's values.
    anomaly: Optional[str] = None


# ── RAG tools (lookup_methodology, get_threshold_rationale, search_external_context) ──

class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    doc_title: str
    chunk_text: str
    source_url: Optional[str] = None
    source_tier: str
    published_date: Optional[date] = None
    contains_numeric_claim: bool
    # COSINE distance from VECTOR_SEARCH, lower = more similar. Named
    # "distance" not "score" on purpose -- it is not a confidence value.
    similarity_distance: float


class DocSearchResult(BaseModel):
    query: str
    error: Optional[str] = None
    chunks: list[RetrievedChunk] = Field(default_factory=list)
