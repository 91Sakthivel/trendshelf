"""All BigQuery query functions for the TrendShelf dashboard."""

import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from dashboard.config import PROJECT_ID, DATASET, CREDENTIALS_PATH

P = PROJECT_ID
D = DATASET


def _client():
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    return bigquery.Client(project=P, credentials=creds)


def _run(sql: str) -> pd.DataFrame:
    client = _client()
    return client.query(sql).to_dataframe()


# ── Query functions ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def get_action_queue() -> pd.DataFrame:
    """Full mart_action_queue ordered by opportunity score desc."""
    return _run(f"""
        SELECT
            action_priority,
            action_type,
            recommended_action,
            urgency,
            decision_strength,
            signal_type,
            store_id,
            store_name,
            category_name,
            state,
            region,
            action_description,
            action_reason,
            expected_impact,
            reason_code,
            driving_score,
            overall_confidence_score,
            overall_demand_gap_score,
            overall_risk_score,
            overall_margin_risk_score,
            row_level_source_coverage_score,
            score_version,
            load_timestamp,
            overall_opportunity_score,
            opportunity_tier,
            category_lifecycle,
            seasonality_adjusted_action,
            demand_velocity_direction,
            demand_reason_code,
            risk_reason_code,
            competitive_intensity,
            macro_risk_flag
        FROM `{P}.{D}.mart_action_queue`
        ORDER BY overall_opportunity_score DESC, overall_confidence_score DESC
    """)


@st.cache_data(ttl=3600)
def get_pricing_intelligence() -> pd.DataFrame:
    """Full mart_pricing_intelligence with macro_risk_flag joined from mart_action_queue."""
    return _run(f"""
        SELECT
            pi.*,
            aq.macro_risk_flag
        FROM `{P}.{D}.mart_pricing_intelligence` pi
        LEFT JOIN `{P}.{D}.mart_action_queue` aq
               ON pi.store_id      = aq.store_id
              AND pi.category_name = aq.category_name
        ORDER BY pi.action_confidence_score DESC
    """)


@st.cache_data(ttl=3600)
def get_demand_scores() -> pd.DataFrame:
    """
    mart_demand_gap_scores joined with dim_location, mart_expansion_readiness,
    and mart_action_queue for demand_velocity_direction and seasonality_flag.
    """
    return _run(f"""
        SELECT
            d.store_id,
            COALESCE(l.store_name, d.store_id)      AS store_city,
            d.category_name,
            d.reference_month,
            d.overall_demand_gap_score,
            d.search_to_shelf_gap,
            d.category_momentum_score,
            d.demand_trend_direction,
            d.intent_quality_score,
            d.avg_search_interest,
            d.shelf_product_count,
            d.phantom_distribution,
            d.phantom_signal_type,
            d.ppi_trend_direction,
            d.cpi_trend_direction,
            er.expansion_readiness_score,
            aq.demand_velocity_direction,
            aq.seasonality_flag
        FROM `{P}.{D}.mart_demand_gap_scores`        d
        LEFT JOIN `{P}.{D}.dim_location`              l
               ON d.store_id = l.store_id
        LEFT JOIN `{P}.{D}.mart_expansion_readiness`  er
               ON d.signal_id = er.signal_id
        LEFT JOIN `{P}.{D}.mart_action_queue`         aq
               ON d.store_id      = aq.store_id
              AND d.category_name = aq.category_name
        ORDER BY d.overall_demand_gap_score DESC
    """)


@st.cache_data(ttl=3600)
def get_google_trends() -> pd.DataFrame:
    """
    stg_google_trends with a derived seasonality_flag:
    rows where interest_score > category_avg + 1 stddev are marked
    'Possible Seasonal Spike', all others 'Normal'.
    """
    return _run(f"""
        SELECT
            search_keyword,
            category,
            trend_date,
            interest_score,
            geography,
            CASE
                WHEN interest_score >
                     AVG(interest_score) OVER (PARTITION BY category) +
                     STDDEV(interest_score) OVER (PARTITION BY category)
                THEN 'Possible Seasonal Spike'
                ELSE 'Normal'
            END AS seasonality_flag
        FROM `{P}.{D}.stg_google_trends`
        ORDER BY category, trend_date
    """)


@st.cache_data(ttl=3600)
def get_expansion_avg() -> float:
    """Average expansion readiness score across all signals (KPI card)."""
    df = _run(f"""
        SELECT ROUND(AVG(expansion_readiness_score), 1) AS avg_val
        FROM `{P}.{D}.mart_expansion_readiness`
    """)
    if df.empty:
        return 0.0
    return float(df["avg_val"].iloc[0] or 0)


