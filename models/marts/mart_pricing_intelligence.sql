{{
    config(
        materialized = 'table',
        description  = 'Full pricing intelligence engine: Kroger vs Walmart DFW per store × category, with elasticity-adjusted action cascade and plain-English reasons.'
    )
}}

/*
  Grain: reference_month × category × store (mirrors fact_market_signals).

  Intelligence layers:
    1. Category elasticity prior — industry knowledge; replaced by data-derived elasticity
       when 6+ months of collection accumulates.
    2. Competitor prices by category — Walmart DFW store 2105 via SerpAPI, grouped per
       category (fixes the previous month-level aggregation that blended all categories).
    3. Kroger avg price per store × category — directly from stg_kroger_prices.
    4. Scoring inputs from marts (demand gap, shelf risk, price margin, confidence).
    5. Markdown safety, pricing power, demand signal, price gap confidence.
    6. Action cascade (8 levels, first match wins).

  Score version: v3_category_prices
    vs v2_with_trends: competitor price now category-specific, not a monthly overall average.
*/

-- ── CTE 1: Category elasticity prior ─────────────────────────────────────────
-- Industry-knowledge prior; elasticity_source = 'Industry prior' on every row.
-- Will be replaced with data-derived elasticity when 6+ months of collection accumulates.

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

-- ── CTE 2: Competitor prices by category ──────────────────────────────────────
-- Walmart DFW store 2105. Grouped by category so each category gets its own
-- benchmark price instead of a blended monthly average across all categories.

competitor_by_category as (

    select
        category,
        ROUND(AVG(competitor_price), 4)   as competitor_avg_price,
        COUNT(*)                           as competitor_product_count,
        MAX(reference_date)                as competitor_last_updated
    from {{ ref('stg_serpapi_prices') }}
    where competitor_price is not null
    group by 1

),

-- ── CTE 3: Kroger prices by store × category ──────────────────────────────────
-- AVG(price_regular) ignores NULLs — products sold by weight are excluded.
-- No date filter: uses the latest loaded batch (single month currently).

kroger_by_store_category as (

    select
        store_id,
        COALESCE(category, 'Unknown')          as category_name,
        ROUND(AVG(price_regular), 4)           as kroger_avg_price,
        COUNT(distinct product_id)             as kroger_product_count
    from {{ ref('stg_kroger_prices') }}
    where price_regular is not null
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
        COALESCE(k.kroger_avg_price, d.retail_price)    as kroger_avg_price,
        COALESCE(k.kroger_product_count, 0)             as kroger_product_count,

        -- Category-level Walmart price (NULL when SerpAPI has no data for this category)
        comp.competitor_avg_price,
        COALESCE(comp.competitor_product_count, 0)      as competitor_product_count,
        comp.competitor_last_updated,

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
        COALESCE(e.elasticity_tier,          'Medium') as elasticity_tier,
        COALESCE(e.premium_tolerance_score,   50)      as premium_tolerance_score

    from demand           d
    left join risk        r    on d.signal_id      = r.signal_id
    left join price       p    on d.signal_id      = p.signal_id
    left join confidence  c    on d.signal_id      = c.signal_id
    left join category_dim   cat on d.category_name = cat.category_name
    left join location_dim   loc on d.store_id      = loc.store_id
    left join kroger_by_store_category k
           on d.store_id       = k.store_id
          and d.category_name  = k.category_name
    left join competitor_by_category comp
           on d.category_name  = comp.category
    left join category_elasticity e
           on d.category_name  = e.category

),

