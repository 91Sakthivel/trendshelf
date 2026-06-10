{{
    config(
        materialized = 'view',
        enabled      = true,
        description  = 'Daily Google Trends interest score for "energy drinks" (US). Partial days excluded.'
    )
}}

/*
  Source: google_trends_raw
  To re-enable: change enabled = false  â†’  enabled = true  above.
*/

with source as (

    select * from {{ source('bronze', 'google_trends_raw') }}

),

staged as (

    select
        trend_date,
        interest_score,
        is_partial,
        search_keyword,
        category,
        geography,
        collected_at,
        CURRENT_TIMESTAMP()                                                         as load_timestamp,
        TO_HEX(MD5(CONCAT(search_keyword, '||', CAST(trend_date AS STRING))))      as trend_id
    from source
    where not is_partial

)

select * from staged

