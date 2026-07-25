{{
    config(
        materialized = 'table',
        description  = 'Priority-ranked action queue — one row per (month × category × store) with a single first-match action.'
    )
}}

/*
  Grain: one row per (reference_month, category, store).

  Cascade order (first match wins):
    0. INVESTIGATE — data quality gate: retail_price missing or confidence < 45
    1. AVOID       — demand decaying OR margin critically squeezed
    2. EXPAND      — high readiness + confident data
    3. DEFEND      — competitive threat risk high
    4. PITCH       — readiness window with confirmed demand gap
    5. REPRICE     — overpriced vs CPI benchmark while demand gap exists
    6. CUTPROMO    — promo dependency too high to sustain
    7. MONITOR     — all scores in mid-range band
    8. INVESTIGATE — default catch-all when no condition fires

  New columns vs v2:
    recommended_action — canonical output name (same value as action_type)
    decision_strength  — Strong / Moderate / Weak (confidence × signal extremity)
    signal_type        — MEASURED (competitor price present) / PROXY (no competitor match)
*/

with expansion as (

    select * from {{ ref('mart_expansion_readiness') }}

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
        margin_pressure_proxy_score,
        cost_shock_score,
        promo_risk_score,
        overall_margin_risk_score,
        price_position_score,
        cost_passthrough_rate
    from {{ ref('mart_price_margin_scores') }}

),

confidence as (

    select
        signal_id,
        overall_confidence_score,
        confidence_level,
        data_completeness_score,
        row_level_source_coverage_score,
        source_count,
        competitor_avg_price,
        reason_codes
    from {{ ref('mart_confidence_layer') }}

),

-- ── Intelligence Layer v2: velocity, macro, and pricing CTEs ─────────────────

velocity as (

    select
        category,
        demand_velocity_direction,
        demand_trend_direction,
        seasonality_flag
    from {{ ref('int_demand_trend_features') }}

),

macro as (

    select
        signal_id,
        macro_risk_flag
    from {{ ref('fact_market_signals') }}

),

pricing_intel as (

    select
        store_id,
        category_name,
        competitive_intensity,
        premium_support_proxy_score,
        markdown_safety_score
    from {{ ref('mart_pricing_intelligence') }}

),

dims as (

    select
        c.category_name,
        c.parent_category,
        l.store_id,
        l.store_name,
        l.state,
        l.region
    from {{ ref('dim_category') }} c
    cross join {{ ref('dim_location') }} l

),

-- ── One row per signal with all scores joined ─────────────────────────────────

full_signals as (

    select
        e.signal_id,
        e.reference_month,
        e.category_name,
        e.store_id,
        e.state,
        e.region,
        d.store_name,
        d.parent_category,

        e.expansion_readiness_score,
        e.overall_demand_gap_score,
        e.avg_search_interest,
        e.shelf_product_count,
        e.search_to_shelf_gap,
        e.category_momentum_score,
        e.retail_price,

        r.demand_decay_risk,
        r.competitive_threat_risk,
        r.missed_demand_risk,
        r.phantom_distribution_risk,
        r.assortment_trap_risk,
        r.overall_risk_score,
        r.risk_level,

        p.margin_pressure_proxy_score,
        p.cost_shock_score,
        p.promo_risk_score,
        p.price_position_score,
        p.overall_margin_risk_score,
        p.cost_passthrough_rate,

        c.overall_confidence_score,
        c.confidence_level,
        c.data_completeness_score,
        c.row_level_source_coverage_score,
        c.source_count,
        c.competitor_avg_price,
        c.reason_codes,

        -- Intelligence layer v2: velocity, macro, and pricing dimensions
        v.demand_velocity_direction,
        v.demand_trend_direction,
        v.seasonality_flag,
        mac.macro_risk_flag,
        pi.competitive_intensity,
        pi.premium_support_proxy_score,
        pi.markdown_safety_score,

        -- Pre-computed opportunity composite for tier derivation
        ROUND(LEAST(100, GREATEST(0,
            e.overall_demand_gap_score                 * {{ var('opp_weight_demand') }}
            + e.expansion_readiness_score              * {{ var('opp_weight_expansion') }}
            + (100 - r.overall_risk_score)             * {{ var('opp_weight_pricing') }}
            + c.overall_confidence_score               * {{ var('opp_weight_confidence') }}
            + COALESCE(pi.premium_support_proxy_score, 50)     * {{ var('opp_weight_risk') }}
            + (100 - p.overall_margin_risk_score)      * {{ var('opp_weight_margin') }}
        )), 1)                                                   as overall_opportunity_score,

        e.load_timestamp

    from expansion  e
    left join risk         r   on e.signal_id     = r.signal_id
    left join price        p   on e.signal_id     = p.signal_id
    left join confidence   c   on e.signal_id     = c.signal_id
    left join dims         d   on e.category_name = d.category_name
                               and e.store_id      = d.store_id
    left join velocity     v   on e.category_name = v.category
    left join macro        mac on e.signal_id     = mac.signal_id
    left join pricing_intel pi on e.store_id      = pi.store_id
                               and e.category_name = pi.category_name

),