-- ── Scored: price gap, position, confidence, and markdown safety ──────────────

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
        competitor_avg_price,
        competitor_product_count,
        competitor_last_updated,

        -- COALESCE all mart scores so later CTEs never see NULL
        COALESCE(overall_demand_gap_score, 50) as overall_demand_gap_score,
        COALESCE(category_momentum_score,  50) as category_momentum_score,
        COALESCE(intent_quality_score,     50) as intent_quality_score,
        COALESCE(competitive_threat_risk,  50) as competitive_threat_risk,
        COALESCE(demand_decay_risk,        35) as demand_decay_risk,
        COALESCE(margin_pressure_risk,     30) as margin_pressure_risk,
        COALESCE(promo_risk_score,         30) as promo_risk_score,
        COALESCE(overall_confidence_score, 50) as confidence_score,

        elasticity_tier,
        premium_tolerance_score,

        -- Price gap: positive = Kroger above Walmart
        ROUND(
            SAFE_DIVIDE(
                COALESCE(kroger_avg_price, 0) - COALESCE(competitor_avg_price, 0),
                NULLIF(COALESCE(competitor_avg_price, 0), 0)
            ) * 100,
        2)                                                  as price_gap_pct,

        -- Price position label
        CASE
            WHEN competitor_avg_price IS NULL
                THEN 'Unknown'
            WHEN SAFE_DIVIDE(
                    COALESCE(kroger_avg_price, 0) - competitor_avg_price,
                    NULLIF(competitor_avg_price, 0)
                 ) * 100 > 10
                THEN 'Overpriced'
            WHEN SAFE_DIVIDE(
                    COALESCE(kroger_avg_price, 0) - competitor_avg_price,
                    NULLIF(competitor_avg_price, 0)
                 ) * 100 < -10
                THEN 'Underpriced'
            ELSE 'Fair'
        END                                                 as price_position,

        -- Competitor data confidence — governs how much to trust the price gap
        CASE
            WHEN competitor_product_count >= 20 THEN 'High'
            WHEN competitor_product_count >= 10 THEN 'Medium'
            WHEN competitor_product_count >= 3  THEN 'Low'
            ELSE 'Missing'
        END                                                 as price_gap_confidence,

        CASE
            WHEN competitor_product_count >= 20 THEN 1.00
            WHEN competitor_product_count >= 10 THEN 0.70
            WHEN competitor_product_count >= 3  THEN 0.40
            ELSE 0.00
        END                                                 as price_gap_confidence_weight,

        -- ── Markdown safety ────────────────────────────────────────────────────
        -- Inverse of markdown risk. High = safe to cut price; Low = cutting is dangerous.
        LEAST(100, GREATEST(0,
            100 - (
                COALESCE(margin_pressure_risk, 30) * 0.45
                + COALESCE(promo_risk_score,   30) * 0.30
                + COALESCE(demand_decay_risk,  35) * 0.25
            )
        ))                                                  as markdown_safety_score,

        load_timestamp

    from base

),

-- ── Derived: columns that depend on scored intermediates ─────────────────────

