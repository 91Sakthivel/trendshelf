{{
    config(
        materialized = 'table',
        description  = 'Data quality and signal confidence layer. Scores how much to trust each month\'s analysis. One row per month × category × store.'
    )
}}

/*
  Grain: reference_month × category × store (mirrors fact_market_signals).

  5 expected sources: Google Trends, Kroger, FRED PPI, BLS CPI, SerpAPI.

  Confidence formula (v3):
    data_completeness_score         × 0.30  — binary source presence (5×20 pts)
    signal_agreement_score          × 0.25  — do signals tell a consistent story?
    data_freshness_score            × 0.20  — weighted staleness of each source
    row_level_source_coverage_score × 0.25  — weighted per-row source coverage

  Confidence levels:
    HIGH   >= 75
    MEDIUM  50-74
    LOW    < 50
*/

with demand as (

    select * from {{ ref('mart_demand_gap_scores') }}

),

risk as (

    select
        signal_id,
        missed_demand_risk,
        demand_decay_risk,
        overall_risk_score,
        competitor_avg_price
    from {{ ref('mart_shelfrisk_scores') }}

),

price as (

    select
        signal_id,
        price_position_score,
        margin_pressure_risk,
        overall_margin_risk_score,
        cost_passthrough_rate
    from {{ ref('mart_price_margin_scores') }}

),

-- ── Latest collection timestamps per source ───────────────────────────────────

source_freshness as (

    select
        'google_trends'                             as source_name,
        MAX(collected_at)                           as latest_collected_at,
        COUNT(distinct trend_date)                  as total_rows
    from {{ ref('stg_google_trends') }}

    union all

    select 'fred_ppi', MAX(collected_at), COUNT(*)
    from {{ ref('stg_fred_ppi') }}

    union all

    select 'bls_cpi', MAX(collected_at), COUNT(*)
    from {{ ref('stg_bls_cpi') }}

    union all

    select 'kroger_prices', MAX(collected_at), COUNT(*)
    from {{ ref('stg_kroger_prices') }}

    union all

    select 'serpapi_prices', MAX(collected_at), COUNT(*)
    from {{ ref('stg_serpapi_prices') }}

),

freshness_summary as (

    select
        MAX(CASE WHEN source_name = 'google_trends'   THEN latest_collected_at END)  as trends_last_collected,
        MAX(CASE WHEN source_name = 'fred_ppi'        THEN latest_collected_at END)  as fred_last_collected,
        MAX(CASE WHEN source_name = 'bls_cpi'         THEN latest_collected_at END)  as bls_last_collected,
        MAX(CASE WHEN source_name = 'kroger_prices'   THEN latest_collected_at END)  as kroger_last_collected,
        MAX(CASE WHEN source_name = 'serpapi_prices'  THEN latest_collected_at END)  as serpapi_last_collected,
        MAX(CASE WHEN source_name = 'google_trends'   THEN total_rows END)           as trends_row_count,
        MAX(CASE WHEN source_name = 'fred_ppi'        THEN total_rows END)           as fred_row_count,
        MAX(CASE WHEN source_name = 'bls_cpi'         THEN total_rows END)           as bls_row_count,
        MAX(CASE WHEN source_name = 'kroger_prices'   THEN total_rows END)           as kroger_row_count,
        MAX(CASE WHEN source_name = 'serpapi_prices'  THEN total_rows END)           as serpapi_row_count
    from source_freshness

),

-- ── Base join ─────────────────────────────────────────────────────────────────

base as (

    select
        d.signal_id,
        d.reference_month,
        d.category_name,
        d.store_id,
        d.state,
        d.region,

        d.avg_search_interest,
        d.shelf_product_count,
        d.retail_price,
        d.ppi_value,
        d.cpi_value,
        d.overall_demand_gap_score,
        d.signal_type,
        d.load_timestamp,

        r.missed_demand_risk,
        r.demand_decay_risk,
        r.overall_risk_score,
        r.competitor_avg_price,

        p.price_position_score,
        p.margin_pressure_risk,
        p.overall_margin_risk_score,
        p.cost_passthrough_rate,

        f.trends_last_collected,
        f.fred_last_collected,
        f.bls_last_collected,
        f.kroger_last_collected,
        f.serpapi_last_collected,
        f.trends_row_count,
        f.fred_row_count,
        f.bls_row_count,
        f.kroger_row_count,
        f.serpapi_row_count

    from demand d
    left join risk          r on d.signal_id = r.signal_id
    left join price         p on d.signal_id = p.signal_id
    cross join freshness_summary f

),

