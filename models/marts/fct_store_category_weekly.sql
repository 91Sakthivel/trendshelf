{{
    config(
        materialized = 'table',
        description  = 'Temporal fact table: Kroger vs Walmart prices per store × category × collection date. ALL dates preserved — temporal foundation for price trend analysis. Grain: kroger_collection_date × store_id × category_name.'
    )
}}

/*
  Grain: kroger_collection_date × store_id × category_name.
  One row per (date, store, category) — no latest-only filter.
  Opposite of mart_pricing_intelligence which pins to the latest partition.

  Outlier exclusion: same >5× category median logic as mart_pricing_intelligence,
  but threshold is computed per-date so each collection period is self-contained.

  SerpAPI carry-forward: for each Kroger collection date, the most recent Walmart
  pull on or before that date is used. This is forward-compatible with future
  twice-weekly --mode kroger runs where Kroger may be ahead of SerpAPI.
*/

-- ── CTE 1: Distinct Kroger collection dates ───────────────────────────────────

with kroger_dates as (

    select distinct DATE(collected_at) as kroger_collection_date
    from {{ ref('stg_kroger_prices') }}

),

-- ── CTE 2: Category-level medians per Kroger date ─────────────────────────────
-- Outlier-exclusion threshold per date — keeps each period self-contained.

category_medians_by_date as (

    select
        DATE(collected_at)                                          as kroger_collection_date,
        COALESCE(category, 'Unknown')                               as category_name,
        APPROX_QUANTILES(price_regular, 100)[OFFSET(50)]            as cat_median
    from {{ ref('stg_kroger_prices') }}
    where price_regular is not null
    group by 1, 2

),

-- ── CTE 3: Category CV per date (drives CV-calibrated price_position band) ───

category_cv_by_date as (

    select
        DATE(k.collected_at)                                        as kroger_collection_date,
        COALESCE(k.category, 'Unknown')                             as category_name,
        ROUND(
            SAFE_DIVIDE(STDDEV(k.price_regular), AVG(k.price_regular)) * 100,
        1)                                                          as category_cv_pct
    from {{ ref('stg_kroger_prices') }} k
    join category_medians_by_date cm
      on DATE(k.collected_at) = cm.kroger_collection_date
     and COALESCE(k.category, 'Unknown') = cm.category_name
    where k.price_regular is not null
      and k.price_regular <= 5 * cm.cat_median
    group by 1, 2

),

-- ── CTE 4: SerpAPI as-of date per Kroger collection date (carry-forward) ─────
-- For each Kroger date, the most recent Walmart pull on or before that date.

serpapi_asof_by_date as (

    select
        kd.kroger_collection_date,
        MAX(DATE(s.collected_at))                                   as competitor_asof_date
    from kroger_dates kd
    join {{ ref('stg_serpapi_prices') }} s
      on DATE(s.collected_at) <= kd.kroger_collection_date
    where s.competitor_price is not null
    group by 1

),

-- ── CTE 5: Competitor median per as-of date × category ────────────────────────

competitor_by_date_category as (

    select
        DATE(collected_at)                                          as serpapi_date,
        category,
        ROUND(APPROX_QUANTILES(competitor_price, 100)[OFFSET(50)], 4)
                                                                    as competitor_median_price,
        COUNT(*)                                                    as competitor_product_count
    from {{ ref('stg_serpapi_prices') }}
    where competitor_price is not null
    group by 1, 2

),

-- ── CTE 6: Kroger median per store × category × date, outlier-excluded ────────

kroger_by_store_cat_date as (

    select
        DATE(k.collected_at)                                        as kroger_collection_date,
        k.store_id,
        COALESCE(k.category, 'Unknown')                             as category_name,
        ROUND(APPROX_QUANTILES(
            IF(k.price_regular <= 5 * cm.cat_median, k.price_regular, NULL),
            100
        )[OFFSET(50)], 4)                                           as kroger_median_price,
        COUNT(DISTINCT IF(k.price_regular <= 5 * cm.cat_median, k.product_id, NULL))
                                                                    as kroger_product_count
    from {{ ref('stg_kroger_prices') }} k
    join category_medians_by_date cm
      on DATE(k.collected_at) = cm.kroger_collection_date
     and COALESCE(k.category, 'Unknown') = cm.category_name
    where k.price_regular is not null
    group by 1, 2, 3

)

-- ── Final: join all sources ───────────────────────────────────────────────────

