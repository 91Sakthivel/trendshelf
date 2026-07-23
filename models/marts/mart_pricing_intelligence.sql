{{
    config(
        materialized = 'table',
        description  = 'Full pricing intelligence engine: Kroger vs Walmart DFW per store × category, with elasticity-adjusted action cascade and plain-English reasons. Score version: v4_statistical_calibration.'
    )
}}

/*
  Grain: reference_month × category × store (mirrors fact_market_signals).

  Intelligence layers:
    1. Category elasticity prior — industry knowledge; replaced by data-derived elasticity
       when 6+ months of collection accumulates.
    2. Competitor prices by category — Walmart DFW store 2105 via SerpAPI, grouped per
       category. Median used since v4 to reduce sensitivity to pack-size outliers.
    3. Kroger median price per store × category — outliers >5× category median excluded.
    4. Scoring inputs from marts (demand gap, shelf risk, price margin, confidence).
    5. Markdown safety, pricing power, demand signal, price gap confidence.
    6. Action cascade (8 levels, first match wins).

  Score version: v4_statistical_calibration
    vs v3_category_prices:
      - price_gap_pct: NULL propagates honestly (no COALESCE-to-0 false gaps)
      - kroger/competitor prices: median replaces mean (outlier-robust)
      - price_position bands: CV-calibrated per category (replaces fixed ±10%)
      - price_gap_confidence_weight: smooth saturation curve + private label penalty
      - kroger_private_label_share: new output column for dashboard transparency
      - price_position_threshold / category_cv_pct: new output columns
*/

-- ── CTE 1: Category elasticity prior ─────────────────────────────────────────

with category_elasticity as (

    select * from UNNEST([
        STRUCT('beverages'        as category, 'Low'    as elasticity_tier, 70 as premium_tolerance_score),
        STRUCT('snacks'           as category, 'Medium' as elasticity_tier, 55 as premium_tolerance_score),
        STRUCT('dairy'            as category, 'High'   as elasticity_tier, 30 as premium_tolerance_score),
        STRUCT('frozen foods'     as category, 'High'   as elasticity_tier, 35 as premium_tolerance_score),
        STRUCT('breakfast cereal' as category, 'Medium' as elasticity_tier, 55 as premium_tolerance_score),
        STRUCT('meat seafood'     as category, 'High'   as elasticity_tier, 30 as premium_tolerance_score),
        STRUCT('produce'          as category, 'High'   as elasticity_tier, 25 as premium_tolerance_score),
        STRUCT('personal care'    as category, 'Low'    as elasticity_tier, 75 as premium_tolerance_score),
        STRUCT('household'        as category, 'High'   as elasticity_tier, 35 as premium_tolerance_score),
        STRUCT('coffee tea'       as category, 'Low'    as elasticity_tier, 80 as premium_tolerance_score)
    ])

),

-- ── Anchor: latest collection dates ──────────────────────────────────────────
-- All Kroger and SerpAPI reads pin to these so medians are single-date, not blended.
-- serpapi_asof carries forward the most recent Walmart pull on or before the Kroger date,
-- which keeps the mart correct when --mode kroger eventually pushes Kroger ahead of SerpAPI.

latest_dates as (

    -- Anchor to the latest Kroger date that ALSO has competitor (SerpAPI) data,
    -- so incomplete/Kroger-only partitions (e.g. an off-cadence manual run) are
    -- never scored. Protects against partial partitions generally, not just one date.
    select MAX(DATE(k.collected_at)) as kroger_date
    from {{ ref('stg_kroger_prices') }} k
    where DATE(k.collected_at) in (
        select DATE(collected_at) from {{ ref('stg_serpapi_prices') }}
    )

),

serpapi_asof as (

    select MAX(DATE(s.collected_at)) as serpapi_date
    from {{ ref('stg_serpapi_prices') }} s
    cross join latest_dates ld
    where DATE(s.collected_at) <= ld.kroger_date

),

-- ── CTE 2: Category medians — used as outlier-exclusion threshold ─────────────
-- Computed from all non-null rows. Products priced >5× this threshold are excluded
-- from per-store aggregations so that e.g. espresso machines don't skew coffee tea.

category_medians as (

    select
        COALESCE(category, 'Unknown')                           as category_name,
        APPROX_QUANTILES(price_regular, 100)[OFFSET(50)]        as cat_median
    from {{ ref('stg_kroger_prices') }}
    cross join latest_dates ld
    where price_regular is not null
      and DATE(collected_at) = ld.kroger_date
    group by 1

),

-- ── CTE 3: Category dispersion (post-outlier CV) ──────────────────────────────
-- Coefficient of variation after excluding extreme outliers.
-- Drives self-calibrating price_position threshold in scored CTE.

category_dispersion as (

    select
        COALESCE(k.category, 'Unknown')                         as category_name,
        ROUND(
            SAFE_DIVIDE(STDDEV(k.price_regular), AVG(k.price_regular)) * 100,
        1)                                                      as category_cv_pct
    from {{ ref('stg_kroger_prices') }} k
    cross join latest_dates ld
    join category_medians cm
      on COALESCE(k.category, 'Unknown') = cm.category_name
    where k.price_regular is not null
      and k.price_regular <= 5 * cm.cat_median
      and DATE(k.collected_at) = ld.kroger_date
    group by 1

),