derived as (

    select
        *,

        -- Adjusted gap: discounts the gap when competitor sample is thin
        ROUND(price_gap_pct * price_gap_confidence_weight, 2) as adjusted_price_gap_pct,

        -- Demand signal tier
        -- Note: threshold set at 60 (not 65) to match current single-month data
        -- range of 39–63. Raise to 65 once 6+ months of data validates higher
        -- score differentiation.
        CASE
            WHEN overall_demand_gap_score >= {{ var('demand_high_threshold') }}   THEN 'High'
            WHEN overall_demand_gap_score >= {{ var('demand_medium_threshold') }} THEN 'Medium'
            ELSE 'Low'
        END                                                 as demand_signal,

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
        ))                                                  as pricing_power_score,

        -- Competitive intensity: market density of competitor SKUs in this category
        CASE
            WHEN competitor_product_count >= 30 THEN 'Saturated'
            WHEN competitor_product_count >= 15 THEN 'Competitive'
            WHEN competitor_product_count >= 5  THEN 'Emerging'
            ELSE 'Sparse'
        END                                                 as competitive_intensity

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
        END                                                 as pricing_situation,

        -- Action cascade (first match wins)
        CASE

            -- 1. Investigate: data too weak or absent to act
            WHEN confidence_score < 50
              OR competitor_avg_price IS NULL
              OR competitor_product_count < 3
                THEN 'Investigate'

            -- 2. Avoid Discount: margin too pressured to cut price
            WHEN markdown_safety_score < {{ var('avoid_markdown_safety_threshold') }}
              OR margin_pressure_risk  > {{ var('avoid_margin_pressure_threshold') }}
                THEN 'Avoid Discount'

            -- 3. Raise Price: underpriced, strong demand, pricing power confirmed
            WHEN price_position = 'Underpriced'
             AND demand_signal = 'High'
             AND pricing_power_score >= {{ var('expand_margin_threshold') }}
             AND margin_pressure_risk < 65
                THEN 'Raise Price'

            -- 4. Hold Premium: overpriced but demand + category elasticity support it
            -- Threshold 65 (not 70): at 1 month of data pricing_power tops at ~69 for
            -- low-elasticity categories. Raise back to 70 at 6+ months of data.
            -- Guard: skip when market is saturated (competing on price is necessary)
            WHEN price_position = 'Overpriced'
             AND demand_signal = 'High'
             AND pricing_power_score >= 65
             AND elasticity_tier IN ('Low', 'Medium')
             AND competitive_intensity != 'Saturated'
                THEN 'Hold Premium'

            -- 5. Reduce Price (Full): overpriced, elastic category, safe margins
            WHEN price_position = 'Overpriced'
             AND demand_signal IN ('Low', 'Medium')
             AND adjusted_price_gap_pct > 10
             AND markdown_safety_score >= 60
             AND elasticity_tier IN ('High', 'Medium')
                THEN 'Reduce Price'

            -- 6. Reduce Price (Partial): overpriced, margin caution — any elasticity
            WHEN price_position = 'Overpriced'
             AND adjusted_price_gap_pct > 10
             AND markdown_safety_score BETWEEN {{ var('avoid_markdown_safety_threshold') }} AND 59
                THEN 'Reduce Price'

            -- 7. Protect Price: fair pricing with adequate demand — hold, don't discount
            -- Medium demand included because single-month data rarely reaches High threshold
            -- at a Fair price position. Tighten back to High-only at 6+ months.
            WHEN price_position = 'Fair'
             AND demand_signal IN ('High', 'Medium')
             AND competitive_threat_risk < 70
                THEN 'Protect Price'

            -- 8. Monitor: mixed signals or low elasticity premium not yet justified
            ELSE 'Monitor'

        END                                                 as recommended_price_action,

        -- Markdown intensity label (used in recommended_price and reason text)
        CASE
            WHEN markdown_safety_score >= 60 THEN 'Full'
            WHEN markdown_safety_score >= 40 THEN 'Partial'
            ELSE 'Not Safe'
        END                                                 as _intensity

    from derived

)

-- ── Final output ──────────────────────────────────────────────────────────────

