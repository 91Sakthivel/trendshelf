{{
    config(
        materialized = 'table',
        description  = 'Expansion readiness scoring: synthesises demand, risk, margin, and confidence into a retailer pitch priority ranking.'
    )
}}

/*
  Grain: reference_month × category × store (mirrors fact_market_signals).

  Outputs:
    region_opportunity_score      — demand attractiveness of the region
    store_market_fit_score        — how well the store's profile fits the category
    expansion_readiness_score     — composite go/no-go score (0-100)
    retailer_pitch_priority       — ROW_NUMBER() rank (1 = most ready to pitch)
    recommended_action            — plain-English action string (cascade logic)
*/

with demand as (

    select * from {{ ref('mart_demand_gap_scores') }}

),

risk as (

    select
        signal_id,
        missed_demand_risk,
        demand_decay_risk,
        phantom_distribution_risk,
        competitive_threat_risk,
        assortment_trap_risk,
        overall_risk_score,
        risk_level
    from {{ ref('mart_shelfrisk_scores') }}

),

price as (

    select
        signal_id,
        price_position_score,
        cost_shock_score,
        margin_pressure_risk,
        promo_risk_score,
        overall_margin_risk_score
    from {{ ref('mart_price_margin_scores') }}

),

confidence as (

    select
        signal_id,
        data_completeness_score,
        signal_agreement_score,
        data_freshness_score,
        source_count,
        overall_confidence_score,
        confidence_level,
        reason_codes
    from {{ ref('mart_confidence_layer') }}

),

-- ── Join all four scoring layers ──────────────────────────────────────────────

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
        d.promo_depth_pct,
        d.category_momentum_score,
        d.search_to_shelf_gap,
        d.intent_quality_score,
        d.overall_demand_gap_score,
        d.signal_type,
        d.load_timestamp,

        r.missed_demand_risk,
        r.demand_decay_risk,
        r.overall_risk_score,
        r.risk_level,

        p.price_position_score,
        p.margin_pressure_risk,
        p.promo_risk_score,
        p.overall_margin_risk_score,

        c.data_completeness_score,
        c.overall_confidence_score,
        c.confidence_level,
        c.source_count,
        c.reason_codes

    from demand    d
    left join risk       r on d.signal_id = r.signal_id
    left join price      p on d.signal_id = p.signal_id
    left join confidence c on d.signal_id = c.signal_id

),

scored as (

    select
        signal_id,
        reference_month,
        category_name,
        store_id,
        state,
        region,

        -- ── 1. Region Opportunity Score ───────────────────────────────────────
        -- Blends demand gap with search interest and category momentum.
        -- High score = region has unmet demand and rising consumer interest.
        LEAST(100, GREATEST(0,
            overall_demand_gap_score * 0.50 +
            category_momentum_score  * 0.30 +
            intent_quality_score     * 0.20
        ))                                           as region_opportunity_score,

        -- ── 2. Store Market Fit Score ─────────────────────────────────────────
        -- Measures how attractive this specific store is for expansion.
        -- Penalises high risk and margin pressure; rewards price position.
        LEAST(100, GREATEST(0,
            -- Base: search-to-shelf gap (opportunity not yet captured)
            search_to_shelf_gap * 0.40 +
            -- Reward: good price position (brand can earn margin here)
            price_position_score * 0.25 +
            -- Penalise: margin risk reduces attractiveness
            (100 - margin_pressure_risk) * 0.20 +
            -- Penalise: promo dependency reduces long-term fit
            (100 - promo_risk_score) * 0.15
        ))                                           as store_market_fit_score,

        -- raw scores carried for composite
        overall_demand_gap_score,
        overall_risk_score,
        overall_margin_risk_score,
        overall_confidence_score,
        data_completeness_score,
        category_momentum_score,
        search_to_shelf_gap,
        intent_quality_score,
        price_position_score,
        margin_pressure_risk,
        promo_risk_score,
        missed_demand_risk,
        demand_decay_risk,
        risk_level,
        confidence_level,
        source_count,
        reason_codes,

        avg_search_interest,
        shelf_product_count,
        retail_price,
        ppi_value,
        cpi_value,
        promo_depth_pct,
        signal_type,
        load_timestamp

    from base

),

