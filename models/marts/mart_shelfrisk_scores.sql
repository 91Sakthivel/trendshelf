{{
    config(
        materialized = 'table',
        description  = 'Shelf risk scoring: likelihood of missed sales, demand decay, and assortment problems. One row per month × category × store.'
    )
}}

/*
  Grain: reference_month × category × store (mirrors fact_market_signals).

  Risk scores (0–100, higher = more risk):
    missed_demand_risk        — unmet demand due to insufficient shelf presence
    demand_decay_risk         — falling search interest indicating trend reversal
    phantom_distribution_risk — shelf space wasted on low-demand products
    competitive_threat_risk   — MEASURED via SerpAPI competitor pricing (falls back to PPI proxy)
    assortment_trap_risk      — over-indexed on promo SKUs that may disappear
    overall_risk_score        — weighted composite
    risk_level                — 'HIGH' / 'MEDIUM' / 'LOW' bucket
*/

with demand as (

    select * from {{ ref('mart_demand_gap_scores') }}

),

-- ── Month-over-month trend velocity for decay detection ───────────────────────
-- avg_search_interest is the same per month for all stores (Google Trends is national),
-- so distinct on (reference_month, avg_search_interest) gives exactly one row per month.

trend_velocity as (

    select
        reference_month,
        category_name,
        avg_search_interest,
        LAG(avg_search_interest, 1) OVER (PARTITION BY category_name ORDER BY reference_month) as prev_interest,
        LAG(avg_search_interest, 2) OVER (PARTITION BY category_name ORDER BY reference_month) as interest_2m_ago,
        LAG(avg_search_interest, 3) OVER (PARTITION BY category_name ORDER BY reference_month) as interest_3m_ago
    from (
        select distinct reference_month, category_name, avg_search_interest
        from demand
    )

),

-- ── Retail price lag per store × category ────────────────────────────────────
-- Partitioned so each store×category gets its own LAG sequence.
-- Without partitioning, a many-to-many on reference_month alone would explode
-- to thousands of cross-joined rows once we have 200 store×category combos.

retail_price_lag as (

    select
        signal_id,
        LAG(retail_price, 1) OVER (
            PARTITION BY store_id, category_name
            ORDER BY reference_month
        )                                              as prev_retail_price
    from demand

),

-- ── PPI lag from staging (one row per month — no cross-store cardinality) ─────

ppi_lag_monthly as (

    select
        DATE_TRUNC(observation_date, MONTH)            as reference_month,
        LAG(ppi_value, 1) OVER (
            ORDER BY DATE_TRUNC(observation_date, MONTH)
        )                                              as prev_ppi
    from {{ ref('stg_fred_ppi') }}

),

-- ── SerpAPI competitor prices aggregated to month ─────────────────────────────

competitor_monthly as (

    select
        DATE_TRUNC(reference_date, MONTH)           as reference_month,
        AVG(competitor_price)                       as competitor_avg_price,
        COUNT(distinct competitor_store)            as competitor_store_count,
        COUNT(*)                                    as price_observations
    from {{ ref('stg_serpapi_prices') }}
    where competitor_price is not null
    group by 1

),

-- ── Join everything for scoring ───────────────────────────────────────────────

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
        d.promo_depth_pct,
        d.retail_price,
        d.ppi_value,
        d.cpi_value,
        d.category_momentum_score,
        d.search_to_shelf_gap,
        d.phantom_distribution,
        d.intent_quality_score,
        d.overall_demand_gap_score,
        d.load_timestamp,

        v.prev_interest,
        v.interest_2m_ago,
        v.interest_3m_ago,
        rpl.prev_retail_price,
        pl.prev_ppi,

        c.competitor_avg_price,
        c.competitor_store_count,
        c.price_observations

    from demand d
    left join trend_velocity    v   on d.reference_month = v.reference_month
                                   and d.category_name  = v.category_name
    left join retail_price_lag  rpl on d.signal_id       = rpl.signal_id
    left join ppi_lag_monthly   pl  on d.reference_month = pl.reference_month
    left join competitor_monthly c  on d.reference_month = c.reference_month

),