-- ── Scoring inputs from existing marts ────────────────────────────────────────

demand as (

    select
        signal_id,
        reference_month,
        category_name,
        store_id,
        state,
        region,
        retail_price,
        overall_demand_gap_score,
        category_momentum_score,
        intent_quality_score,
        load_timestamp
    from {{ ref('mart_demand_gap_scores') }}

),

risk as (

    select
        signal_id,
        competitive_threat_risk,
        demand_decay_risk
    from {{ ref('mart_shelfrisk_scores') }}

),

price as (

    select
        signal_id,
        margin_pressure_risk,
        promo_risk_score
    from {{ ref('mart_price_margin_scores') }}

),

confidence as (

    select
        signal_id,
        overall_confidence_score
    from {{ ref('mart_confidence_layer') }}

),

-- ── Dimension keys ────────────────────────────────────────────────────────────

category_dim as (

    select category_key, category_name
    from {{ ref('dim_category') }}

),

location_dim as (

    select location_key, store_id, city as store_city
    from {{ ref('dim_location') }}

),

-- ── Temporal features: pinned to latest Kroger date ───────────────────────────
-- Provides lag, direction stability, volatility, and directional eligibility
-- for the snapshot mart. Filtered here to match the latest-partition grain.

temporal_features as (

    select *
    from {{ ref('int_pricing_temporal_features') }}
    where kroger_collection_date = (select kroger_date from latest_dates)

),

-- ── CTE 4: Competitor VALUE-ANCHOR prices by category ─────────────────────────
-- Walmart DFW store 2105 (mass-merchant EDLP). Median since v4.
-- NOTE: Walmart is a value-anchor / price-FLOOR, NOT a same-format peer to
-- Kroger (conventional supermarket). It systematically biases Kroger toward
-- 'Overpriced' by format, not mispricing. competitor_relevance_level scales
-- this per category; true same-format peers (Tom Thumb/H-E-B) are roadmap.

competitor_by_category as (

    select
        category,
        ROUND(APPROX_QUANTILES(competitor_price, 100)[OFFSET(50)], 4)
                                                                as competitor_avg_price, -- holds MEDIAN since v4 (column name kept for compatibility)
        COUNT(*)                                                as competitor_product_count,
        MAX(DATE(collected_at))                                 as competitor_price_asof_date
    from {{ ref('stg_serpapi_prices') }}
    cross join serpapi_asof sa
    where competitor_price is not null
      and DATE(collected_at) = sa.serpapi_date
    group by category

),

-- ── CTE 5: Kroger prices by store × category ──────────────────────────────────
-- Median since v4. Outlier exclusion uses IF() so kroger_outliers_excluded
-- correctly counts excluded rows without being hidden by the WHERE clause.
-- Private label share: proportion of in-scope SKUs branded Kroger/Simple Truth/Private Selection.

kroger_by_store_category as (

    select
        k.store_id,
        COALESCE(k.category, 'Unknown')                         as category_name,
        ROUND(APPROX_QUANTILES(
            IF(k.price_regular <= 5 * cm.cat_median, k.price_regular, NULL),
            100
        )[OFFSET(50)], 4)                                       as kroger_avg_price, -- holds MEDIAN since v4 (column name kept for compatibility)
        COUNT(distinct IF(k.price_regular <= 5 * cm.cat_median, k.product_id, NULL))
                                                                as kroger_product_count,
        COUNTIF(k.price_regular > 5 * cm.cat_median)           as kroger_outliers_excluded,
        ROUND(
            COUNTIF(
                k.price_regular <= 5 * cm.cat_median
                AND (
                    STARTS_WITH(k.description, 'Kroger')
                 OR STARTS_WITH(k.description, 'Simple Truth')
                 OR STARTS_WITH(k.description, 'Private Selection')
                )
            )
            / NULLIF(COUNTIF(k.price_regular <= 5 * cm.cat_median), 0),
        3)                                                      as kroger_private_label_share,

        -- Promo signal: DIAGNOSTIC only — not wired into price_gap_pct, price_position,
        -- or the action cascade. Regular-price scoring unchanged. Future phase.
        ROUND(APPROX_QUANTILES(
            IF(k.price_regular <= 5 * cm.cat_median,
               COALESCE(k.price_promo, k.price_regular), NULL),
            100
        )[OFFSET(50)], 4)                                       as kroger_effective_price,
        ROUND(SAFE_DIVIDE(
            COUNTIF(k.price_promo IS NOT NULL
                    AND k.price_promo < k.price_regular
                    AND k.price_regular <= 5 * cm.cat_median),
            NULLIF(COUNTIF(k.price_regular <= 5 * cm.cat_median), 0)
        ), 3)                                                   as kroger_promo_share,

        MAX(DATE(k.collected_at))                               as kroger_collection_date
    from {{ ref('stg_kroger_prices') }} k
    cross join latest_dates ld
    join category_medians cm
      on COALESCE(k.category, 'Unknown') = cm.category_name
    where k.price_regular is not null
      and DATE(k.collected_at) = ld.kroger_date
    group by 1, 2

),