select
    k.kroger_collection_date,
    k.store_id,
    k.category_name,

    -- Kroger
    k.kroger_median_price,
    k.kroger_product_count,

    -- Competitor (SerpAPI carry-forward)
    'Walmart DFW'                                                   as competitor_name,
    sa.competitor_asof_date,
    DATE_DIFF(k.kroger_collection_date, sa.competitor_asof_date, DAY)
                                                                    as competitor_staleness_days,
    comp.competitor_median_price,
    COALESCE(comp.competitor_product_count, 0)                      as competitor_product_count,

    -- Price gap: NULL propagates honestly when either price is missing
    CASE
        WHEN k.kroger_median_price IS NULL OR comp.competitor_median_price IS NULL THEN NULL
        ELSE ROUND(SAFE_DIVIDE(
            k.kroger_median_price - comp.competitor_median_price,
            NULLIF(comp.competitor_median_price, 0)
        ) * 100, 2)
    END                                                             as price_gap_pct,

    -- price_gap_direction: simple above/below label (no fair band — use price_position for banded)
    CASE
        WHEN k.kroger_median_price IS NULL OR comp.competitor_median_price IS NULL THEN 'Unknown'
        WHEN k.kroger_median_price > comp.competitor_median_price   THEN 'Overpriced'
        ELSE                                                             'Underpriced'
    END                                                             as price_gap_direction,

    -- Reliability gate: mirrors mart_pricing_intelligence logic
    CASE
        WHEN comp.competitor_median_price IS NULL
          OR k.kroger_median_price IS NULL                          THEN 'Unknown'
        WHEN COALESCE(comp.competitor_product_count, 0)
             < {{ var('reliability_min_competitor_count') }}         THEN 'Low'
        WHEN ABS(ROUND(SAFE_DIVIDE(
                k.kroger_median_price - comp.competitor_median_price,
                NULLIF(comp.competitor_median_price, 0)
             ) * 100, 2))
             > {{ var('reliability_low_gap_threshold') }}            THEN 'Low'
        WHEN ABS(ROUND(SAFE_DIVIDE(
                k.kroger_median_price - comp.competitor_median_price,
                NULLIF(comp.competitor_median_price, 0)
             ) * 100, 2))
             > {{ var('reliability_medium_gap_threshold') }}         THEN 'Medium'
        ELSE 'High'
    END                                                             as competitor_reliability,

    -- price_position: CV-calibrated band (same formula as mart_pricing_intelligence)
    CASE
        WHEN k.kroger_median_price IS NULL OR comp.competitor_median_price IS NULL
            THEN 'Unknown'
        WHEN ROUND(SAFE_DIVIDE(
                k.kroger_median_price - comp.competitor_median_price,
                NULLIF(comp.competitor_median_price, 0)
             ) * 100, 2)
             > GREATEST({{ var('min_price_gap_threshold') }}, LEAST({{ var('max_price_gap_threshold') }},
                 COALESCE(cv.category_cv_pct, 30.0) * {{ var('cv_multiplier') }}
             ))                                                      THEN 'Overpriced'
        WHEN ROUND(SAFE_DIVIDE(
                k.kroger_median_price - comp.competitor_median_price,
                NULLIF(comp.competitor_median_price, 0)
             ) * 100, 2)
             < -GREATEST({{ var('min_price_gap_threshold') }}, LEAST({{ var('max_price_gap_threshold') }},
                 COALESCE(cv.category_cv_pct, 30.0) * {{ var('cv_multiplier') }}
             ))                                                      THEN 'Underpriced'
        ELSE 'Fair'
    END                                                             as price_position,

    -- basket_mismatch_flag: TRUE when gap magnitude exceeds plausible comparison threshold
    CASE
        WHEN k.kroger_median_price IS NULL OR comp.competitor_median_price IS NULL THEN FALSE
        WHEN ABS(ROUND(SAFE_DIVIDE(
                k.kroger_median_price - comp.competitor_median_price,
                NULLIF(comp.competitor_median_price, 0)
             ) * 100, 2))
             > {{ var('reliability_low_gap_threshold') }}            THEN TRUE
        ELSE FALSE
    END                                                             as basket_mismatch_flag

from kroger_by_store_cat_date k
left join serpapi_asof_by_date sa
  on k.kroger_collection_date = sa.kroger_collection_date
left join competitor_by_date_category comp
  on sa.competitor_asof_date  = comp.serpapi_date
 and k.category_name          = comp.category
left join category_cv_by_date cv
  on k.kroger_collection_date = cv.kroger_collection_date
 and k.category_name          = cv.category_name
