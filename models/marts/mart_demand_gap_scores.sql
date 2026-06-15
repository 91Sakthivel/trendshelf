{{
    config(
        materialized = 'table',
        description  = 'Demand gap scoring: how much consumer interest exceeds current shelf supply. One row per month × category × store.'
    )
}}

/*
  Grain: same as fact_market_signals (reference_month × category × store).

  Scores (0-100, higher = bigger gap / more opportunity):
    category_momentum_score  — 80% Google Trends momentum + 20% macro inflation composite
    search_to_shelf_gap      — consumer intent vs. actual shelf availability
    phantom_distribution     — unmet demand where shelf coverage is weak
    intent_quality_score     — how consistent and well-covered the trends signal is
    overall_demand_gap_score — weighted composite

  Trend features flow from int_demand_trend_features → fact_market_signals → here.
  Macro features flow from int_macro_trend_features → fact_market_signals → here.
*/

-- ── Fact table joined with dimensions ────────────────────────────────────────

with signals as (

    select
        f.signal_id,
        f.date_key,
        f.category_key,
        f.location_key,
        f.source_key,
        f.retail_price,
        f.ppi_value,
        f.cpi_value,
        f.avg_search_interest,
        f.google_trends_level_score,
        f.google_trends_momentum_score,
        f.demand_trend_direction,
        f.max_interest_12m,
        f.min_interest_12m,
        f.weeks_with_data,
        f.normalized_ppi_growth_score,
        f.normalized_cpi_growth_score,
        f.ppi_trend_direction,
        f.cpi_trend_direction,
        f.load_timestamp,
        d.calendar_date                             as reference_month,
        c.category_name,
        l.store_id,
        l.state,
        l.region
    from {{ ref('fact_market_signals') }} f
    left join {{ ref('dim_date') }}     d on f.date_key     = d.date_key
    left join {{ ref('dim_category') }} c on f.category_key = c.category_key
    left join {{ ref('dim_location') }} l on f.location_key = l.location_key

),

-- ── Kroger shelf data (product count and promo depth by month) ────────────────

base as (

    select
        s.*,
        k.product_count,
        k.promo_depth_pct
    from signals s
    left join (
        select
            DATE_TRUNC(DATE(collected_at), MONTH)   as reference_month,
            store_id,
            COALESCE(category, 'Unknown')           as category_name,
            COUNT(distinct product_id)              as product_count,
            AVG(SAFE_DIVIDE(
                price_regular - COALESCE(price_promo, price_regular),
                price_regular
            )) * 100                                as promo_depth_pct
        from {{ ref('stg_kroger_prices') }}
        group by 1, 2, 3
    ) k on s.reference_month = k.reference_month
         and s.store_id       = k.store_id
         and s.category_name  = k.category_name

),

-- ── Individual scores ─────────────────────────────────────────────────────────

scored as (

    select
        signal_id,
        reference_month,
        category_name,
        store_id,
        state,
        region,

        -- ── 1. Category Momentum Score ────────────────────────────────────────
        -- 80%: Google Trends momentum (0-100, centered at 50 = no change)
        -- 20%: Macro inflation composite — average of CPI and PPI normalized scores
        --      (0-100, centered at 50 = stable prices)
        LEAST(100, GREATEST(0,
            COALESCE(google_trends_momentum_score, 50.0) * 0.80 +
            ((
                COALESCE(normalized_cpi_growth_score, 50.0) +
                COALESCE(normalized_ppi_growth_score, 50.0)
            ) / 2.0) * 0.20
        ))                                          as category_momentum_score,

        -- ── 2. Search-to-Shelf Gap Score ──────────────────────────────────────
        -- High search + few products on shelf = large gap = high score.
        -- Normalised against a baseline of 50 products (full coverage).
        LEAST(100, GREATEST(0,
            COALESCE(avg_search_interest, 0) *
            SAFE_DIVIDE(
                50.0,
                NULLIF(COALESCE(product_count, 1), 0)
            )
        ))                                          as search_to_shelf_gap,

        -- ── 3. Phantom Distribution Score ────────────────────────────────────
        -- Demand exists where shelf coverage is weak.
        -- NULL-guarded: returns NULL when product_count is unknown so downstream
        -- models don't inflate risk scores using a phantom 100% shelf gap.
        CASE
            WHEN product_count IS NULL THEN NULL
            ELSE LEAST(100, GREATEST(0,
                COALESCE(avg_search_interest, 0) *
                GREATEST(0.0,
                    1.0 - SAFE_DIVIDE(product_count, 50.0)
                )
            ))
        END                                         as phantom_distribution,

        CASE
            WHEN product_count IS NULL THEN 'MISSING'
            ELSE 'MEASURED'
        END                                         as phantom_signal_type,

        -- ── 4. Intent Quality Score ───────────────────────────────────────────
        -- 60%: Coverage — how many weeks of data vs expected 52 weeks
        -- 40%: Consistency — smaller 12-month peak-to-min range = more stable signal
        LEAST(100, GREATEST(0,
            SAFE_DIVIDE(COALESCE(weeks_with_data, 0), 52.0) * 60.0 +
            (1.0 - SAFE_DIVIDE(
                COALESCE(max_interest_12m, 0) - COALESCE(min_interest_12m, 0),
                100.0
            )) * 40.0
        ))                                          as intent_quality_score,

        -- raw inputs for downstream models
        COALESCE(avg_search_interest, 0)            as avg_search_interest,
        COALESCE(product_count, 0)                  as shelf_product_count,
        COALESCE(promo_depth_pct, 0)                as promo_depth_pct,
        retail_price,
        ppi_value,
        cpi_value,

        -- trend direction columns (for EDA and action queue)
        demand_trend_direction,
        ppi_trend_direction,
        cpi_trend_direction,

        'MEASURED'                                  as signal_type,
        'v4_statistical_calibration'                as score_version,
        CASE
            WHEN avg_search_interest IS NULL
                THEN 'No Google Trends data for this category'
            WHEN product_count IS NULL
                THEN 'No Kroger shelf data for this month; phantom_distribution set to NULL'
            ELSE 'All signals present and measured'
        END                                         as data_note,
        load_timestamp

    from base

)

-- ── Final composite score ─────────────────────────────────────────────────────

select
    signal_id,
    reference_month,
    category_name,
    store_id,
    state,
    region,

    ROUND(category_momentum_score, 2)               as category_momentum_score,
    ROUND(search_to_shelf_gap, 2)                   as search_to_shelf_gap,
    ROUND(phantom_distribution, 2)                  as phantom_distribution,
    ROUND(intent_quality_score, 2)                  as intent_quality_score,

    ROUND(LEAST(100, GREATEST(0,
        category_momentum_score * 0.25 +
        search_to_shelf_gap     * 0.40 +
        COALESCE(phantom_distribution, 0) * 0.15 +
        intent_quality_score    * 0.20
    )), 2)                                          as overall_demand_gap_score,

    avg_search_interest,
    shelf_product_count,
    promo_depth_pct,
    retail_price,
    ppi_value,
    cpi_value,

    demand_trend_direction,
    ppi_trend_direction,
    cpi_trend_direction,

    phantom_signal_type,
    signal_type,
    score_version,
    data_note,
    load_timestamp

from scored
order by reference_month desc, overall_demand_gap_score desc