scored as (

    select
        signal_id,
        reference_month,
        category_name,
        store_id,
        state,
        region,

        -- ── 1. Data Completeness Score ────────────────────────────────────────
        -- 5 expected sources × 20 points each = 100 max
        -- SerpAPI credit is per-row: only awarded when this signal has an actual
        -- competitor price match.
        LEAST(100, GREATEST(0,
            CASE WHEN avg_search_interest > 0          THEN 20 ELSE 0 END +
            CASE WHEN retail_price IS NOT NULL          THEN 20 ELSE 0 END +
            CASE WHEN ppi_value IS NOT NULL             THEN 20 ELSE 0 END +
            CASE WHEN cpi_value IS NOT NULL             THEN 20 ELSE 0 END +
            CASE WHEN competitor_avg_price IS NOT NULL  THEN 20 ELSE 0 END
        ))                                              as data_completeness_score,

        -- ── 2. Signal Agreement Score ─────────────────────────────────────────
        LEAST(100, GREATEST(0,
            CASE
                WHEN overall_demand_gap_score >= 50 AND overall_risk_score >= 40 THEN 85
                WHEN overall_demand_gap_score >= 30 AND overall_risk_score >= 25 THEN 65
                WHEN ABS(overall_demand_gap_score - (100 - overall_risk_score)) > 50 THEN 35
                ELSE 50
            END
        ))                                              as signal_agreement_score,

        -- ── 3. Data Freshness Score ───────────────────────────────────────────
        -- 5-source weighted freshness. Weights: Kroger 25% | Trends 20% | FRED 20% | BLS 20% | SerpAPI 15%
        LEAST(100, GREATEST(0,
            CASE
                WHEN kroger_last_collected IS NULL THEN 0
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), kroger_last_collected, HOUR) <= 48   THEN 100
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), kroger_last_collected, HOUR) <= 168  THEN 70
                ELSE 30
            END * 0.25 +

            CASE
                WHEN trends_last_collected IS NULL THEN 0
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), trends_last_collected, HOUR) <= 336  THEN 100
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), trends_last_collected, HOUR) <= 720  THEN 70
                ELSE 30
            END * 0.20 +

            CASE
                WHEN fred_last_collected IS NULL THEN 0
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), fred_last_collected, HOUR) <= 1080   THEN 100
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), fred_last_collected, HOUR) <= 2160   THEN 70
                ELSE 30
            END * 0.20 +

            CASE
                WHEN bls_last_collected IS NULL THEN 0
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), bls_last_collected, HOUR) <= 1080    THEN 100
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), bls_last_collected, HOUR) <= 2160    THEN 70
                ELSE 30
            END * 0.20 +

            CASE
                WHEN serpapi_last_collected IS NULL THEN 0
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), serpapi_last_collected, HOUR) <= 336 THEN 100
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), serpapi_last_collected, HOUR) <= 720 THEN 70
                ELSE 30
            END * 0.15
        ))                                              as data_freshness_score,

        -- ── 4. Row-Level Source Coverage Score ────────────────────────────────
        -- Weighted by data value to the retail prediction model:
        --   Kroger 35 pts: anchors retail price and shelf context
        --   Trends 25 pts: consumer intent signal
        --   FRED/BLS 25 pts: macro context (both required together)
        --   SerpAPI 15 pts: competitive pricing context
        LEAST(100, GREATEST(0,
            CASE WHEN retail_price IS NOT NULL          THEN 35 ELSE 0 END +
            CASE WHEN avg_search_interest > 0           THEN 25 ELSE 0 END +
            CASE WHEN ppi_value IS NOT NULL
              AND cpi_value IS NOT NULL                 THEN 25 ELSE 0 END +
            CASE WHEN competitor_avg_price IS NOT NULL  THEN 15 ELSE 0 END
        ))                                              as row_level_source_coverage_score,

        -- ── 5. Source Count (out of 5) ────────────────────────────────────────
        (CASE WHEN avg_search_interest > 0          THEN 1 ELSE 0 END +
         CASE WHEN retail_price IS NOT NULL          THEN 1 ELSE 0 END +
         CASE WHEN ppi_value IS NOT NULL             THEN 1 ELSE 0 END +
         CASE WHEN cpi_value IS NOT NULL             THEN 1 ELSE 0 END +
         CASE WHEN competitor_avg_price IS NOT NULL  THEN 1 ELSE 0 END
        )                                             as source_count,

        -- raw pass-through
        avg_search_interest,
        retail_price,
        ppi_value,
        cpi_value,
        competitor_avg_price,
        overall_demand_gap_score,
        overall_risk_score,
        overall_margin_risk_score,
        price_position_score,
        cost_passthrough_rate,
        signal_type,

        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), kroger_last_collected,  HOUR) as kroger_hours_ago,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), trends_last_collected,  HOUR) as trends_hours_ago,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), fred_last_collected,    HOUR) as fred_hours_ago,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), bls_last_collected,     HOUR) as bls_hours_ago,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), serpapi_last_collected, HOUR) as serpapi_hours_ago,

        trends_row_count,
        fred_row_count,
        bls_row_count,
        kroger_row_count,
        serpapi_row_count,

        load_timestamp

    from base

),

