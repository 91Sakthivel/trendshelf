"""
tests/agent/test_tools_known_values.py

One hand-verified fixture per tool, per the Phase 2 build instructions:
"query the mart by hand FIRST, record the real value, hardcode it as
expected." Every value below was queried directly against live BigQuery
(bronze + rag_corpus, project windy-container-451804-n4) before this file
was written -- see the Phase 2 build report for the exact hand-query
transcript. A tool is only added to agent.tools.VERIFIED_TOOLS once its
fixture here passes.

check_data_freshness is a deliberate exception to "hardcode the value":
docs/threshold_decisions.md #7.19 already documents that these fields
drift with wall-clock time by design (collected_at-based, not
observation_date-based), so a hardcoded hour count would go stale and
start failing for reasons that have nothing to do with the tool being
broken. Its fixture instead re-runs the same aggregation by hand inside
the test and asserts the tool matches that live re-query, plus the
structural invariant (#7.19: exactly one distinct freshness combo across
all rows) that IS stable.
"""
from datetime import date

from google.cloud import bigquery

from agent import bq
from agent.tools.docs import get_threshold_rationale, lookup_methodology, search_external_context
from agent.tools.marts import check_data_freshness, get_price_history, query_store_category
import config


# ── query_store_category ─────────────────────────────────────────────────

def test_query_store_category_known_value():
    """Hand-queried 2026-08-31 against mart_pricing_intelligence:
    store 01100002 (Denton) x beverages, latest scoring_date = 2026-08-01."""
    r = query_store_category("01100002", "beverages")
    assert r.found is True
    assert r.error is None
    assert r.data_as_of == date(2026, 8, 1)
    assert r.recommended_price_action == "Monitor"
    assert r.price_gap_reliability == "Low"
    assert r.price_gap_confidence == "High"
    assert r.directional_signal_confidence == "Unreliable"
    assert r.premium_support_proxy_score == 54.76
    assert r.markdown_safety_score == 44.07
    assert r.competitive_intensity == "Saturated"
    assert r.price_position == "Underpriced"
    assert r.price_reduction_intensity == "N/A"
    assert r.action_confidence_level == "Medium"
    assert r.category_sensitivity_tier == "Low"
    assert r.demand_signal == "Medium"
    assert r.pricing_situation == "Weak Demand"
    assert r.kroger_private_label_share == 0.0
    assert r.competitor_price_staleness_days == 0


def test_query_store_category_specific_month():
    """Same store/category, pinned to 2026-06-01 -- a different hand-verified row."""
    r = query_store_category("01100002", "beverages", reference_month=date(2026, 6, 1))
    assert r.found is True
    assert r.data_as_of == date(2026, 6, 1)
    assert r.premium_support_proxy_score == 55.25
    assert r.markdown_safety_score == 49.96
    assert r.pricing_situation == "Weak Demand"


def test_query_store_category_unknown_store_is_error_not_null_result():
    r = query_store_category("99999999", "beverages")
    assert r.found is False
    assert r.error is not None
    assert "99999999" in r.error
    assert r.premium_support_proxy_score is None


def test_query_store_category_unknown_category_is_error_not_null_result():
    r = query_store_category("01100002", "nonexistent_category")
    assert r.found is False
    assert r.error is not None
    assert "nonexistent_category" in r.error


# ── get_price_history ────────────────────────────────────────────────────

def test_get_price_history_known_values():
    """Hand-queried against fct_store_category_weekly: store 01100002 x
    beverages, 5 most recent weeks as of 2026-08-31."""
    r = get_price_history("01100002", "beverages", weeks=5)
    assert r.found is True
    assert r.error is None
    assert len(r.rows) == 5

    dates = [row.kroger_collection_date for row in r.rows]
    assert dates == [
        date(2026, 8, 26), date(2026, 8, 19), date(2026, 8, 12),
        date(2026, 8, 5), date(2026, 7, 29),
    ]

    latest = r.rows[0]
    assert latest.price_gap_pct == -71.62
    assert latest.price_gap_direction == "Underpriced"
    assert latest.competitor_reliability == "Low"
    assert latest.kroger_product_count == 49
    assert latest.basket_mismatch_flag is True

    third = r.rows[2]  # 2026-08-12, a distinctly different value than the latest 2 rows
    assert third.price_gap_pct == 0.37
    assert third.price_gap_direction == "Overpriced"
    assert third.price_position == "Fair"
    assert third.competitor_reliability == "High"
    assert third.basket_mismatch_flag is False


def test_get_price_history_weeks_beyond_available_history_not_an_error():
    """Only 13 collection dates exist project-wide -- asking for more must
    return everything there is, not fail."""
    r = get_price_history("01100002", "beverages", weeks=500)
    assert r.error is None
    assert 0 < len(r.rows) <= 13