-- ── CTE 6: Kroger unit prices by store × category ─────────────────────────────
-- Same 5× outlier gate as kroger_by_store_category; additionally requires
-- unit_parse_ok so only successfully parsed rows contribute to the median.
-- competitor unit comparison NOT implemented: SerpAPI price_per_unit is NULL and
-- price_per_unit_str mixes non-harmonized units ($/fl oz, $/oz, $/count) within
-- the same category — medians across incommensurable denominators are invalid.

kroger_unit_by_store_category as (

    select
        k.store_id,
        COALESCE(k.category, 'Unknown')                         as category_name,
        ROUND(APPROX_QUANTILES(
            IF(k.unit_parse_ok AND k.price_regular <= 5 * cm.cat_median,
               k.kroger_unit_price_raw, NULL),
            100
        )[OFFSET(50)], 4)                                       as kroger_unit_price_median,
        ROUND(
            100 * SAFE_DIVIDE(COUNTIF(k.unit_parse_ok), COUNT(*)),
        2)                                                       as kroger_unit_price_coverage_pct,
        APPROX_TOP_COUNT(
            IF(k.unit_parse_ok, k.size_unit, NULL), 1
        )[SAFE_OFFSET(0)].value                                  as kroger_unit_price_unit
    from {{ ref('int_kroger_unit_price') }} k
    cross join latest_dates ld
    join category_medians cm
      on COALESCE(k.category, 'Unknown') = cm.category_name
    where DATE(k.collected_at) = ld.kroger_date
    group by 1, 2

),

-- ── Join all sources at signal grain ──────────────────────────────────────────

base as (

    select
        d.signal_id,
        d.reference_month,
        d.category_name,
        d.store_id,
        d.state,
        d.region,
        d.load_timestamp,

        cat.category_key,
        loc.location_key,
        loc.store_city,

        -- Kroger price: prefer fresh aggregation; fall back to fact_market_signals retail_price
        COALESCE(k.kroger_avg_price, d.retail_price)            as kroger_avg_price,
        COALESCE(k.kroger_product_count, 0)                     as kroger_product_count,
        COALESCE(k.kroger_outliers_excluded, 0)                 as kroger_outliers_excluded,
        COALESCE(k.kroger_private_label_share, 0)               as kroger_private_label_share,
        k.kroger_effective_price,
        COALESCE(k.kroger_promo_share, 0)                       as kroger_promo_share,

        -- Kroger unit price (NULL when category parse coverage is zero)
        ku.kroger_unit_price_median,
        ku.kroger_unit_price_coverage_pct,
        ku.kroger_unit_price_unit,

        -- Category-level Walmart price (NULL when SerpAPI has no data for this category)
        comp.competitor_avg_price,
        COALESCE(comp.competitor_product_count, 0)              as competitor_product_count,
        k.kroger_collection_date,
        comp.competitor_price_asof_date,

        -- Category dispersion from post-outlier CV
        cd.category_cv_pct,

        -- Mart scores (raw; COALESCEd in scored CTE)
        d.overall_demand_gap_score,
        d.category_momentum_score,
        d.intent_quality_score,
        r.competitive_threat_risk,
        r.demand_decay_risk,
        p.margin_pressure_risk,
        p.promo_risk_score,
        c.overall_confidence_score,

        -- Elasticity prior
        COALESCE(e.elasticity_tier,           'Medium')         as elasticity_tier,
        COALESCE(e.premium_tolerance_score,    50)              as premium_tolerance_score,

        -- Temporal features (NULL on first collection; populated from 2nd date onward)
        tf.previous_price_gap_pct,
        tf.previous_gap_direction,
        tf.gap_direction_stable,
        tf.collection_count,
        tf.stable_direction_count,
        tf.price_gap_change_pct,
        tf.price_gap_volatility,
        tf.directional_action_eligible

    from demand           d
    left join risk        r    on d.signal_id      = r.signal_id
    left join price       p    on d.signal_id      = p.signal_id
    left join confidence  c    on d.signal_id      = c.signal_id
    left join category_dim    cat on d.category_name = cat.category_name
    left join location_dim    loc on d.store_id      = loc.store_id
    left join kroger_by_store_category k
           on d.store_id       = k.store_id
          and d.category_name  = k.category_name
    left join kroger_unit_by_store_category ku
           on d.store_id       = ku.store_id
          and d.category_name  = ku.category_name
    left join competitor_by_category comp
           on d.category_name  = comp.category
    left join category_dispersion cd
           on d.category_name  = cd.category_name
    left join category_elasticity e
           on d.category_name  = e.category
    left join temporal_features tf
           on d.store_id       = tf.store_id
          and d.category_name  = tf.category_name

),

-- ── Scored: price gap, confidence, and markdown safety ────────────────────────
-- price_position is computed in derived so it can reference price_gap_pct
-- and price_position_threshold without repeating the formula.

