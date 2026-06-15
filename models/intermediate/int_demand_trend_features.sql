{{
    config(
        materialized = 'table',
        description  = 'Google Trends 4-week momentum, level, and seasonality by category. One row per category. Collapsed from weekly grain — represents the current trend state for each category.'
    )
}}

/*
  Grain: one row per category (10 categories total).
  Joins into fact_market_signals on category; all months within a category
  receive the same trend features (current-snapshot semantics).

  Week ranking is descending by trend_date so:
    week_rank 1-4  = most recent 4 weeks  (recent momentum window)
    week_rank 5-8  = preceding 4 weeks    (prior momentum window)
    week_rank 49-52 = same period ~1 year ago (seasonality baseline)
*/

with weekly as (

    select
        category,
        trend_date,
        interest_score,
        ROW_NUMBER() OVER (
            PARTITION BY category
            ORDER BY trend_date DESC
        )                                           as week_rank
    from {{ ref('stg_google_trends') }}
    where interest_score is not null

),

-- ── 4-week rolling windows ────────────────────────────────────────────────────

latest_week as (

    select category, interest_score as latest_trends_value
    from weekly
    where week_rank = 1

),

recent_4wk as (

    select
        category,
        AVG(interest_score)                         as trends_recent_4wk_avg
    from weekly
    where week_rank <= 4
    group by category

),

prior_4wk as (

    select
        category,
        AVG(interest_score)                         as trends_prior_4wk_avg
    from weekly
    where week_rank between 5 and 8
    group by category

),

earlier_4wk as (

    select
        category,
        AVG(interest_score)                         as earlier_4wk_avg
    from weekly
    where week_rank between 9 and 12
    group by category

),

-- ── Same 4-week window ~1 year ago (weeks 49-52 from most recent) ─────────────

prior_year_4wk as (

    select
        category,
        AVG(interest_score)                         as prior_year_4wk_avg
    from weekly
    where week_rank between 49 and 52
    group by category

),

-- ── OLS slope velocity over last 8 weeks ─────────────────────────────────────
-- Replaces the 3-point second-derivative (demand_velocity_score) which is noise-
-- fragile — one spike week flips the sign. OLS gives a smoothed trend direction.
-- x = week index (1 = oldest of last 8, 8 = most recent); standard OLS formula:
--   slope = (E[xy] - E[x]·E[y]) / (E[x²] - E[x]²)
-- demand_noise = STDDEV(interest) over the same 8 weeks (normalises the slope).

last8 as (

    select
        category,
        interest_score,
        ROW_NUMBER() OVER (
            PARTITION BY category
            ORDER BY trend_date
        )                                           as x
    from weekly
    where week_rank <= 8

),

slope_calc as (

    select
        category,
        SAFE_DIVIDE(
            AVG(x * interest_score) - AVG(x) * AVG(interest_score),
            NULLIF(AVG(x * x) - AVG(x) * AVG(x), 0)
        )                                           as demand_slope_per_week,
        STDDEV(interest_score)                      as demand_noise
    from last8
    group by category

),

-- ── Category-level stats across full 12-month window ─────────────────────────

category_stats as (

    select
        category,
        MAX(interest_score)                         as max_interest_12m,
        MIN(interest_score)                         as min_interest_12m,
        COUNT(distinct trend_date)                  as weeks_with_data
    from {{ ref('stg_google_trends') }}
    where interest_score is not null
    group by category

),

-- ── Assemble final features ───────────────────────────────────────────────────