select
    -- Keys and identifiers
    reference_month                                     as scoring_date,
    category_key,
    location_key,
    category_name,
    store_city,
    store_id,

    -- Price inputs
    ROUND(kroger_avg_price,     2)                      as kroger_avg_price,
    kroger_product_count,
    ROUND(competitor_avg_price, 2)                      as competitor_avg_price,
    competitor_product_count,
    competitive_intensity,
    competitor_last_updated,

    -- Price gap
    price_gap_pct,
    adjusted_price_gap_pct,
    price_position,
    price_gap_confidence,
    price_gap_confidence_weight,

    -- Demand
    demand_signal,
    ROUND(overall_demand_gap_score, 2)                  as overall_demand_gap_score,
    ROUND(category_momentum_score,  2)                  as category_momentum_score,

    -- Margin
    ROUND(margin_pressure_risk,     2)                  as margin_pressure_risk,
    ROUND(promo_risk_score,         2)                  as promo_risk_score,
    ROUND(demand_decay_risk,        2)                  as demand_decay_risk,
    ROUND(markdown_safety_score,    2)                  as markdown_safety_score,

    -- Elasticity
    elasticity_tier,
    premium_tolerance_score,
    'Industry prior'                                    as elasticity_source,

    -- Composite scores
    ROUND(pricing_power_score,      2)                  as pricing_power_score,
    pricing_situation,

    -- Action
    recommended_price_action,

    -- Price reduction intensity — 'N/A' when action is not Reduce Price
    CASE
        WHEN recommended_price_action = 'Reduce Price' THEN _intensity
        ELSE 'N/A'
    END                                                 as price_reduction_intensity,

    -- Recommended shelf price
    ROUND(
        CASE recommended_price_action
            WHEN 'Reduce Price' THEN
                CASE _intensity
                    WHEN 'Full'    THEN GREATEST(
                                           COALESCE(competitor_avg_price, kroger_avg_price) * 1.03,
                                           COALESCE(kroger_avg_price, 0) * 0.95
                                       )
                    WHEN 'Partial' THEN COALESCE(kroger_avg_price, 0) * 0.97
                    ELSE                COALESCE(kroger_avg_price, 0)
                END
            WHEN 'Raise Price' THEN
                LEAST(
                    COALESCE(competitor_avg_price, kroger_avg_price) * 1.05,
                    COALESCE(kroger_avg_price, 0) * 1.04
                )
            ELSE COALESCE(kroger_avg_price, 0)
        END,
    2)                                                  as recommended_price,

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
        WHEN 'Raise Price' THEN CONCAT(
            'Kroger is ',
            CAST(CAST(ROUND(ABS(price_gap_pct), 0) AS INT64) AS STRING),
            '% below Walmart. Demand is strong (',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            '/100) and pricing power supports an increase.'
        )
        WHEN 'Hold Premium' THEN CONCAT(
            'Kroger is ', CAST(ROUND(price_gap_pct, 0) AS STRING),
            '% above Walmart but demand is strong (',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            '/100) and category has premium tolerance (',
            CAST(premium_tolerance_score AS STRING), '/100). Hold price.'
        )
        WHEN 'Reduce Price' THEN CONCAT(
            'Kroger is ', CAST(ROUND(price_gap_pct, 0) AS STRING),
            '% above Walmart. ',
            CASE _intensity
                WHEN 'Full'    THEN 'Demand and margin support a full price reduction.'
                WHEN 'Partial' THEN 'Margin caution — reduce partially only.'
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
    END                                                 as price_action_reason,

    -- Action confidence
    CASE
        WHEN price_gap_confidence = 'High'
         AND ABS(adjusted_price_gap_pct) > 15
         AND overall_demand_gap_score > 60
         AND markdown_safety_score > 60
            THEN 'High'
        WHEN price_gap_confidence IN ('High', 'Medium')
         AND ABS(adjusted_price_gap_pct) > 10
            THEN 'Medium'
        ELSE 'Low'
    END                                                 as action_confidence_level,

    CASE
        WHEN price_gap_confidence = 'High'
         AND ABS(adjusted_price_gap_pct) > 15
         AND overall_demand_gap_score > 60
         AND markdown_safety_score > 60
            THEN 85
        WHEN price_gap_confidence IN ('High', 'Medium')
         AND ABS(adjusted_price_gap_pct) > 10
            THEN 60
        ELSE 35
    END                                                 as action_confidence_score,

    -- Confidence inputs
    ROUND(confidence_score,         2)                  as confidence_score,
    ROUND(competitive_threat_risk,  2)                  as competitive_threat_risk,

    -- Signal labels
    CASE
        WHEN competitor_avg_price IS NOT NULL THEN 'MEASURED'
        ELSE 'PROXY'
    END                                                 as signal_type,
    'Decision rule'                                     as pricing_signal_type,

    -- Metadata
    'v3_category_prices'                                as score_version,
    CURRENT_TIMESTAMP()                                 as load_timestamp

from actioned
order by scoring_date desc, pricing_power_score desc
