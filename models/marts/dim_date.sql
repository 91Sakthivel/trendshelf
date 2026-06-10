{{
    config(
        materialized = 'table',
        description  = 'Date dimension spanning the full range of dates across all staging tables.'
    )
}}

/*
  Generates one row per calendar day from the earliest date in any staging
  table to the latest, using BigQuery's GENERATE_DATE_ARRAY.
  date_key is the MD5 of the ISO date string so fact tables can join with
  TO_HEX(MD5(CAST(their_date AS STRING))).
*/

with date_bounds as (

    -- Collect min/max from every staging table, then take the overall envelope
    select
        MIN(min_d) as min_date,
        MAX(max_d) as max_date
    from (
        select MIN(observation_date)      as min_d,
               MAX(observation_date)      as max_d
        from {{ ref('stg_fred_ppi') }}

        union all

        select MIN(DATE(collected_at))    as min_d,
               MAX(DATE(collected_at))    as max_d
        from {{ ref('stg_kroger_prices') }}

        union all

        select MIN(reference_date)        as min_d,
               MAX(reference_date)        as max_d
        from {{ ref('stg_bls_cpi') }}
    )

),

date_spine as (

    select calendar_date
    from date_bounds
    cross join UNNEST(
        GENERATE_DATE_ARRAY(date_bounds.min_date, date_bounds.max_date)
    ) as calendar_date

)

select
    TO_HEX(MD5(CAST(calendar_date AS STRING)))  as date_key,
    calendar_date,
    EXTRACT(YEAR    FROM calendar_date)          as year,
    EXTRACT(QUARTER FROM calendar_date)          as quarter,
    EXTRACT(MONTH   FROM calendar_date)          as month,
    EXTRACT(ISOWEEK FROM calendar_date)          as week_of_year,
    EXTRACT(DAYOFWEEK FROM calendar_date)        as day_of_week,   -- 1 = Sunday, 7 = Saturday
    EXTRACT(DAYOFWEEK FROM calendar_date) IN (1, 7) as is_weekend,
    calendar_date = LAST_DAY(calendar_date)      as is_month_end
from date_spine
