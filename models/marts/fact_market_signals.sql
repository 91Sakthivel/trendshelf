{{
    config(
        materialized = 'table',
        description  = 'Monthly market-signal fact table. Grain: reference_month × category × store. Spine is Kroger-anchored; FRED and BLS are joined latest-available-as-of to handle their 2-month reporting lag.'
    )
}}

/*
  Latest-available-as-of join strategy (BigQuery-compatible)
  ──────────────────────────────────────────────────────────
  BigQuery does not allow CTE self-references in JOIN ON predicates.
  Solution: pre-compute the month mapping in a separate CTE using the
  distinct spine months × source months, then join on the mapped value.

    fred_as_of  → spine_month → latest FRED month ≤ spine_month
    bls_as_of   → spine_month → latest BLS month  ≤ spine_month
    macro_as_of → spine_month → latest int_macro_trend_features month
*/

-- ── Spine: only months where Kroger data was actually collected ───────────────

with all_months as (

    select distinct
        DATE_TRUNC(DATE(collected_at), MONTH)       as reference_month
    from {{ ref('stg_kroger_prices') }}

),

retail_segments as (

    select distinct
        COALESCE(category, 'Unknown')               as category,
        store_id
    from {{ ref('stg_kroger_prices') }}
    where store_id is not null

),

-- ── Source aggregations ───────────────────────────────────────────────────────

kroger_monthly as (

    select
        DATE_TRUNC(DATE(collected_at), MONTH)       as reference_month,
        COALESCE(category, 'Unknown')               as category,
        store_id,
        AVG(price_regular)                          as retail_price
    from {{ ref('stg_kroger_prices') }}
    group by 1, 2, 3

),

fred as (

    select
        DATE_TRUNC(observation_date, MONTH)         as reference_month,
        ppi_value
    from {{ ref('stg_fred_ppi') }}

),

bls as (

    select
        reference_date                              as reference_month,
        cpi_value
    from {{ ref('stg_bls_cpi') }}
    where not is_suppressed

),

-- ── Full spine ────────────────────────────────────────────────────────────────

spine as (

    select
        m.reference_month,
        r.category,
        r.store_id
    from all_months m
    cross join retail_segments r

),

-- ── Pre-compute latest available month for each source ────────────────────────
-- Uses all_months (not the full spine) to keep the aggregations small.

fred_as_of as (

    select
        m.reference_month,
        MAX(f.reference_month)                      as fred_month
    from all_months m
    left join fred f on f.reference_month <= m.reference_month
    group by m.reference_month

),

bls_as_of as (

    select
        m.reference_month,
        MAX(b.reference_month)                      as bls_month
    from all_months m
    left join bls b on b.reference_month <= m.reference_month
    group by m.reference_month

),

macro_as_of as (

    select
        m.reference_month,
        MAX(mt.reference_month)                     as macro_month
    from all_months m
    left join {{ ref('int_macro_trend_features') }} mt
           on mt.reference_month <= m.reference_month
    group by m.reference_month

),

-- ── Final join ────────────────────────────────────────────────────────────────

final as (

    select
        TO_HEX(MD5(CONCAT(
            CAST(s.reference_month AS STRING), '||',
            s.category,                        '||',
            s.store_id
        )))                                                     as signal_id,

        TO_HEX(MD5(CAST(s.reference_month AS STRING)))          as date_key,
        TO_HEX(MD5(s.category))                                 as category_key,
        TO_HEX(MD5(s.store_id))                                 as location_key,
        TO_HEX(MD5('kroger'))                                   as source_key,

        -- ── Core metrics ─────────────────────────────────────────────────────
        k.retail_price,
        f.ppi_value,
        b.cpi_value,

        -- ── Macro trend features ──────────────────────────────────────────────
        mt.ppi_trend_direction,
        mt.cpi_trend_direction,

        -- macro_data_available: TRUE only when BOTH FRED and BLS resolved an as-of
        -- month for this spine month. Single combined flag, not per-source, because
        -- both sources come from the same collector run (collect_apis.py --mode
        -- prices, see docs/threshold_decisions.md #7.6) and a real outage takes both
        -- down together. See #7.20 for the full design.
        (fa.fred_month IS NOT NULL AND ba.bls_month IS NOT NULL)   as macro_data_available,

        -- macro_risk_flag: NULL when macro is absent — never a neutral default.
        -- The old ELSE 'Stable Macro' asserted an observed stability that didn't
        -- happen; it fired identically whether PPI/CPI were flat OR absent. See #7.20.
        CASE
            WHEN mt.ppi_trend_direction IS NULL AND mt.cpi_trend_direction IS NULL
                THEN NULL
            WHEN mt.ppi_trend_direction = 'Rising' AND mt.cpi_trend_direction = 'Rising'
                THEN 'High Inflation Risk'
            WHEN mt.ppi_trend_direction = 'Rising'
                THEN 'Cost Pressure'
            WHEN mt.ppi_trend_direction = 'Falling'
                THEN 'Cost Relief'
            ELSE 'Stable Macro'
        END                                                     as macro_risk_flag,

        mt.ppi_3mo_trend,
        mt.cpi_3mo_trend,
        mt.normalized_ppi_growth_score,
        mt.normalized_cpi_growth_score,

        -- ── Demand trend features ─────────────────────────────────────────────
        dt.trends_recent_4wk_avg                                as avg_search_interest,
        dt.google_trends_level_score,
        dt.google_trends_momentum_score,
        dt.google_trends_4wk_momentum,
        dt.demand_trend_direction,
        dt.seasonality_flag,
        dt.is_seasonal,
        dt.max_interest_12m,
        dt.min_interest_12m,
        dt.weeks_with_data,

        (retail_price IS NOT NULL)                              as has_kroger_data,

        CURRENT_TIMESTAMP()                                     as load_timestamp

    from spine s

    left join kroger_monthly k
           on s.reference_month = k.reference_month
          and s.category        = k.category
          and s.store_id        = k.store_id

    -- Resolve latest available FRED month, then join
    left join fred_as_of  fa on fa.reference_month = s.reference_month
    left join fred         f  on f.reference_month  = fa.fred_month

    -- Resolve latest available BLS month, then join
    left join bls_as_of   ba on ba.reference_month = s.reference_month
    left join bls          b  on b.reference_month  = ba.bls_month

    -- Resolve latest available macro trend snapshot, then join
    left join macro_as_of ma on ma.reference_month = s.reference_month
    left join {{ ref('int_macro_trend_features') }} mt
           on mt.reference_month = ma.macro_month

    -- Demand trend features: category-level snapshot
    left join {{ ref('int_demand_trend_features') }} dt
           on dt.category = s.category

)

select * from final