scored as (

    select
        signal_id,
        reference_month,
        category_name,
        store_id,
        state,
        region,
        category_key,
        location_key,
        store_city,

        kroger_avg_price,
        kroger_product_count,
        kroger_outliers_excluded,
        kroger_private_label_share,
        kroger_effective_price,
        kroger_promo_share,
        kroger_unit_price_median,
        kroger_unit_price_coverage_pct,
        kroger_unit_price_unit,
        competitor_avg_price,
        competitor_product_count,
        kroger_collection_date,
        competitor_price_asof_date,
        DATE_DIFF(kroger_collection_date, competitor_price_asof_date, DAY)
                                                                as competitor_price_staleness_days,

        -- Category dispersion and self-calibrating band
        -- tight categories (cereal CV≈30%) floor at 8%; dispersed (coffee CV≈157%) cap at 25%
        COALESCE(category_cv_pct, 30.0)                         as category_cv_pct,
        GREATEST({{ var('min_price_gap_threshold') }}, LEAST({{ var('max_price_gap_threshold') }},
            COALESCE(category_cv_pct, 30.0) * {{ var('cv_multiplier') }}
        ))                                                      as price_position_threshold,

        -- COALESCE all mart scores so later CTEs never see NULL
        COALESCE(overall_demand_gap_score, 50)                  as overall_demand_gap_score,
        COALESCE(category_momentum_score,  50)                  as category_momentum_score,
        COALESCE(intent_quality_score,     50)                  as intent_quality_score,
        COALESCE(competitive_threat_risk,  50)                  as competitive_threat_risk,
        COALESCE(demand_decay_risk,        35)                  as demand_decay_risk,
        COALESCE(margin_pressure_risk,     30)                  as margin_pressure_risk,
        COALESCE(promo_risk_score,         30)                  as promo_risk_score,
        COALESCE(overall_confidence_score, 50)                  as confidence_score,

        elasticity_tier,
        premium_tolerance_score,

        -- Temporal features (passed through from base; NULL = first collection)
        previous_price_gap_pct,
        previous_gap_direction,
        gap_direction_stable,
        collection_count,
        stable_direction_count,
        price_gap_change_pct,
        price_gap_volatility,
        directional_action_eligible,

        -- Price gap: NULL propagates honestly when either price is missing.
        -- Previous v3 COALESCE-to-0 produced false -100% gaps for stores
        -- where Kroger median was not available.
        CASE
            WHEN kroger_avg_price IS NULL OR competitor_avg_price IS NULL
                THEN NULL
            ELSE ROUND(
                SAFE_DIVIDE(
                    kroger_avg_price - competitor_avg_price,
                    NULLIF(competitor_avg_price, 0)
                ) * 100,
            2)
        END                                                     as price_gap_pct,

        -- effective_gap_pct: DIAGNOSTIC only — promo-adjusted gap vs Walmart.
        -- Regular-price scoring (price_gap_pct, price_position, cascade) unchanged.
        -- Wiring effective price into the cascade is a future phase.
        CASE
            WHEN kroger_effective_price IS NULL OR competitor_avg_price IS NULL THEN NULL
            ELSE ROUND(
                SAFE_DIVIDE(
                    kroger_effective_price - competitor_avg_price,
                    NULLIF(competitor_avg_price, 0)
                ) * 100,
            2)
        END                                                     as effective_gap_pct,

        -- Competitor data confidence label (step tiers — unchanged from v3)
        CASE
            WHEN competitor_product_count >= 20 THEN 'High'
            WHEN competitor_product_count >= 10 THEN 'Medium'
            WHEN competitor_product_count >= 3  THEN 'Low'
            ELSE 'Missing'
        END                                                     as price_gap_confidence,

        -- Smooth confidence weight: n/(n+15), so 6→0.29, 16→0.52, 40→0.73.
        -- Basket-mismatch risk is handled by price_gap_reliability gate (not here).
        ROUND(
            SAFE_DIVIDE(competitor_product_count, competitor_product_count + {{ var('confidence_smoothing_k') }}),
        3)                                                      as price_gap_confidence_weight,

        -- ── Markdown safety ────────────────────────────────────────────────────
        -- Inverse of markdown risk. High = safe to cut price; Low = cutting is dangerous.
        LEAST(100, GREATEST(0,
            100 - (
                COALESCE(margin_pressure_risk, 30) * 0.45
                + COALESCE(promo_risk_score,   30) * 0.30
                + COALESCE(demand_decay_risk,  35) * 0.25
            )
        ))                                                      as markdown_safety_score,

        load_timestamp

    from base

),

-- ── Derived: columns that depend on scored intermediates ─────────────────────