@st.cache_data(ttl=3600)
def get_avg_confidence() -> float:
    """Average overall_confidence_score from mart_confidence_layer (KPI card)."""
    df = _run(f"""
        SELECT ROUND(AVG(overall_confidence_score), 1) AS avg_val
        FROM `{P}.{D}.mart_confidence_layer`
    """)
    if df.empty:
        return 0.0
    return float(df["avg_val"].iloc[0] or 0)


@st.cache_data(ttl=3600)
def get_top_pricing_actions() -> pd.DataFrame:
    """Top 5 non-Monitor rows from mart_pricing_intelligence."""
    return _run(f"""
        SELECT
            store_city,
            category_name,
            recommended_price_action,
            ROUND(kroger_avg_price,     2) AS kroger_avg_price,
            ROUND(recommended_price,    2) AS recommended_price,
            action_confidence_score,
            action_confidence_level,
            ROUND(price_gap_pct,        1) AS price_gap_pct,
            elasticity_tier
        FROM `{P}.{D}.mart_pricing_intelligence`
        WHERE recommended_price_action NOT IN ('Monitor', 'Investigate')
        ORDER BY action_confidence_score DESC
        LIMIT 5
    """)


@st.cache_data(ttl=3600)
def get_dfw_avg_scores() -> dict:
    """
    DFW-wide averages for the 6 radar axes, used as the comparison polygon
    on Page 4. Shelf risk is already inverted (100 - avg_risk).
    """
    df = _run(f"""
        SELECT
            ROUND(AVG(aq.overall_demand_gap_score),   1) AS avg_demand_gap,
            ROUND(AVG(er.expansion_readiness_score),  1) AS avg_expansion,
            ROUND(AVG(pi.pricing_power_score),        1) AS avg_pricing_power,
            ROUND(AVG(aq.overall_confidence_score),   1) AS avg_confidence,
            ROUND(100 - AVG(aq.overall_risk_score),   1) AS avg_risk_inv,
            ROUND(AVG(pi.markdown_safety_score),      1) AS avg_markdown_safety
        FROM `{P}.{D}.mart_action_queue`          aq
        LEFT JOIN `{P}.{D}.mart_expansion_readiness` er
               ON aq.store_id = er.store_id AND aq.category_name = er.category_name
        LEFT JOIN `{P}.{D}.mart_pricing_intelligence` pi
               ON aq.store_id = pi.store_id AND aq.category_name = pi.category_name
    """)
    fallback = dict(avg_demand_gap=50.0, avg_expansion=50.0, avg_pricing_power=50.0,
                    avg_confidence=50.0, avg_risk_inv=50.0, avg_markdown_safety=50.0)
    if df.empty:
        return fallback
    return {k: float(v or 50.0) for k, v in df.iloc[0].to_dict().items()}


@st.cache_data(ttl=3600)
def get_store_health_rankings() -> pd.DataFrame:
    """Per-store health scores for ranking context on Page 4."""
    return _run(f"""
        SELECT
            aq.store_id,
            aq.store_name,
            ROUND(AVG(aq.overall_demand_gap_score),  1) AS avg_demand_gap,
            ROUND(AVG(aq.overall_confidence_score),  1) AS avg_confidence,
            ROUND(AVG(er.expansion_readiness_score), 1) AS avg_expansion,
            ROUND(
                (AVG(aq.overall_demand_gap_score)  +
                 AVG(aq.overall_confidence_score)  +
                 AVG(er.expansion_readiness_score)) / 3.0,
            1) AS health_score
        FROM `{P}.{D}.mart_action_queue` aq
        LEFT JOIN `{P}.{D}.mart_expansion_readiness` er
               ON aq.store_id = er.store_id
              AND aq.category_name = er.category_name
        GROUP BY aq.store_id, aq.store_name
        ORDER BY health_score DESC
    """)


@st.cache_data(ttl=3600)
def get_store_list() -> pd.DataFrame:
    """
    Distinct store_id / display_name pairs.
    Uses mart_action_queue.store_name which preserves 'Dallas - Capitol Ave'.
    """
    return _run(f"""
        SELECT DISTINCT store_id, store_name AS display_name
        FROM `{P}.{D}.mart_action_queue`
        ORDER BY store_name
    """)


