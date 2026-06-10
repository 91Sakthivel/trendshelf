{{
    config(
        materialized = 'table',
        description  = 'PPI and CPI rolling windows and trend direction signals. One row per reference_month. Used by fact_market_signals for latest-as-of join.'
    )
}}

with fred_monthly as (

    select
        DATE_TRUNC(observation_date, MONTH)     as reference_month,
        ppi_value
    from {{ ref('stg_fred_ppi') }}

),

bls_monthly as (

    select
        reference_date                          as reference_month,
        cpi_value
    from {{ ref('stg_bls_cpi') }}
    where not is_suppressed

),

ppi_windowed as (

    select
        reference_month,
        ppi_value,
        AVG(ppi_value) OVER (
            ORDER BY reference_month
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        )                                       as ppi_recent_3mo_avg,
        AVG(ppi_value) OVER (
            ORDER BY reference_month
            ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
        )                                       as ppi_prior_3mo_avg,
        LAG(ppi_value, 12) OVER (
            ORDER BY reference_month
        )                                       as ppi_yoy_value
    from fred_monthly

),

cpi_windowed as (

    select
        reference_month,
        cpi_value,
        AVG(cpi_value) OVER (
            ORDER BY reference_month
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        )                                       as cpi_recent_3mo_avg,
        AVG(cpi_value) OVER (
            ORDER BY reference_month
            ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
        )                                       as cpi_prior_3mo_avg,
        LAG(cpi_value, 12) OVER (
            ORDER BY reference_month
        )                                       as cpi_yoy_value
    from bls_monthly

),

final as (

    select
        p.reference_month,

        -- PPI metrics
        p.ppi_value,
        p.ppi_recent_3mo_avg - p.ppi_prior_3mo_avg                                 as ppi_3mo_trend,
        SAFE_DIVIDE(
            p.ppi_value - p.ppi_yoy_value, p.ppi_yoy_value
        ) * 100                                                                     as ppi_yoy_change,
        CASE
            WHEN p.ppi_recent_3mo_avg - p.ppi_prior_3mo_avg >  0.5 THEN 'Rising'
            WHEN p.ppi_recent_3mo_avg - p.ppi_prior_3mo_avg < -0.5 THEN 'Falling'
            WHEN p.ppi_prior_3mo_avg IS NULL                        THEN NULL
            ELSE 'Stable'
        END                                                                         as ppi_trend_direction,
        -- 0-100 score: 50 = neutral, >50 = inflationary pressure, <50 = deflation
        LEAST(100, GREATEST(0,
            50.0 + (p.ppi_recent_3mo_avg - p.ppi_prior_3mo_avg) * 10.0
        ))                                                                          as normalized_ppi_growth_score,

        -- CPI metrics
        c.cpi_value,
        c.cpi_recent_3mo_avg - c.cpi_prior_3mo_avg                                 as cpi_3mo_trend,
        SAFE_DIVIDE(
            c.cpi_value - c.cpi_yoy_value, c.cpi_yoy_value
        ) * 100                                                                     as cpi_yoy_change,
        CASE
            WHEN c.cpi_recent_3mo_avg - c.cpi_prior_3mo_avg >  0.5 THEN 'Rising'
            WHEN c.cpi_recent_3mo_avg - c.cpi_prior_3mo_avg < -0.5 THEN 'Falling'
            WHEN c.cpi_prior_3mo_avg IS NULL                        THEN NULL
            ELSE 'Stable'
        END                                                                         as cpi_trend_direction,
        LEAST(100, GREATEST(0,
            50.0 + (c.cpi_recent_3mo_avg - c.cpi_prior_3mo_avg) * 10.0
        ))                                                                          as normalized_cpi_growth_score

    from ppi_windowed p
    left join cpi_windowed c on p.reference_month = c.reference_month

)

select * from final
order by reference_month