derived as (

    select
        *,

        -- Adjusted gap: discounts the gap when competitor sample is thin.
        -- NULL when price_gap_pct is NULL (honest propagation).
        CASE
            WHEN price_gap_pct IS NULL THEN NULL
            ELSE ROUND(price_gap_pct * price_gap_confidence_weight, 2)
        END                                                     as adjusted_price_gap_pct,

        -- Price position: CV-calibrated band (replaces fixed ±10% from v3).
        -- Moved here from scored so it can reference price_gap_pct and
        -- price_position_threshold without repeating the division formula.
        CASE
            WHEN competitor_avg_price IS NULL OR kroger_avg_price IS NULL
                THEN 'Unknown'
            WHEN price_gap_pct >  price_position_threshold THEN 'Overpriced'
            WHEN price_gap_pct < -price_position_threshold THEN 'Underpriced'
            ELSE 'Fair'
        END                                                     as price_position,

        -- Demand signal tier
        -- Threshold set at 60 to match current single-month range (39-63).
        -- Raise to 65 once 6+ months of data validates higher differentiation.
        CASE
            WHEN overall_demand_gap_score >= {{ var('demand_high_threshold') }}   THEN 'High'
            WHEN overall_demand_gap_score >= {{ var('demand_medium_threshold') }} THEN 'Medium'
            ELSE 'Low'
        END                                                     as demand_signal,

        -- ── Pricing power ──────────────────────────────────────────────────────
        -- Incorporates the elasticity-derived premium_tolerance_score so that
        -- low-elasticity categories (coffee tea, personal care) earn higher
        -- pricing power without needing stronger demand signals.
        LEAST(100, GREATEST(0,
            overall_demand_gap_score  * 0.30
            + category_momentum_score * 0.20
            + premium_tolerance_score * 0.20
            + markdown_safety_score   * 0.15
            + confidence_score        * 0.15
        ))                                                      as pricing_power_score,

        -- Competitive intensity: market density of competitor SKUs in this category
        CASE
            WHEN competitor_product_count >= 30 THEN 'Saturated'
            WHEN competitor_product_count >= 15 THEN 'Competitive'
            WHEN competitor_product_count >= 5  THEN 'Emerging'
            ELSE 'Sparse'
        END                                                     as competitive_intensity,

        -- How relevant is Walmart as a VALUE-ANCHOR (price-floor) benchmark for this
        -- category? Higher = Walmart EDLP is a fair floor; Lower = format/brand gap
        -- makes the floor less comparable (Kroger premium is expected, not mispricing).
        CASE
            WHEN LOWER(category_name) IN ('household','produce','dairy','frozen foods')
                THEN 'High'
            WHEN LOWER(category_name) IN ('breakfast cereal','snacks')
                THEN 'Medium'
            WHEN LOWER(category_name) IN ('beverages','coffee tea','personal care','meat seafood')
                THEN 'Low'
            ELSE 'Unknown'
        END                                                     as competitor_relevance_level,

        CASE
            WHEN LOWER(category_name) = 'household'
                THEN 'Commodity category. Walmart EDLP pricing is a highly relevant benchmark.'
            WHEN LOWER(category_name) = 'produce'
                THEN 'Commodity-like category. Price comparison useful though quality differences may matter.'
            WHEN LOWER(category_name) = 'dairy'
                THEN 'Commodity category. Walmart benchmark relevant for milk, eggs, yogurt and similar staples.'
            WHEN LOWER(category_name) = 'frozen foods'
                THEN 'Commodity/brand mix. Walmart benchmark relevant for price-sensitive frozen items.'
            WHEN LOWER(category_name) = 'breakfast cereal'
                THEN 'Brand-driven but price-comparable. Walmart benchmark moderately relevant.'
            WHEN LOWER(category_name) = 'snacks'
                THEN 'Brand-driven category. Walmart benchmark moderately relevant but not definitive.'
            WHEN LOWER(category_name) = 'beverages'
                THEN 'Brand-loyal category. Walmart benchmark may understate Kroger premium positioning.'
            WHEN LOWER(category_name) = 'coffee tea'
                THEN 'Premium-tolerant category. Walmart benchmark is weaker — treat as directional only.'
            WHEN LOWER(category_name) = 'personal care'
                THEN 'Brand-loyal category. Shoppers may tolerate Kroger premium over Walmart.'
            WHEN LOWER(category_name) = 'meat seafood'
                THEN 'Quality-differentiated category. Walmart price comparison low relevance without quality normalization.'
            ELSE 'Competitor relevance not classified.'
        END                                                     as competitor_relevance_reason,

        -- Gap reliability gate: bars non-comparable baskets from driving actions.
        -- comp_n < 10 = thin sample; |gap| > 50% = likely basket mismatch (e.g. frozen
        -- single-serve meals vs full-aisle); |gap| > 25% = directional uncertainty.
        CASE
            WHEN competitor_avg_price IS NULL
              OR kroger_avg_price IS NULL              THEN 'Unknown'
            WHEN competitor_product_count < {{ var('reliability_min_competitor_count') }}  THEN 'Low'
            WHEN competitor_price_staleness_days > {{ var('max_competitor_staleness_days') }}  THEN 'Low'
            WHEN ABS(price_gap_pct) > {{ var('reliability_low_gap_threshold') }}          THEN 'Low'
            WHEN ABS(price_gap_pct) > {{ var('reliability_medium_gap_threshold') }}       THEN 'Medium'
            ELSE 'High'
        END                                                     as price_gap_reliability,

        CASE
            WHEN competitor_avg_price IS NULL OR kroger_avg_price IS NULL
                THEN 'No competitor benchmark available for this category.'
            WHEN competitor_product_count < {{ var('reliability_min_competitor_count') }}
                THEN CONCAT(
                    'Thin competitor sample (', CAST(competitor_product_count AS STRING),
                    ' products) — benchmark covers a narrow slice of the category.'
                )
            WHEN competitor_price_staleness_days > {{ var('max_competitor_staleness_days') }}
                THEN CONCAT(
                    'Competitor benchmark is ', CAST(competitor_price_staleness_days AS STRING),
                    ' days old — stale beyond ', CAST({{ var('max_competitor_staleness_days') }} AS STRING),
                    '-day limit. Not used for pricing actions.'
                )
            WHEN ABS(price_gap_pct) > {{ var('reliability_low_gap_threshold') }}
                THEN 'Implausible gap magnitude indicates non-comparable Kroger vs Walmart product baskets — not used for pricing actions.'
            WHEN ABS(price_gap_pct) > {{ var('reliability_medium_gap_threshold') }}
                THEN 'Moderate gap with some basket-composition uncertainty — directional only.'
            ELSE 'Comparable baskets with adequate sample — gap is actionable.'
        END                                                     as price_gap_reliability_reason

    from scored

),