-- ── First-match cascade ───────────────────────────────────────────────────────

action_rows as (

    select
        *,
        CASE
            -- 0. INVESTIGATE: data quality gate — fire first before any business logic
            WHEN retail_price IS NULL
              OR overall_confidence_score < {{ var('investigate_confidence_threshold') }}
              OR data_completeness_score  < 60
                THEN 'INVESTIGATE'
            -- 1. AVOID: demand decaying or margins critically squeezed
            WHEN demand_decay_risk > 70 OR margin_pressure_proxy_score > {{ var('avoid_margin_pressure_threshold') }}
                THEN 'AVOID'
            -- 2. EXPAND: high readiness backed by confident data
            WHEN expansion_readiness_score > {{ var('expand_readiness_threshold') }} AND overall_confidence_score > {{ var('expand_confidence_threshold') }}
                THEN 'EXPAND'
            -- 3. DEFEND: competitor pricing is a real threat
            WHEN competitive_threat_risk > 70
                THEN 'DEFEND'
            -- 4. PITCH: good readiness window with a confirmed demand gap
            -- pitch_readiness_floor (65) is the same var used by MONITOR's ceiling below —
            -- see docs/threshold_decisions.md #7.15.
            WHEN expansion_readiness_score BETWEEN {{ var('pitch_readiness_floor') }} AND {{ var('expand_readiness_threshold') }} AND overall_demand_gap_score > 60
                THEN 'PITCH'
            -- 5. REPRICE: overpriced vs CPI benchmark while demand gap exists
            WHEN price_position_score > 70 AND overall_demand_gap_score > 50
                THEN 'REPRICE'
            -- 6. CUTPROMO: promo dependency too high to sustain
            WHEN promo_risk_score > 70
                THEN 'CUTPROMO'
            -- 7. MONITOR: data is solid but no threshold met — check monthly
            -- Same pitch_readiness_floor var as PITCH's floor above — must stay in sync
            -- so rows can't fall into a gap between the two actions. See #7.15.
            WHEN overall_confidence_score >= 60
             AND expansion_readiness_score < {{ var('pitch_readiness_floor') }}
                THEN 'MONITOR'
            -- 8. INVESTIGATE: default — no condition fired above
            ELSE 'INVESTIGATE'
        END                                                  as action_type

    from full_signals

)

-- ── Final output ──────────────────────────────────────────────────────────────

