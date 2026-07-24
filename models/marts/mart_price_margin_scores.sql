{{
    config(
        materialized = 'table',
        description  = 'Price and margin health scoring for CPG brand. One row per month × category × store.'
    )
}}

/*
  Grain: reference_month × category × store (mirrors fact_market_signals).

  Scores (0–100):
    price_position_score   — where shelf price sits vs. cost benchmarks (higher = premium positioned)
    cost_shock_score       — how much input costs have moved recently (higher = more cost pressure)
    margin_pressure_proxy_score — retail-price-vs-PPI divergence proxy (higher = more inferred pressure)
    promo_risk_score       — dependency on promotions to move product (higher = more risky)
    cost_passthrough_rate  — how well retail price tracks input costs (not capped; can exceed 100)
*/

with demand as (

    select * from {{ ref('mart_demand_gap_scores') }}

),

-- ── Retail price lags per store × category ────────────────────────────────────
-- Partitioned by store_id + category_name so each store×category gets its own
-- price history. Joining on signal_id (instead of reference_month) avoids the
-- many-to-many explosion that occurs once we have 200 store×category combos.

retail_lags as (

    select
        signal_id,
        LAG(retail_price, 1) OVER (
            PARTITION BY store_id, category_name ORDER BY reference_month
        )                                           as retail_price_1m_ago,
        LAG(retail_price, 3) OVER (
            PARTITION BY store_id, category_name ORDER BY reference_month
        )                                           as retail_price_3m_ago,
        LAG(retail_price, 6) OVER (
            PARTITION BY store_id, category_name ORDER BY reference_month
        )                                           as retail_price_6m_ago
    from demand

),

-- ── PPI lags from staging (one row per month — no cross-store cardinality) ────

ppi_lags_stg as (

    select
        DATE_TRUNC(observation_date, MONTH)         as reference_month,
        ppi_value,
        LAG(ppi_value, 1) OVER (
            ORDER BY DATE_TRUNC(observation_date, MONTH)
        )                                           as ppi_1m_ago,
        LAG(ppi_value, 3) OVER (
            ORDER BY DATE_TRUNC(observation_date, MONTH)
        )                                           as ppi_3m_ago,
        LAG(ppi_value, 6) OVER (
            ORDER BY DATE_TRUNC(observation_date, MONTH)
        )                                           as ppi_6m_ago
    from {{ ref('stg_fred_ppi') }}

),

-- ── CPI lags from staging ──────────────────────────────────────────────────────

cpi_lags_stg as (

    select
        reference_date                              as reference_month,
        LAG(cpi_value, 1) OVER (ORDER BY reference_date) as cpi_1m_ago,
        LAG(cpi_value, 3) OVER (ORDER BY reference_date) as cpi_3m_ago
    from {{ ref('stg_bls_cpi') }}
    where not is_suppressed

),

-- ── Kroger product-level promo detail per store × category ───────────────────

kroger_promo as (

    select
        DATE_TRUNC(DATE(collected_at), MONTH)   as reference_month,
        store_id,
        category,
        COUNT(*)                                as total_products,
        COUNTIF(price_promo IS NOT NULL)        as promo_products,
        AVG(price_regular)                      as avg_regular,
        AVG(COALESCE(price_promo, price_regular)) as avg_effective_price,
        SAFE_DIVIDE(
            COUNTIF(price_promo IS NOT NULL),
            NULLIF(COUNT(*), 0)
        )                                       as promo_fraction
    from {{ ref('stg_kroger_prices') }}
    group by 1, 2, 3

),

-- ── Join ──────────────────────────────────────────────────────────────────────

base as (

    select
        d.signal_id,
        d.reference_month,
        d.category_name,
        d.store_id,
        d.state,
        d.region,
        d.signal_type,
        d.load_timestamp,
        d.overall_demand_gap_score,
        d.avg_search_interest,

        d.retail_price,
        d.ppi_value,
        d.cpi_value,
        d.promo_depth_pct,
        d.shelf_product_count,
        rl.retail_price_1m_ago,
        rl.retail_price_3m_ago,
        rl.retail_price_6m_ago,
        pl.ppi_1m_ago,
        pl.ppi_3m_ago,
        pl.ppi_6m_ago,
        cl.cpi_1m_ago,
        cl.cpi_3m_ago,

        k.promo_fraction,
        k.promo_products,
        k.total_products,
        k.avg_effective_price

    from demand d
    left join retail_lags   rl on d.signal_id        = rl.signal_id
    left join ppi_lags_stg  pl on d.reference_month  = pl.reference_month
    left join cpi_lags_stg  cl on d.reference_month  = cl.reference_month
    left join kroger_promo   k
           on d.reference_month = k.reference_month
           and d.store_id       = k.store_id
           and d.category_name  = k.category

),