-- ── Actioned: cascade + intensity ─────────────────────────────────────────────

actioned as (

    select
        *,

        -- Pricing situation (demand × price interaction label)
        CASE
            WHEN demand_signal = 'High'   AND price_position = 'Overpriced'  THEN 'Premium Tolerance Test'
            WHEN demand_signal = 'Low'    AND price_position = 'Overpriced'  THEN 'Price Blocking Demand'
            WHEN demand_signal = 'High'   AND price_position = 'Underpriced' THEN 'Leaving Money on Table'
            WHEN demand_signal = 'Low'    AND price_position = 'Underpriced' THEN 'Demand Problem Not Price'
            WHEN demand_signal = 'High'   AND price_position = 'Fair'        THEN 'Strong Position'
            WHEN demand_signal = 'Medium' AND price_position = 'Fair'        THEN 'Stable Position'
            ELSE 'Weak Demand'
        END                                                     as pricing_situation,

        -- Action cascade (first match wins)
        CASE

            -- 0. No fresh Kroger price this period -> never act on stale fallback
            WHEN kroger_collection_date IS NULL
                THEN 'Investigate'

            -- 2. Investigate: data too weak or absent to act
            WHEN confidence_score < {{ var('investigate_confidence_threshold') }}
              OR competitor_avg_price IS NULL
              OR competitor_product_count < 3
                THEN 'Investigate'

            -- 3. Avoid Discount: margin too pressured to cut price
            WHEN markdown_safety_score < {{ var('avoid_markdown_safety_threshold') }}
              OR margin_pressure_risk  > {{ var('avoid_margin_pressure_threshold') }}
                THEN 'Avoid Discount'

            -- 4. Raise Price: underpriced, strong demand, pricing power confirmed
            WHEN price_position = 'Underpriced'
             AND demand_signal = 'High'
             AND pricing_power_score >= {{ var('expand_margin_threshold') }}
             AND margin_pressure_risk < {{ var('margin_pressure_avoid_threshold') }}
                THEN 'Review Price Increase'

            -- 5. Hold Premium: overpriced but demand + category elasticity support it
            -- Guard: skip when market is saturated AND competitor benchmark is meaningful
            WHEN price_position = 'Overpriced'
             AND demand_signal = 'High'
             AND pricing_power_score >= {{ var('pricing_power_hold_threshold') }}
             AND elasticity_tier IN ('Low', 'Medium')
             AND competitive_intensity != 'Saturated'
             AND (
                 competitor_relevance_level IN ('Low', 'Medium')
                 OR pricing_power_score >= {{ var('pricing_power_strong_threshold') }}
             )
                THEN 'Hold Premium'

            -- 6. Reduce Price (Full): overpriced, elastic category, safe margins, credible benchmark
            -- price_gap_reliability guard prevents basket-mismatch gaps (frozen, dairy, etc.)
            -- from generating spurious cut recommendations
            WHEN price_position = 'Overpriced'
             AND demand_signal IN ('Low', 'Medium')
             AND adjusted_price_gap_pct > {{ var('reduce_price_min_gap_pct') }}
             AND markdown_safety_score >= {{ var('markdown_safety_full_threshold') }}
             AND elasticity_tier IN ('High', 'Medium')
             AND competitor_relevance_level IN ('High', 'Medium')
             AND price_gap_reliability = 'High'
                THEN 'Review Price Reduction'

            -- 7. Reduce Price (Partial): overpriced, margin caution — any elasticity
            WHEN price_position = 'Overpriced'
             AND adjusted_price_gap_pct > {{ var('reduce_price_min_gap_pct') }}
             AND markdown_safety_score >= {{ var('avoid_markdown_safety_threshold') }}
             AND markdown_safety_score <  {{ var('markdown_safety_full_threshold') }}
             AND price_gap_reliability = 'High'
                THEN 'Review Price Reduction'

            -- 8. Protect Price: fair pricing with adequate demand — hold, don't discount
            -- Medium demand included because single-month data rarely reaches High threshold
            -- at a Fair price position. Tighten back to High-only at 6+ months.
            WHEN price_position = 'Fair'
             AND demand_signal IN ('High', 'Medium')
             AND competitive_threat_risk < {{ var('competitive_threat_threshold') }}
                THEN 'Protect Price'

            -- 9. Monitor: mixed signals or low elasticity premium not yet justified
            ELSE 'Monitor'

        END                                                     as recommended_price_action,

        -- Markdown intensity label (used in recommended_price and reason text)
        CASE
            WHEN markdown_safety_score >= {{ var('markdown_safety_full_threshold') }} THEN 'Full'
            WHEN markdown_safety_score >= {{ var('avoid_markdown_safety_threshold') }} THEN 'Partial'
            ELSE 'Not Safe'
        END                                                     as _intensity,

        -- ── Directional pricing signal ─────────────────────────────────────────
        -- SEPARATE from recommended_price_action — does NOT change the action cascade.
        -- Gate 1: direction must be stable (same as previous date, non-Unknown).
        -- Gate 2: benchmark must be reliable (Low/Unknown baskets → 'Unreliable Benchmark',
        --         keeping the same categories the Reduce Price reliability gate already blocks).
        CASE
            WHEN NOT COALESCE(gap_direction_stable, FALSE)
                THEN 'Insufficient Data'
            WHEN price_gap_reliability IN ('Low', 'Unknown')
                THEN 'Unreliable Benchmark'
            WHEN price_position = 'Overpriced'
                THEN 'Sustained Overpriced'
            WHEN price_position = 'Underpriced'
                THEN 'Sustained Underpriced'
            WHEN price_position = 'Fair'
                THEN 'Sustained Fair'
            ELSE 'Insufficient Data'
        END                                                     as directional_pricing_signal,

        -- Directional signal confidence:
        -- Insufficient  = direction not stable
        -- Unreliable    = stable but benchmark is Low/Unknown reliability
        -- Provisional   = reliable benchmark, direction stable, but < directional_established_min_dates collections
        -- Persistent    = reliable benchmark, direction stable, >= directional_established_min_dates collections
        CASE
            WHEN NOT COALESCE(gap_direction_stable, FALSE)
                THEN 'Insufficient'
            WHEN price_gap_reliability IN ('Low', 'Unknown')
                THEN 'Unreliable'
            WHEN COALESCE(collection_count, 1) >= {{ var('directional_established_min_dates') }}
                THEN 'Persistent'
            ELSE 'Provisional'
        END                                                     as directional_signal_confidence

    from derived

),