-- ── Expansion readiness composite ─────────────────────────────────────────────

readiness as (

    select
        *,
        ROUND(LEAST(100, GREATEST(0,
            -- Opportunity is the primary driver
            region_opportunity_score * 0.35 +
            store_market_fit_score   * 0.30 +
            -- Low risk amplifies readiness; high risk deflates it
            (100 - overall_risk_score) * 0.20 +
            -- Confidence in the data is a prerequisite gating factor
            overall_confidence_score * 0.15
        )), 2)                                       as expansion_readiness_score
    from scored

)

-- ── Final: add ranking + recommended action ───────────────────────────────────

select
    signal_id,
    reference_month,
    category_name,
    store_id,
    state,
    region,

    ROUND(region_opportunity_score, 2)               as region_opportunity_score,
    ROUND(store_market_fit_score,   2)               as store_market_fit_score,
    expansion_readiness_score,

    -- Priority rank: 1 = most ready to pitch to retailer this month
    ROW_NUMBER() OVER (
        PARTITION BY reference_month
        ORDER BY expansion_readiness_score DESC
    )                                                as retailer_pitch_priority,

    -- Cascade action logic (evaluated top-to-bottom, first match wins)
    CASE
        WHEN expansion_readiness_score >= 70
         AND overall_confidence_score  >= 60
            THEN 'PITCH NOW: High readiness and confident data — present expansion business case to buyer'

        WHEN expansion_readiness_score >= 55
         AND risk_level = 'LOW'
            THEN 'PREPARE PITCH: Good readiness with low risk — finalise sell-in deck and request buyer meeting'

        WHEN expansion_readiness_score >= 55
         AND risk_level = 'MEDIUM'
            THEN 'MONITOR AND PREPARE: Readiness is good but some risk flags — address shelf gaps before pitching'

        WHEN demand_decay_risk > 60
            THEN 'DEFEND FIRST: Demand is decaying — focus on retaining current shelf before seeking new distribution'

        WHEN overall_risk_score >= 65
            THEN 'REMEDIATE RISK: High overall risk — resolve shelf and price issues before expansion'

        WHEN overall_confidence_score < 40
            THEN 'COLLECT MORE DATA: Low confidence in signals — refresh all API sources and re-score'

        WHEN margin_pressure_risk >= 70
            THEN 'FIX MARGINS: Margin squeeze detected — negotiate COGS or adjust shelf price before expansion'

        WHEN expansion_readiness_score >= 40
            THEN 'BUILD CASE: Moderate readiness — gather 2 more months of data to strengthen expansion story'

        ELSE 'WATCH AND WAIT: Insufficient signals for expansion at this time — continue monitoring'
    END                                              as recommended_action,

    overall_demand_gap_score,
    overall_risk_score,
    overall_margin_risk_score,
    overall_confidence_score,
    data_completeness_score,
    category_momentum_score,
    search_to_shelf_gap,
    price_position_score,
    margin_pressure_risk,
    promo_risk_score,
    missed_demand_risk,
    demand_decay_risk,
    risk_level,
    confidence_level,
    source_count,
    reason_codes,

    avg_search_interest,
    shelf_product_count,
    retail_price,
    ppi_value,
    cpi_value,
    promo_depth_pct,

    signal_type,
    -- expansion_readiness_score is model-derived: computed from weighted inputs (demand,
    -- risk, margin, confidence), not directly measured from a single source.
    'Model-derived'                                  as expansion_signal_type,
    'v4_statistical_calibration'                     as score_version,
    CONCAT(
        'Expansion score based on ',
        CAST(source_count AS STRING),
        ' of 4 data sources. Confidence: ',
        confidence_level,
        '. Risk level: ',
        risk_level
    )                                                as data_note,
    load_timestamp

from readiness
order by reference_month desc, expansion_readiness_score desc