select
    ROW_NUMBER() OVER (
        ORDER BY
            CASE action_type
                WHEN 'AVOID'        THEN 1
                WHEN 'EXPAND'       THEN 2
                WHEN 'DEFEND'       THEN 3
                WHEN 'PITCH'        THEN 4
                WHEN 'REPRICE'      THEN 5
                WHEN 'CUTPROMO'     THEN 6
                WHEN 'MONITOR'      THEN 7
                ELSE 8
            END,
            reference_month DESC,
            overall_demand_gap_score DESC
    )                                                        as action_priority,

    -- Both column names: action_type for backward compat, recommended_action for new API
    action_type,
    action_type                                              as recommended_action,

    -- Urgency level per action type
    CASE action_type
        WHEN 'AVOID'       THEN 'URGENT'
        WHEN 'EXPAND'      THEN 'HIGH'
        WHEN 'DEFEND'      THEN 'HIGH'
        WHEN 'PITCH'       THEN 'HIGH'
        WHEN 'REPRICE'     THEN 'MEDIUM'
        WHEN 'CUTPROMO'    THEN 'MEDIUM'
        WHEN 'MONITOR'     THEN 'LOW'
        ELSE 'LOW'
    END                                                      as urgency,

    -- Signal strength: how confident and extreme the signal is
    CASE
        WHEN overall_confidence_score >= {{ var('confidence_high') }}
         AND (
             overall_demand_gap_score  > {{ var('demand_high_threshold') }} OR
             overall_demand_gap_score  < 35 OR
             expansion_readiness_score > 75 OR
             overall_risk_score        > 70
         )
            THEN 'Strong'
        WHEN overall_confidence_score >= 55
            THEN 'Moderate'
        ELSE 'Weak'
    END                                                      as decision_strength,

    -- Signal type: MEASURED when competitor pricing validates the signal
    CASE
        WHEN competitor_avg_price IS NOT NULL THEN 'MEASURED'
        ELSE 'PROXY'
    END                                                      as signal_type,

    reference_month,
    category_name,
    store_id,
    state,
    region,
    store_name,

    -- Plain-English action description
    CASE action_type
        WHEN 'AVOID' THEN CONCAT(
            'Do not expand — demand decay risk (',
            CAST(ROUND(demand_decay_risk, 0) AS STRING),
            '/100) or cost-pressure indicator (',
            CAST(ROUND(margin_pressure_proxy_score, 0) AS STRING),
            '/100) is critical; stabilise current shelf position first'
        )
        WHEN 'EXPAND' THEN CONCAT(
            'Pitch full expanded distribution to ',
            COALESCE(store_name, store_id),
            ' — readiness ',
            CAST(ROUND(expansion_readiness_score, 0) AS STRING),
            '/100 with HIGH data confidence (',
            CAST(ROUND(overall_confidence_score, 0) AS STRING),
            '/100)'
        )
        WHEN 'DEFEND' THEN CONCAT(
            'Competitive threat risk at ',
            CAST(ROUND(competitive_threat_risk, 0) AS STRING),
            '/100 — match competitor pricing or run a targeted defensive promotion at ',
            COALESCE(store_name, store_id)
        )
        WHEN 'PITCH' THEN CONCAT(
            'Prepare retailer sell-in deck — readiness ',
            CAST(ROUND(expansion_readiness_score, 0) AS STRING),
            '/100 with demand gap of ',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            '/100; request buyer meeting within 30 days'
        )
        WHEN 'REPRICE' THEN CONCAT(
            'Price position score ',
            CAST(ROUND(price_position_score, 0) AS STRING),
            '/100 signals overpricing vs CPI benchmark — review shelf price to unlock demand gap of ',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            '/100'
        )
        WHEN 'CUTPROMO' THEN CONCAT(
            'Promo risk score ',
            CAST(ROUND(promo_risk_score, 0) AS STRING),
            '/100 — reduce promotional depth or frequency to protect margin and brand price perception'
        )
        WHEN 'MONITOR' THEN CONCAT(
            'All scores mid-range (demand gap ',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            ', risk ',
            CAST(ROUND(overall_risk_score, 0) AS STRING),
            ', readiness ',
            CAST(ROUND(expansion_readiness_score, 0) AS STRING),
            ') — no immediate action; refresh data monthly'
        )
        ELSE CONCAT(
            'Data quality check required for ',
            category_name,
            ' at ',
            COALESCE(store_name, store_id),
            ' — confidence ',
            CAST(ROUND(overall_confidence_score, 0) AS STRING),
            '/100; resolve missing signals before acting'
        )
    END                                                      as action_description,

    -- Expected impact if action is taken
    CASE action_type
        WHEN 'AVOID' THEN
            'Prevents brand equity and margin damage during declining consumer interest; avoids shelf resets that could strand inventory'
        WHEN 'EXPAND' THEN CONCAT(
            'Capturing the ',
            CAST(ROUND(search_to_shelf_gap, 0) AS STRING),
            '-point shelf gap could drive 15-25% volume uplift over next 2 quarters'
        )
        WHEN 'DEFEND' THEN
            'Matching competitor price or running a defensive promotion can halt market share loss in current shelf'
        WHEN 'PITCH' THEN
            'Securing 2+ additional SKU facings could recover missed demand and increase category contribution margin'
        WHEN 'REPRICE' THEN
            'Aligning price to consumer benchmarks could reduce price elasticity drag and lift velocity by 10-20%'
        WHEN 'CUTPROMO' THEN
            'Reducing promo depth by 30% or shifting to non-price promotion improves margin by 2-4 points per unit'
        WHEN 'MONITOR' THEN
            'No immediate financial impact — monitoring catches early trend shifts before they become costly'
        ELSE
            'Resolving data quality issues will unlock clearer signals and enable confident decision-making'
    END                                                      as expected_impact,

    -- Plain-English justification for the action recommendation
    CASE action_type
        WHEN 'AVOID' THEN CONCAT(
            'Demand decaying or cost-pressure indicator elevated (decay risk ',
            CAST(ROUND(demand_decay_risk, 0) AS STRING),
            ', cost-pressure indicator ',
            CAST(ROUND(margin_pressure_proxy_score, 0) AS STRING),
            '/100). Not the right time to act — stabilise current position first.'
        )
        WHEN 'EXPAND' THEN CONCAT(
            'Demand strong and shelf coverage weak (readiness ',
            CAST(ROUND(expansion_readiness_score, 0) AS STRING),
            '/100, confidence ',
            CAST(ROUND(overall_confidence_score, 0) AS STRING),
            '/100). Ready to expand distribution to new doors.'
        )
        WHEN 'DEFEND' THEN CONCAT(
            'Competitor threat elevated (competitive threat risk ',
            CAST(ROUND(competitive_threat_risk, 0) AS STRING),
            '/100). Protect current shelf position with pricing or promotional response.'
        )
        WHEN 'PITCH' THEN CONCAT(
            'Demand growing and a shelf gap exists (readiness ',
            CAST(ROUND(expansion_readiness_score, 0) AS STRING),
            '/100, demand gap ',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            '/100). Worth pitching expanded distribution to the buyer now.'
        )
        WHEN 'REPRICE' THEN CONCAT(
            'Kroger priced above benchmark while demand gap exists (price position ',
            CAST(ROUND(price_position_score, 0) AS STRING),
            '/100, demand gap ',
            CAST(ROUND(overall_demand_gap_score, 0) AS STRING),
            '/100). A price adjustment would unlock latent consumer demand.'
        )
        WHEN 'CUTPROMO' THEN CONCAT(
            'Promo dependency high with margin under pressure (promo risk ',
            CAST(ROUND(promo_risk_score, 0) AS STRING),
            '/100). Stop discounting to protect long-term margin and price perception.'
        )
        WHEN 'MONITOR' THEN CONCAT(
            'Data confidence solid (confidence ',
            CAST(ROUND(overall_confidence_score, 0) AS STRING),
            '/100) but no threshold met for immediate action. Revisit next month with fresh data.'
        )
        ELSE CONCAT(
            'Data confidence too low (confidence ',
            CAST(ROUND(overall_confidence_score, 0) AS STRING),
            '/100) or key signals missing. Verify all data sources before deciding.'
        )
    END                                                      as action_reason,

    -- Short machine-readable tag for the triggering condition
    CASE action_type
        WHEN 'AVOID'       THEN 'DEMAND_DECAY_OR_MARGIN_RISK'
        WHEN 'EXPAND'      THEN 'HIGH_DEMAND_LOW_SHELF'
        WHEN 'DEFEND'      THEN 'COMPETITOR_THREAT_HIGH'
        WHEN 'PITCH'       THEN 'DEMAND_RISING_SHELF_GAP'
        WHEN 'REPRICE'     THEN 'OVERPRICED_VS_COMPETITOR'
        WHEN 'CUTPROMO'    THEN 'PROMO_RISK_MARGIN_PRESSURE'
        WHEN 'MONITOR'     THEN 'MIXED_SIGNALS'
        ELSE 'LOW_CONFIDENCE'
    END                                                      as reason_code,

    -- Score that triggered the action
    ROUND(
        CASE action_type
            WHEN 'AVOID'       THEN GREATEST(demand_decay_risk, margin_pressure_proxy_score)
            WHEN 'EXPAND'      THEN expansion_readiness_score
            WHEN 'DEFEND'      THEN competitive_threat_risk
            WHEN 'PITCH'       THEN expansion_readiness_score
            WHEN 'REPRICE'     THEN price_position_score
            WHEN 'CUTPROMO'    THEN promo_risk_score
            WHEN 'MONITOR'     THEN overall_demand_gap_score
            ELSE overall_confidence_score
        END,
    2)                                                       as driving_score,

    CASE action_type
        WHEN 'AVOID'       THEN 'mart_shelfrisk_scores / mart_price_margin_scores'
        WHEN 'EXPAND'      THEN 'mart_expansion_readiness'
        WHEN 'DEFEND'      THEN 'mart_shelfrisk_scores'
        WHEN 'PITCH'       THEN 'mart_expansion_readiness'
        WHEN 'REPRICE'     THEN 'mart_price_margin_scores'
        WHEN 'CUTPROMO'    THEN 'mart_price_margin_scores'
        WHEN 'MONITOR'     THEN 'mart_demand_gap_scores'
        ELSE 'mart_confidence_layer'
    END                                                      as source_model,

    overall_confidence_score,
    overall_demand_gap_score,
    overall_risk_score,
    overall_margin_risk_score,
    row_level_source_coverage_score,
    reason_codes,

    -- ── Intelligence Layer v2 columns ─────────────────────────────────────────

    -- Passthrough dimensions used by downstream queries and dashboards
    demand_velocity_direction,
    demand_trend_direction,
    seasonality_flag,
    macro_risk_flag,
    competitive_intensity,
    premium_support_proxy_score,
    markdown_safety_score,

    overall_opportunity_score,

    CASE
        WHEN overall_opportunity_score >= {{ var('opp_tier_prime') }} THEN 'Prime'
        WHEN overall_opportunity_score >= {{ var('opp_tier_solid') }} THEN 'Solid'
        WHEN overall_opportunity_score >= {{ var('opp_tier_watch') }} THEN 'Watch'
        ELSE 'Low'
    END                                                          as opportunity_tier,

    CASE
        WHEN demand_velocity_direction = 'Accelerating'
            THEN 'Growth Accelerating'
        WHEN demand_velocity_direction = 'Decelerating'
         AND demand_trend_direction IN ('Rising', 'Stable')
            THEN 'Growth Slowing'
        WHEN demand_velocity_direction = 'Decelerating'
            THEN 'Declining'
        WHEN COALESCE(competitive_intensity, 'Sparse') IN ('Sparse', 'Emerging')
            THEN 'Emerging'
        ELSE 'Mature'
    END                                                          as category_lifecycle,

    CASE
        WHEN COALESCE(seasonality_flag, 'Normal') = 'Possible Seasonal Spike'
         AND overall_confidence_score < {{ var('confidence_high') }}
         AND action_type IN ('EXPAND', 'PITCH')
            THEN 'MONITOR'
        ELSE action_type
    END                                                          as seasonality_adjusted_action,

    CASE
        WHEN COALESCE(seasonality_flag, 'Normal') = 'Possible Seasonal Spike'
            THEN 'SEASONAL_SPIKE'
        WHEN demand_velocity_direction = 'Accelerating'
            THEN 'ACCELERATING'
        WHEN demand_velocity_direction = 'Decelerating'
            THEN 'DECELERATING'
        WHEN overall_demand_gap_score >= {{ var('demand_high_threshold') }}
            THEN 'HIGH_STABLE'
        WHEN overall_demand_gap_score >= {{ var('demand_medium_threshold') }}
            THEN 'MEDIUM_STABLE'
        WHEN demand_velocity_direction IS NOT NULL
            THEN 'LOW_STABLE'
        ELSE 'NO_DATA'
    END                                                          as demand_reason_code,

    CASE
        WHEN COALESCE(macro_risk_flag, 'Stable Macro') = 'High Inflation Risk'
            THEN 'HIGH_INFLATION_RISK'
        WHEN COALESCE(macro_risk_flag, 'Stable Macro') = 'Cost Pressure'
            THEN 'COST_PRESSURE'
        WHEN COALESCE(macro_risk_flag, 'Stable Macro') = 'Cost Relief'
            THEN 'COST_RELIEF'
        WHEN COALESCE(competitive_intensity, 'Sparse') = 'Saturated'
            THEN 'SATURATED_MARKET'
        WHEN overall_risk_score > 70
            THEN 'HIGH_OPERATIONAL_RISK'
        ELSE 'STABLE'
    END                                                          as risk_reason_code,

    'v4_robust_heuristic_calibration'                         as score_version,
    load_timestamp

from action_rows
order by overall_opportunity_score DESC, overall_confidence_score DESC