scored as (

    select
        signal_id,
        reference_month,
        category_name,
        store_id,
        state,
        region,

        -- ── 1. Price Position Score ───────────────────────────────────────────
        -- Measures whether shelf price is premium (high) vs. cost-driven (low).
        -- Compares retail price to CPI index: a premium brand should price above
        -- inflation; scoring 100 = significantly above CPI trend.
        LEAST(100, GREATEST(0,
            CASE
                WHEN retail_price IS NULL OR cpi_value IS NULL THEN 50
                ELSE
                    -- Normalise retail price against CPI baseline (260 ≈ typical food CPI)
                    SAFE_DIVIDE(retail_price * 100.0, NULLIF(cpi_value / 2.6, 0))
            END
        ))                                          as price_position_score,

        -- ── 2. Cost Shock Score ───────────────────────────────────────────────
        -- How much wholesale cost (PPI) moved in the last 3 months.
        -- High movement = cost volatility = uncertainty in margin planning.
        LEAST(100, GREATEST(0,
            COALESCE(
                ABS(
                    SAFE_DIVIDE(
                        COALESCE(ppi_value, 0) - COALESCE(ppi_3m_ago, ppi_value, 0),
                        NULLIF(COALESCE(ppi_3m_ago, 100), 0)
                    )
                ) * 500,   -- scale: 5% PPI move → score of 25; 20% move → score of 100
                10
            )
        ))                                          as cost_shock_score,

        -- ── 3. Margin Pressure Risk ───────────────────────────────────────────
        -- Retail price stagnant / falling while PPI rising = margin being squeezed.
        LEAST(100, GREATEST(0,
            CASE
                WHEN retail_price IS NULL OR ppi_value IS NULL THEN 30
                WHEN retail_price <= COALESCE(retail_price_1m_ago, retail_price)
                 AND ppi_value     > COALESCE(ppi_1m_ago, ppi_value)
                    THEN 80  -- classic margin squeeze
                WHEN retail_price <= COALESCE(retail_price_1m_ago, retail_price)
                    THEN 55  -- price compression only
                WHEN ppi_value > COALESCE(ppi_1m_ago, ppi_value)
                    THEN 40  -- cost rising; retail price holding for now
                ELSE
                    -- Healthy: price rising faster than costs
                    GREATEST(0, 30 - SAFE_DIVIDE(
                        COALESCE(retail_price, 0) - COALESCE(retail_price_1m_ago, retail_price, 0),
                        5.0
                    ))
            END
        ))                                          as margin_pressure_proxy_score,

        -- ── 4. Promo Risk Score ───────────────────────────────────────────────
        -- High fraction of SKUs on promo = demand is promo-dependent; risky.
        LEAST(100, GREATEST(0,
            COALESCE(promo_fraction, 0) * 80 +
            COALESCE(promo_depth_pct, 0) * 1.0
        ))                                          as promo_risk_score,

        -- ── 5. Cost Passthrough Rate ──────────────────────────────────────────
        -- % of PPI change that made it into shelf price; >100 = brand passing
        -- more than costs rose (gaining margin); <100 = absorbing cost increases.
        -- Not capped intentionally — the raw ratio is the useful signal.
        ROUND(
            COALESCE(
                SAFE_DIVIDE(
                    COALESCE(retail_price, 0) - COALESCE(retail_price_3m_ago, retail_price, 0),
                    NULLIF(
                        ABS(COALESCE(ppi_value, 0) - COALESCE(ppi_3m_ago, ppi_value, 0)),
                        0
                    )
                ) * 100,
                0
            ),
        2)                                          as cost_passthrough_rate,

        -- raw metrics
        retail_price,
        ppi_value,
        cpi_value,
        COALESCE(promo_fraction, 0)                 as promo_fraction,
        COALESCE(promo_products, 0)                 as promo_products,
        COALESCE(total_products, 0)                 as total_products,
        avg_effective_price,
        retail_price_1m_ago,
        ppi_1m_ago,
        overall_demand_gap_score,
        avg_search_interest,

        signal_type,
        'v4_robust_heuristic_calibration'           as score_version,
        CASE
            WHEN retail_price IS NULL
                THEN 'No Kroger price data for this month; price scores estimated at mid-range defaults'
            WHEN ppi_value IS NULL
                THEN 'No FRED PPI for this month; cost-side scores use prior month estimates'
            WHEN cpi_value IS NULL
                THEN 'BLS CPI suppressed or missing; price position score defaults to 50'
            ELSE 'All price signals measured'
        END                                         as data_note,
        load_timestamp

    from base

)

select
    signal_id,
    reference_month,
    category_name,
    store_id,
    state,
    region,

    ROUND(price_position_score,  2)                 as price_position_score,
    ROUND(cost_shock_score,      2)                 as cost_shock_score,
    ROUND(margin_pressure_proxy_score,  2)          as margin_pressure_proxy_score,
    ROUND(promo_risk_score,      2)                 as promo_risk_score,
    cost_passthrough_rate,

    -- Composite margin health (higher = more risk to margins)
    ROUND(LEAST(100, GREATEST(0,
        margin_pressure_proxy_score * 0.40 +
        cost_shock_score     * 0.25 +
        promo_risk_score     * 0.20 +
        (100 - price_position_score) * 0.15
    )), 2)                                          as overall_margin_risk_score,

    retail_price,
    ppi_value,
    cpi_value,
    promo_fraction,
    promo_products,
    total_products,
    avg_effective_price,
    retail_price_1m_ago,
    ppi_1m_ago,
    overall_demand_gap_score,
    avg_search_interest,

    signal_type,
    score_version,
    data_note,
    load_timestamp

from scored
order by reference_month desc, overall_margin_risk_score desc