final as (

    select
        r.category,

        -- Raw trend values
        lw.latest_trends_value,
        r.trends_recent_4wk_avg,
        p.trends_prior_4wk_avg,
        ew.earlier_4wk_avg,
        r.trends_recent_4wk_avg - p.trends_prior_4wk_avg                           as google_trends_4wk_momentum,

        -- Level score: position within the category's 12-month observed range (0-100)
        LEAST(100, GREATEST(0,
            SAFE_DIVIDE(
                r.trends_recent_4wk_avg - cs.min_interest_12m,
                NULLIF(cs.max_interest_12m - cs.min_interest_12m, 0)
            ) * 100.0
        ))                                                                          as google_trends_level_score,

        -- Momentum score: deviation from prior period, centered at 50 (0-100)
        LEAST(100, GREATEST(0,
            50.0 + (r.trends_recent_4wk_avg - p.trends_prior_4wk_avg) * 2.0
        ))                                                                          as google_trends_momentum_score,

        -- Trend direction
        CASE
            WHEN r.trends_recent_4wk_avg - p.trends_prior_4wk_avg >  5 THEN 'Rising'
            WHEN r.trends_recent_4wk_avg - p.trends_prior_4wk_avg < -5 THEN 'Falling'
            WHEN p.trends_prior_4wk_avg IS NULL                         THEN NULL
            ELSE 'Stable'
        END                                                                         as demand_trend_direction,

        -- Demand velocity: rate of change of momentum (second derivative of trend)
        -- LEGACY: superseded by demand_slope_per_week (OLS over 8 weeks, noise-normalized).
        -- Retained for downstream compatibility; do not use in new logic.
        ROUND(
            (r.trends_recent_4wk_avg - p.trends_prior_4wk_avg)
            - (p.trends_prior_4wk_avg - ew.earlier_4wk_avg),
        2)                                                                          as demand_velocity_score,

        CASE
            WHEN p.trends_prior_4wk_avg IS NULL OR ew.earlier_4wk_avg IS NULL
                THEN 'Stable Velocity'
            WHEN (r.trends_recent_4wk_avg - p.trends_prior_4wk_avg)
               - (p.trends_prior_4wk_avg - ew.earlier_4wk_avg) > 5
                THEN 'Accelerating'
            WHEN (r.trends_recent_4wk_avg - p.trends_prior_4wk_avg)
               - (p.trends_prior_4wk_avg - ew.earlier_4wk_avg) < -5
                THEN 'Decelerating'
            ELSE 'Stable Velocity'
        END                                                                         as demand_velocity_direction,

        -- OLS slope velocity (supersedes demand_velocity_score as primary signal)
        ROUND(sc.demand_slope_per_week, 3)                                          as demand_slope_per_week,
        ROUND(SAFE_DIVIDE(sc.demand_slope_per_week,
              NULLIF(sc.demand_noise, 0)), 3)                                        as demand_slope_to_noise,

        -- demand_state: noise-normalised slope direction (t-stat-like ratio vs STDDEV)
        -- 'Insufficient' only when STDDEV = 0 (all 8 weeks share identical interest score)
        CASE
            WHEN sc.demand_noise IS NULL
              OR sc.demand_noise = 0
                THEN 'Insufficient'
            WHEN SAFE_DIVIDE(sc.demand_slope_per_week, NULLIF(sc.demand_noise, 0))
                 >  {{ var('demand_slope_rising_threshold') }}
                THEN 'Rising'
            WHEN SAFE_DIVIDE(sc.demand_slope_per_week, NULLIF(sc.demand_noise, 0))
                 < -{{ var('demand_slope_rising_threshold') }}
                THEN 'Falling'
            ELSE 'Stable'
        END                                                                         as demand_state,

        -- Seasonality: compare recent 4 weeks to same period last year
        CASE
            WHEN py.prior_year_4wk_avg IS NULL
                THEN 'Insufficient History'
            WHEN r.trends_recent_4wk_avg > py.prior_year_4wk_avg * 1.20
                THEN 'Possible Seasonal Spike'
            ELSE 'Steady Demand'
        END                                                                         as seasonality_flag,

        CASE
            WHEN py.prior_year_4wk_avg IS NULL                          THEN 'Unknown'
            WHEN r.trends_recent_4wk_avg > py.prior_year_4wk_avg * 1.20 THEN 'Yes'
            ELSE 'No'
        END                                                                         as is_seasonal,

        -- Coverage and range stats (used by intent_quality_score downstream)
        cs.max_interest_12m,
        cs.min_interest_12m,
        cs.weeks_with_data

    from recent_4wk        r
    left join latest_week   lw  on r.category = lw.category
    left join prior_4wk     p   on r.category = p.category
    left join earlier_4wk   ew  on r.category = ew.category
    left join prior_year_4wk py on r.category = py.category
    left join category_stats cs on r.category = cs.category
    left join slope_calc    sc  on r.category = sc.category

)

select * from final