-- ── Individual risk scores ────────────────────────────────────────────────────

scored as (

    select
        signal_id,
        reference_month,
        category_name,
        store_id,
        state,
        region,

        -- ── 1. Missed Demand Risk ─────────────────────────────────────────────
        -- High search + limited shelf = sales being left on the table
        LEAST(100, GREATEST(0,
            search_to_shelf_gap * 0.7 +
            CASE WHEN avg_search_interest > 60 AND shelf_product_count < 10
                 THEN 30
                 WHEN avg_search_interest > 40 AND shelf_product_count < 20
                 THEN 15
                 ELSE 0
            END
        ))                                              as missed_demand_risk,

        -- ── 2. Demand Decay Risk ──────────────────────────────────────────────
        -- Consecutive months of falling interest = trend reversal in progress
        LEAST(100, GREATEST(0,
            CASE
                WHEN COALESCE(avg_search_interest, 0) < COALESCE(prev_interest, 100)
                 AND COALESCE(prev_interest, 100)     < COALESCE(interest_2m_ago, 100)
                 AND COALESCE(interest_2m_ago, 100)   < COALESCE(interest_3m_ago, 100)
                    THEN 85  -- 3 consecutive months of decline: severe
                WHEN COALESCE(avg_search_interest, 0) < COALESCE(prev_interest, 100)
                 AND COALESCE(prev_interest, 100)     < COALESCE(interest_2m_ago, 100)
                    THEN 60  -- 2 months: elevated
                WHEN COALESCE(avg_search_interest, 0) < COALESCE(prev_interest, 100)
                    THEN 35  -- 1 month: watch closely
                ELSE GREATEST(0,
                    50 - SAFE_DIVIDE(
                        COALESCE(avg_search_interest, 50) - COALESCE(prev_interest, 50),
                        5.0
                    )
                )
            END
        ))                                              as demand_decay_risk,

        -- ── 3. Phantom Distribution Risk ─────────────────────────────────────
        -- Ghost SKUs: high product count relative to consumer interest.
        -- High score = many products on shelf + weak search signal = shelf waste.
        LEAST(100, GREATEST(0,
            SAFE_DIVIDE(COALESCE(shelf_product_count, 0), 50.0) * 100 *
            GREATEST(0.0,
                1.0 - SAFE_DIVIDE(COALESCE(avg_search_interest, 0), 100.0)
            )
        ))                                              as phantom_distribution_risk,

        -- ── 4. Competitive Threat Risk ────────────────────────────────────────
        -- MEASURED via SerpAPI when competitor prices are available.
        -- competitor_price_advantage = % by which Kroger price exceeds competitor avg.
        -- Positive = Kroger more expensive = HIGH threat.
        -- Falls back to PPI-based proxy when SerpAPI data is absent.
        LEAST(100, GREATEST(0,
            CASE
                -- MEASURED: use actual competitor price comparison
                WHEN competitor_avg_price IS NOT NULL AND retail_price IS NOT NULL
                    THEN CASE
                        WHEN retail_price > competitor_avg_price
                            -- Kroger priced above competitors: scaling threat
                            THEN LEAST(100,
                                50 + SAFE_DIVIDE(
                                    retail_price - competitor_avg_price,
                                    competitor_avg_price
                                ) * 200
                            )
                        ELSE
                            -- Kroger at or below competitor price: LOW threat
                            GREATEST(0,
                                25 - SAFE_DIVIDE(
                                    competitor_avg_price - retail_price,
                                    competitor_avg_price
                                ) * 100
                            )
                    END
                -- PROXY: no SerpAPI data; infer from retail vs PPI movement
                WHEN retail_price IS NULL OR prev_retail_price IS NULL THEN 25
                WHEN retail_price < prev_retail_price
                 AND ppi_value    > COALESCE(prev_ppi, ppi_value)
                    THEN 80  -- price cut while input costs rising = competitive pressure
                WHEN retail_price < prev_retail_price
                    THEN 50  -- price cut without cost pressure = promotional competition
                WHEN ppi_value > COALESCE(prev_ppi, ppi_value)
                    THEN 35  -- cost rising but price holding = will need to act soon
                ELSE 15
            END
        ))                                              as competitive_threat_risk,

        -- ── 5. Assortment Trap Risk ───────────────────────────────────────────
        -- Heavy promo dependence = vulnerable if promos are withdrawn
        LEAST(100, GREATEST(0,
            COALESCE(promo_depth_pct, 0) * 2 +
            CASE WHEN shelf_product_count > 0
                      AND COALESCE(promo_depth_pct, 0) > 15
                 THEN 20
                 ELSE 0
            END
        ))                                              as assortment_trap_risk,

        -- raw inputs
        avg_search_interest,
        shelf_product_count,
        promo_depth_pct,
        retail_price,
        ppi_value,
        cpi_value,
        competitor_avg_price,
        -- competitor_price_advantage: positive = Kroger more expensive (bad)
        ROUND(
            SAFE_DIVIDE(
                retail_price - COALESCE(competitor_avg_price, retail_price),
                NULLIF(COALESCE(competitor_avg_price, retail_price), 0)
            ) * 100,
        2)                                              as competitor_price_advantage_pct,
        overall_demand_gap_score,

        -- MEASURED when SerpAPI competitor data is available; PROXY when falling back to PPI
        CASE WHEN competitor_avg_price IS NOT NULL THEN 'MEASURED' ELSE 'PROXY' END as signal_type,
        'v4_robust_heuristic_calibration'               as score_version,
        CASE
            WHEN competitor_avg_price IS NOT NULL
                THEN CONCAT(
                    'Competitive threat based on ',
                    CAST(COALESCE(competitor_store_count, 0) AS STRING),
                    ' competitor store(s) from SerpAPI — MEASURED'
                )
            WHEN avg_search_interest = 0 OR avg_search_interest IS NULL
                THEN 'No search data; decay and missed-demand risks estimated conservatively'
            WHEN retail_price IS NULL
                THEN 'No retail price this month; competitive risk uses PPI signal only (PROXY)'
            ELSE 'No SerpAPI competitor data yet; competitive risk uses PPI proxy'
        END                                             as data_note,
        load_timestamp

    from base

),

