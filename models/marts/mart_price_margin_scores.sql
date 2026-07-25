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
        series_id,
        ppi_value,
        LAG(ppi_value, 1) OVER (
            PARTITION BY series_id ORDER BY DATE_TRUNC(observation_date, MONTH)
        )                                           as ppi_1m_ago,
        LAG(ppi_value, 3) OVER (
            PARTITION BY series_id ORDER BY DATE_TRUNC(observation_date, MONTH)
        )                                           as ppi_3m_ago,
        LAG(ppi_value, 6) OVER (
            PARTITION BY series_id ORDER BY DATE_TRUNC(observation_date, MONTH)
        )                                           as ppi_6m_ago
    from {{ ref('stg_fred_ppi') }}

),

-- ── Resolve latest available FRED month for each spine month, with a staleness
--    guard ──────────────────────────────────────────────────────────────────────
-- Same latest-available-as-of pattern as fact_market_signals.sql's fred_as_of CTE
-- (lines 89-98): resolve the most recent FRED month <= each spine month. If that
-- FRED month is more than {{ var('max_ppi_staleness_months') }} months behind the
-- spine month, treat the PPI lag columns as unknown (NULL) rather than carrying an
-- indefinitely stale reading forward. ppi_signal_stale records that determination
-- explicitly so it's never a silent NULL.

ppi_as_of as (

    select
        d.reference_month,
        CASE
            WHEN DATE_DIFF(d.reference_month, MAX(pl.reference_month), MONTH)
                 <= {{ var('max_ppi_staleness_months') }}
                THEN MAX(pl.reference_month)
        END                                                      as ppi_month,
        COALESCE(
            DATE_DIFF(d.reference_month, MAX(pl.reference_month), MONTH)
                > {{ var('max_ppi_staleness_months') }},
            TRUE
        )                                                        as ppi_signal_stale
    from (select distinct reference_month from demand) d
    left join ppi_lags_stg pl on pl.reference_month <= d.reference_month
    group by d.reference_month

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
        pa.ppi_signal_stale,
        -- Whether a real prior-month comparison is even possible. FALSE for a store×
        -- category's first observed month (retail) or the very start of the FRED series'
        -- own history (PPI) — distinct from ppi_signal_stale, which is about a resolved
        -- PPI reading being too OLD, not about no prior reading existing at all. Read by
        -- the unknown-trend branch in `scored`, guarded by not_null tests in schema.yml.
        rl.retail_price_1m_ago IS NOT NULL                     as has_prior_month_price,
        pl.ppi_1m_ago IS NOT NULL                               as has_prior_month_ppi,
        -- Retail price direction vs. one month ago, computed once here (no COALESCE-to-
        -- self): NULL when retail_price_1m_ago is NULL, which is fine because the CASE in
        -- `scored` routes has_prior_month_price = FALSE rows to the unknown branch before
        -- this column is ever consulted.
        d.retail_price <= rl.retail_price_1m_ago                as retail_price_declining,
        -- Month-over-month PPI % change, computed once here so both the branch-80 and
        -- branch-40 tests in `scored` read the same value instead of duplicating the
        -- expression. Same null-handling as the old inline `>` comparison: a NULL
        -- ppi_1m_ago collapses the numerator to 0, giving 0% change (not NULL, not an error).
        SAFE_DIVIDE(
            d.ppi_value - COALESCE(pl.ppi_1m_ago, d.ppi_value),
            NULLIF(COALESCE(pl.ppi_1m_ago, d.ppi_value), 0)
        ) * 100                                                as ppi_mom_pct_change,
        -- Retail MoM %% change, computed once here (same pattern as ppi_mom_pct_change)
        -- so the ELSE/healthy branch in `scored` reads a percent, not raw dollars — a $1
        -- rise on a $2 item and a $40 item are no longer scored identically. See #7.13.
        SAFE_DIVIDE(
            d.retail_price - COALESCE(rl.retail_price_1m_ago, d.retail_price),
            NULLIF(COALESCE(rl.retail_price_1m_ago, d.retail_price), 0)
        ) * 100                                                as retail_mom_pct_change,
        cl.cpi_1m_ago,
        cl.cpi_3m_ago,

        k.promo_fraction,
        k.promo_products,
        k.total_products,
        k.avg_effective_price

    from demand d
    left join retail_lags   rl on d.signal_id        = rl.signal_id
    left join ppi_as_of     pa on d.reference_month  = pa.reference_month
    left join ppi_lags_stg  pl on pa.ppi_month        = pl.reference_month
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
        -- How much wholesale cost (PPI) has RISEN in the last 3 months — directional,
        -- not volatility. A falling-cost period is relief, not a shock, and floors to 0
        -- via the outer GREATEST rather than scoring identically to a rise of the same
        -- magnitude (the prior ABS() formulation did the latter). See #7.14. NULL-fallback
        -- caveat (COALESCE .. 10 scoring higher than a confirmed falling-cost 0) logged in
        -- #7.14, not fixed here — dormant today, same unknown-vs-evidenced class as #7.9/#7.12.
        LEAST(100, GREATEST(0,
            COALESCE(
                SAFE_DIVIDE(
                    COALESCE(ppi_value, 0) - COALESCE(ppi_3m_ago, ppi_value, 0),
                    NULLIF(COALESCE(ppi_3m_ago, 100), 0)
                ) * 500,   -- scale: 5% PPI move → score of 25; 20% move → score of 100
                10
            )
        ))                                          as cost_shock_score,

        -- ── 3. Margin Pressure Risk ───────────────────────────────────────────
        -- Retail price stagnant / falling while PPI rising (beyond the noise deadband)
        -- = margin being squeezed. ppi_mom_pct_change > var('ppi_deadband_pct') treats
        -- moves at or below the deadband as flat, not "rising" (see docs/threshold_
        -- decisions.md #7.8 for the natural-gap derivation of the 0.1 threshold).
        -- 50 = "trend unresolved" when either side has no prior-month reading to compare
        -- against — neutral, not a guess at compression or health (see #7.9).
        LEAST(100, GREATEST(0,
            CASE
                WHEN retail_price IS NULL OR ppi_value IS NULL THEN 30
                WHEN NOT has_prior_month_price OR NOT has_prior_month_ppi THEN 50
                WHEN retail_price_declining
                 AND ppi_mom_pct_change > {{ var('ppi_deadband_pct') }}
                    THEN 80  -- classic margin squeeze
                WHEN retail_price_declining
                    THEN 55  -- price compression only
                WHEN ppi_mom_pct_change > {{ var('ppi_deadband_pct') }}
                    THEN 40  -- cost rising; retail price holding for now
                ELSE
                    -- Healthy: price rising faster than costs. Percent-based (retail_mom_pct_change),
                    -- not raw dollars, so items at different price points aren't scored identically.
                    -- retail_healthy_pct_divisor (7.5) is a CONVENTION anchoring the median rising-
                    -- price move to the branch midpoint, not a data-discovered threshold — see
                    -- docs/threshold_decisions.md #7.13 for the derivation and its caveats.
                    GREATEST(0, 30 - retail_mom_pct_change * {{ var('retail_healthy_pct_divisor') }})
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
        ppi_signal_stale,
        has_prior_month_price,
        has_prior_month_ppi,
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
    ppi_signal_stale,
    has_prior_month_price,
    has_prior_month_ppi,
    overall_demand_gap_score,
    avg_search_interest,

    signal_type,
    score_version,
    data_note,
    load_timestamp

from scored
order by reference_month desc, overall_margin_risk_score desc