def test_get_price_history_unknown_identifiers_error():
    r = get_price_history("bad_store", "beverages")
    assert r.found is False
    assert r.error is not None


# ── check_data_freshness ─────────────────────────────────────────────────

def test_check_data_freshness_matches_live_requery_and_invariant_holds():
    r = check_data_freshness()
    assert r.error is None

    # Structural invariant (#7.19): exactly one shared freshness reading
    # across the whole mart. Stable regardless of wall-clock drift.
    assert r.distinct_freshness_combos == 1
    assert r.anomaly is None
    assert r.source_count == 5

    # Cross-check against an independent hand-written re-query, run live in
    # this test rather than against a hardcoded hour count.
    manual = bq.run_query(f"""
        SELECT ANY_VALUE(kroger_hours_ago) AS kroger_hours_ago,
               ANY_VALUE(collection_recency_score) AS collection_recency_score
        FROM `{config.PROJECT_ID}.{config.DATASET}.mart_confidence_layer`
    """)[0]
    assert r.kroger_hours_ago == manual["kroger_hours_ago"]
    assert r.collection_recency_score == manual["collection_recency_score"]


# ── get_threshold_rationale ──────────────────────────────────────────────

def test_get_threshold_rationale_known_top_hit():
    """Hand-queried VECTOR_SEARCH, query='why is pitch_readiness_floor 65',
    filtered to internal_threshold_decisions: top hit is chunk e9c2c913...,
    distance ~0.2592."""
    r = get_threshold_rationale("why is pitch_readiness_floor 65")
    assert r.error is None
    assert len(r.chunks) > 0
    top = r.chunks[0]
    assert top.chunk_id == "e9c2c91308ae85ba972d609256dace75e8c53877b9212f6e212ebda725a2b54a"
    assert top.document_id == "internal_threshold_decisions"
    assert abs(top.similarity_distance - 0.2592) < 0.01
    # scoping constraint: every result must come from the one doc requested,
    # never README's or scoring_methodology.md's copy of the same number
    # (this is the direct fix for the #7.24 ranking finding)
    assert all(c.document_id == "internal_threshold_decisions" for c in r.chunks)


def test_get_threshold_rationale_never_returns_other_internal_docs():
    r = get_threshold_rationale("cv_multiplier price band width")
    assert r.error is None
    assert all(c.document_id == "internal_threshold_decisions" for c in r.chunks)


# ── lookup_methodology ───────────────────────────────────────────────────

def test_lookup_methodology_known_top_hit():
    """Hand-queried, query='how is markdown_safety_score calculated',
    source_class='internal': top hit chunk e71b7716..., distance ~0.2527."""
    r = lookup_methodology("how is markdown_safety_score calculated")
    assert r.error is None
    assert len(r.chunks) > 0
    top = r.chunks[0]
    assert top.chunk_id == "e71b7716bde8e315129545b2b9dda431e2351ce1a781b95f39d06cf66d285600"
    assert top.document_id == "internal_threshold_decisions"
    assert abs(top.similarity_distance - 0.2527) < 0.01
    # scoping constraint: internal only, never a 10-K or FRED/USDA chunk
    assert all(
        c.document_id in {
            "internal_readme", "internal_scoring_methodology",
            "internal_threshold_decisions", "internal_signal_stability_backtest",
        }
        for c in r.chunks
    )


# ── search_external_context ──────────────────────────────────────────────

def test_search_external_context_known_top_hit():
    """Hand-queried, query='what business segments does Walmart operate',
    source_class='external': top hit chunk 600f8d28..., distance ~0.2976."""
    r = search_external_context("what business segments does Walmart operate")
    assert r.error is None
    assert len(r.chunks) > 0
    top = r.chunks[0]
    assert top.chunk_id == "600f8d284a7f36644c9aa8aec2f4127bb32f979fab47bb2803170dafb69430d5"
    assert top.document_id == "walmart_10k"
    assert abs(top.similarity_distance - 0.2976) < 0.01
    # scoping constraint: external only, never an internal doc
    assert all(
        c.document_id in {
            "kroger_10k", "walmart_10k", "fred_pcu311311_methodology",
            "usda_ers_food_price_outlook",
        }
        for c in r.chunks
    )


def test_search_external_context_and_lookup_methodology_are_disjoint_by_source_class():
    """The 6th tool exists specifically because lookup_methodology's
    internal-only scope can't reach external sources -- confirm the two
    tools never return overlapping document_ids for the same question."""
    q = "pricing and cost trends"
    external = search_external_context(q)
    internal = lookup_methodology(q)
    assert external.error is None and internal.error is None
    external_docs = {c.document_id for c in external.chunks}
    internal_docs = {c.document_id for c in internal.chunks}
    assert external_docs.isdisjoint(internal_docs)