-- ── Composite + bucketing ─────────────────────────────────────────────────────

final as (

    select
        signal_id,
        reference_month,
        category_name,
        store_id,
        state,
        region,

        ROUND(missed_demand_risk,        2)             as missed_demand_risk,
        ROUND(demand_decay_risk,         2)             as demand_decay_risk,
        ROUND(phantom_distribution_risk, 2)             as phantom_distribution_risk,
        ROUND(competitive_threat_risk,   2)             as competitive_threat_risk,
        ROUND(assortment_trap_risk,      2)             as assortment_trap_risk,

        ROUND(LEAST(100, GREATEST(0,
            missed_demand_risk        * 0.30 +
            demand_decay_risk         * 0.25 +
            phantom_distribution_risk * 0.15 +
            competitive_threat_risk   * 0.20 +
            assortment_trap_risk      * 0.10
        )), 2)                                          as overall_risk_score,

        avg_search_interest,
        shelf_product_count,
        promo_depth_pct,
        retail_price,
        ppi_value,
        cpi_value,
        competitor_avg_price,
        competitor_price_advantage_pct,
        overall_demand_gap_score,

        signal_type,
        score_version,
        data_note,
        load_timestamp

    from scored

)

select
    *,
    CASE
        WHEN overall_risk_score >= 65 THEN 'HIGH'
        WHEN overall_risk_score >= 35 THEN 'MEDIUM'
        ELSE 'LOW'
    END                                                 as risk_level
from final
order by reference_month desc, overall_risk_score desc
