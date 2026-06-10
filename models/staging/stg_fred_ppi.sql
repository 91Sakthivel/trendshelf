{{
    config(
        materialized = 'view',
        description  = 'Monthly Producer Price Index for energy drink wholesalers (FRED PCU42440042440012).'
    )
}}

/*
  Source: fred_ppi_raw
  Data is already flat and typed by collect_apis.py:
    observation_date DATE, ppi_value FLOAT64, series_id STRING, collected_at TIMESTAMP
*/

with source as (

    select * from {{ source('bronze', 'fred_ppi_raw') }}

),

staged as (

    select
        observation_date,
        ppi_value,
        series_id,
        collected_at,
        CURRENT_TIMESTAMP()                                                           as load_timestamp,
        -- Surrogate key: series + observation date
        TO_HEX(MD5(CONCAT(series_id, '||', CAST(observation_date AS STRING))))       as ppi_id
    from source
    where observation_date >= '2025-01-01'

)

select * from staged