-- ── Composite + reason codes ──────────────────────────────────────────────────

final as (

    select
        signal_id,
        reference_month,
        category_name,
        store_id,
        state,
        region,

        ROUND(data_completeness_score,          2)  as data_completeness_score,
        ROUND(signal_agreement_score,           2)  as signal_agreement_score,
        ROUND(data_freshness_score,             2)  as data_freshness_score,
        ROUND(row_level_source_coverage_score,  2)  as row_level_source_coverage_score,
        source_count,

        -- v3 formula: 4 weighted components
        ROUND(LEAST(100, GREATEST(0,
            data_completeness_score         * 0.30 +
            signal_agreement_score          * 0.25 +
            data_freshness_score            * 0.20 +
            row_level_source_coverage_score * 0.25
        )), 2)                                      as overall_confidence_score,

        overall_demand_gap_score,
        overall_risk_score,
        overall_margin_risk_score,
        price_position_score,
        cost_passthrough_rate,
        competitor_avg_price,
        signal_type,
        'v3_trend_features'                         as score_version,

        kroger_hours_ago,
        trends_hours_ago,
        fred_hours_ago,
        bls_hours_ago,
        serpapi_hours_ago,
        trends_row_count,
        fred_row_count,
        bls_row_count,
        kroger_row_count,
        serpapi_row_count,

        ARRAY_CONCAT(
            CASE WHEN avg_search_interest = 0 OR avg_search_interest IS NULL
                 THEN ['NO_SEARCH_SIGNAL: Google Trends data absent for this category']
                 ELSE [] END,
            CASE WHEN retail_price IS NULL
                 THEN ['NO_RETAIL_PRICE: Kroger price not collected for this month']
                 ELSE [] END,
            CASE WHEN ppi_value IS NULL
                 THEN ['NO_PPI_DATA: FRED PPI absent — no data available yet as-of this month']
                 ELSE [] END,
            CASE WHEN cpi_value IS NULL
                 THEN ['NO_CPI_DATA: BLS CPI suppressed or absent as-of this month']
                 ELSE [] END,
            CASE WHEN serpapi_hours_ago IS NULL
                 THEN ['NO_SERPAPI_DATA: Competitor pricing not yet collected']
                 ELSE [] END,
            CASE WHEN kroger_hours_ago > 168
                 THEN ['STALE_KROGER: Kroger data more than 7 days old']
                 ELSE [] END,
            CASE WHEN trends_hours_ago > 720
                 THEN ['STALE_TRENDS: Google Trends data more than 30 days old']
                 ELSE [] END,
            CASE WHEN serpapi_hours_ago > 336
                 THEN ['STALE_SERPAPI: Competitor pricing data more than 14 days old']
                 ELSE [] END,
            CASE WHEN ABS(overall_demand_gap_score - (100 - overall_risk_score)) > 50
                 THEN ['SIGNAL_CONFLICT: Demand and risk signals point in opposite directions']
                 ELSE [] END,
            CASE WHEN source_count = 5
                 THEN ['FULL_COVERAGE: All 5 data sources present']
                 ELSE [] END
        )                                           as reason_codes,

        load_timestamp

    from scored

)

select
    *,
    CASE
        WHEN overall_confidence_score >= {{ var('confidence_high') }}   THEN 'HIGH'
        WHEN overall_confidence_score >= {{ var('confidence_medium') }} THEN 'MEDIUM'
        ELSE 'LOW'
    END                                             as confidence_level
from final
order by reference_month desc, overall_confidence_score desc