-- ── Tiered: within-category gap tercile ──────────────────────────────────────
-- relative_gap_tier is PEER-CONTEXT ONLY — never feeds the action cascade.
-- CV band remains the action classifier; NTILE rank is a diagnostic lens.
-- N=20 stores per category → terciles are the correct resolution (not deciles).

tiered as (

    select
        *,
        NTILE(3) OVER (
            PARTITION BY category_name
            ORDER BY ABS(price_gap_pct)
        )                                                       as gap_tile_raw
    from actioned

)

-- ── Final output ──────────────────────────────────────────────────────────────

select
    -- Keys and identifiers
    reference_month                                             as scoring_date,
    category_key,
    location_key,
    category_name,
    store_city,
    store_id,

    -- Price inputs
    ROUND(kroger_avg_price,     2)                              as kroger_avg_price,
    kroger_product_count,
    kroger_outliers_excluded,
    kroger_private_label_share,
    ROUND(kroger_unit_price_median, 4)                          as kroger_unit_price_median,
    kroger_unit_price_coverage_pct,
    kroger_unit_price_unit,
    ROUND(kroger_effective_price,   4)                          as kroger_effective_price,
    kroger_promo_share,
    ROUND(competitor_avg_price, 2)                              as competitor_avg_price,
    competitor_product_count,
    competitive_intensity,
    competitor_relevance_level,
    competitor_relevance_reason,
    kroger_collection_date,
    competitor_price_asof_date,
    competitor_price_staleness_days,

    -- Price gap
    price_gap_pct,
    adjusted_price_gap_pct,
    effective_gap_pct,
    price_position,
    price_position_threshold,
    category_cv_pct,
    price_gap_confidence,
    price_gap_confidence_weight,
    price_gap_reliability,
    price_gap_reliability_reason,
    -- relative_gap_tier is PEER-CONTEXT ONLY, never feeds the action cascade
    -- (CV band remains the classifier; NTILE over N=20 stores is diagnostic only)
    CASE
        WHEN price_gap_pct IS NULL THEN NULL
        WHEN gap_tile_raw = 3 THEN 'Top'
        WHEN gap_tile_raw = 2 THEN 'Middle'
        ELSE 'Bottom'
    END                                                         as relative_gap_tier,
    'CV calibrated absolute band'                               as price_band_method,
    '{{ var("threshold_config_version") }}'                     as threshold_config_version,

    -- Demand
    demand_signal,
    ROUND(overall_demand_gap_score, 2)                          as overall_demand_gap_score,
    ROUND(category_momentum_score,  2)                          as category_momentum_score,

    -- Margin
    ROUND(margin_pressure_risk,     2)                          as margin_pressure_risk,
    ROUND(promo_risk_score,         2)                          as promo_risk_score,
    ROUND(demand_decay_risk,        2)                          as demand_decay_risk,
    ROUND(markdown_safety_score,    2)                          as markdown_safety_score,

    -- Elasticity
    elasticity_tier,
    premium_tolerance_score,
    'Industry prior'                                            as elasticity_source,

    -- Composite scores
    ROUND(pricing_power_score,      2)                          as pricing_power_score,
    pricing_situation,

    -- Action
    recommended_price_action,

    -- Directional signal (separate column, separate confidence — does not modify action cascade)
    directional_pricing_signal,
    directional_signal_confidence,

    -- Temporal features
    COALESCE(collection_count, 1)                                   as collection_count,
    previous_price_gap_pct,
    previous_gap_direction,
    gap_direction_stable,
    stable_direction_count,
    price_gap_change_pct,
    ROUND(price_gap_volatility, 2)                                   as price_gap_volatility,
    COALESCE(directional_action_eligible, FALSE)                     as directional_action_eligible,

    -- Price reduction intensity — 'N/A' when action is not Review Price Reduction
    CASE
        WHEN recommended_price_action = 'Review Price Reduction' THEN _intensity
        ELSE 'N/A'
    END                                                         as price_reduction_intensity,

    -- Recommended shelf price
    ROUND(
        CASE recommended_price_action
            WHEN 'Review Price Reduction' THEN
                CASE _intensity
                    WHEN 'Full'    THEN GREATEST(
                                           COALESCE(competitor_avg_price, kroger_avg_price) * 1.03,
                                           COALESCE(kroger_avg_price, 0) * 0.95
                                       )
                    WHEN 'Partial' THEN COALESCE(kroger_avg_price, 0) * 0.97
                    ELSE                COALESCE(kroger_avg_price, 0)
                END
            WHEN 'Review Price Increase' THEN
                LEAST(
                    COALESCE(competitor_avg_price, kroger_avg_price) * 1.05,
                    COALESCE(kroger_avg_price, 0) * 1.04
                )
            ELSE COALESCE(kroger_avg_price, 0)
        END,
    2)                                                          as recommended_price,

    -- Plain-English reason with live score values
    CASE recommended_price_action
        WHEN 'Investigate' THEN CONCAT(
            'Insufficient data to recommend action. ',
            'Competitor sample: ', CAST(competitor_product_count AS STRING),
            ' products. Confidence: ', CAST(ROUND(confidence_score, 0) AS STRING), '/100.'
        )
        WHEN 'Avoid Discount' THEN CONCAT(
            'Margin pressure too high to discount safely. ',
            'Markdown safety: ', CAST(ROUND(markdown_safety_score, 0) AS STRING), '/100. ',
            'Protect current price.'
        )
        WHEN 'Review Price Increase' THEN CONCAT(
            'Kroger is ',
            CAST(CAST(ROUND(ABS(COALESCE(price_gap_pct, 0)), 0) AS INT64) AS STRING),
            '% below Walmart. Demand is strong (',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            '/100) and pricing power supports a price increase.'
        )
        WHEN 'Hold Premium' THEN CONCAT(
            'Kroger is ', CAST(ROUND(COALESCE(price_gap_pct, 0), 0) AS STRING),
            '% above Walmart but demand is strong (',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            '/100) and category has premium tolerance (',
            CAST(premium_tolerance_score AS STRING), '/100). Hold price.'
        )
        WHEN 'Review Price Reduction' THEN CONCAT(
            'Kroger is ', CAST(ROUND(COALESCE(price_gap_pct, 0), 0) AS STRING),
            '% above Walmart. ',
            CASE _intensity
                WHEN 'Full'    THEN 'Demand and margin support a full price reduction.'
                WHEN 'Partial' THEN 'Margin caution — partial reduction recommended.'
                ELSE                'Review margin before cutting.'
            END
        )
        WHEN 'Protect Price' THEN CONCAT(
            'Fair pricing with strong demand (',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            '/100). No change needed — defend shelf position.'
        )
        ELSE CONCAT(
            'Mixed signals. Demand: ', demand_signal,
            '. Pricing situation: ', pricing_situation,
            '. Revisit next month.'
        )
    END                                                         as price_action_reason,

    -- Action confidence
    CASE
        WHEN price_gap_confidence = 'High'
         AND ABS(COALESCE(adjusted_price_gap_pct, 0)) > 15
         AND overall_demand_gap_score > 60
         AND markdown_safety_score > 60
            THEN 'High'
        WHEN price_gap_confidence IN ('High', 'Medium')
         AND ABS(COALESCE(adjusted_price_gap_pct, 0)) > 10
            THEN 'Medium'
        ELSE 'Low'
    END                                                         as action_confidence_level,

    CASE
        WHEN price_gap_confidence = 'High'
         AND ABS(COALESCE(adjusted_price_gap_pct, 0)) > 15
         AND overall_demand_gap_score > 60
         AND markdown_safety_score > 60
            THEN 85
        WHEN price_gap_confidence IN ('High', 'Medium')
         AND ABS(COALESCE(adjusted_price_gap_pct, 0)) > 10
            THEN 60
        ELSE 35
    END                                                         as action_confidence_score,

    -- Confidence inputs
    ROUND(confidence_score,         2)                          as confidence_score,
    ROUND(competitive_threat_risk,  2)                          as competitive_threat_risk,

    -- Signal labels
    CASE
        WHEN competitor_avg_price IS NOT NULL THEN 'MEASURED'
        ELSE 'PROXY'
    END                                                         as signal_type,
    'Decision rule'                                             as pricing_signal_type,

    -- Metadata
    'v4_statistical_calibration'                                as score_version,
    CURRENT_TIMESTAMP()                                         as load_timestamp

from tiered
order by scoring_date desc, pricing_power_score desc