@st.cache_data(ttl=3600)
def get_store_scores(store_id: str) -> pd.DataFrame:
    """Per-category scoring profile for one store."""
    safe_id = store_id.replace("'", "")
    return _run(f"""
        SELECT
            aq.category_name,
            aq.action_type,
            aq.decision_strength,
            ROUND(aq.overall_demand_gap_score,    1) AS demand_gap_score,
            ROUND(aq.overall_confidence_score,    1) AS confidence_score,
            ROUND(aq.overall_risk_score,          1) AS risk_score,
            ROUND(aq.overall_margin_risk_score,   1) AS margin_risk_score,
            aq.action_reason,
            aq.reason_code,
            ROUND(er.expansion_readiness_score,   1) AS expansion_readiness_score,
            ROUND(er.region_opportunity_score,    1) AS region_opportunity_score,
            ROUND(er.store_market_fit_score,      1) AS store_market_fit_score,
            ROUND(pi.pricing_power_score,         1) AS pricing_power_score,
            ROUND(pi.markdown_safety_score,       1) AS markdown_safety_score,
            ROUND(pi.kroger_avg_price,            2) AS kroger_avg_price,
            ROUND(pi.competitor_avg_price,        2) AS competitor_avg_price,
            ROUND(pi.price_gap_pct,               1) AS price_gap_pct,
            ROUND(pi.recommended_price,           2) AS recommended_price,
            pi.recommended_price_action,
            pi.price_action_reason,
            pi.pricing_situation,
            pi.action_confidence_level,
            pi.action_confidence_score,
            pi.demand_signal,
            pi.store_city,
            ROUND(aq.overall_opportunity_score,   1) AS overall_opportunity_score,
            aq.opportunity_tier,
            aq.category_lifecycle,
            aq.demand_velocity_direction,
            aq.demand_reason_code,
            aq.risk_reason_code,
            aq.macro_risk_flag
        FROM `{P}.{D}.mart_action_queue`             aq
        LEFT JOIN `{P}.{D}.mart_expansion_readiness`  er
               ON aq.store_id      = er.store_id
              AND aq.category_name = er.category_name
        LEFT JOIN `{P}.{D}.mart_pricing_intelligence` pi
               ON aq.store_id      = pi.store_id
              AND aq.category_name = pi.category_name
        WHERE aq.store_id = '{safe_id}'
        ORDER BY aq.overall_opportunity_score DESC, aq.overall_confidence_score DESC
    """)


@st.cache_data(ttl=3600)
def get_data_freshness() -> pd.DataFrame:
    """Last collected_at per raw source table."""
    return _run(f"""
        SELECT 'Kroger Prices'  AS source, MAX(collected_at) AS last_updated
        FROM `{P}.{D}.kroger_prices_raw`
        UNION ALL
        SELECT 'SerpAPI Prices', MAX(collected_at)
        FROM `{P}.{D}.serpapi_prices_raw`
        UNION ALL
        SELECT 'Google Trends', MAX(collected_at)
        FROM `{P}.{D}.google_trends_raw`
        UNION ALL
        SELECT 'FRED PPI',      MAX(collected_at)
        FROM `{P}.{D}.fred_ppi_raw`
        UNION ALL
        SELECT 'BLS CPI',       MAX(collected_at)
        FROM `{P}.{D}.bls_cpi_raw`
    """)


@st.cache_data(ttl=3600)
def get_intelligence_summary() -> dict:
    """Macro environment and velocity summary for sidebar Intelligence Layer section."""
    df = _run(f"""
        SELECT
            ANY_VALUE(macro_risk_flag)                                                             AS macro_env,
            COUNT(DISTINCT IF(seasonality_flag = 'Possible Seasonal Spike', category_name, NULL)) AS active_spikes,
            COUNT(DISTINCT IF(demand_velocity_direction = 'Accelerating', category_name, NULL))   AS accelerating_cats,
            (
                SELECT category_name
                FROM `{P}.{D}.mart_action_queue`
                GROUP BY category_name
                ORDER BY AVG(overall_opportunity_score) DESC
                LIMIT 1
            )                                                                                      AS top_opportunity
        FROM `{P}.{D}.mart_action_queue`
    """)
    fallback = dict(macro_env="—", active_spikes=0, accelerating_cats=0, top_opportunity="—")
    if df.empty:
        return fallback
    row = df.iloc[0].to_dict()
    return {k: (v if v is not None else "—") for k, v in row.items()}


@st.cache_data(ttl=3600)
def get_category_opportunity_scores() -> pd.DataFrame:
    """Avg opportunity score per category for the horizontal bar chart on Page 1."""
    return _run(f"""
        SELECT
            category_name,
            ROUND(AVG(overall_opportunity_score), 1) AS avg_score
        FROM `{P}.{D}.mart_action_queue`
        GROUP BY category_name
        ORDER BY avg_score DESC
    """)
