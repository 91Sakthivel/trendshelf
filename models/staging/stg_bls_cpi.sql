{{
    config(
        materialized = 'view',
        description  = 'Monthly CPI for Food at home (BLS CUUR0000SAF11). Suppressed months have NULL cpi_value.'
    )
}}

/*
  Source: bls_cpi_raw
  Data is already flat and typed by collect_apis.py:
    reference_date DATE, cpi_value FLOAT64 (NULL when suppressed),
    is_suppressed BOOL, is_latest BOOL.
  The "-" sentinel was already converted to NULL during collection.
*/

with source as (

    select * from {{ source('bronze', 'bls_cpi_raw') }}

),

staged as (

    select
        reference_year,
        period_code,
        period_name,
        reference_date,
        cpi_value,
        is_suppressed,
        is_latest,
        series_id,
        collected_at,
        CURRENT_TIMESTAMP()                                                          as load_timestamp,
        -- Surrogate key: series + year + period
        TO_HEX(MD5(CONCAT(
            series_id, '||',
            CAST(reference_year AS STRING), '||',
            period_code
        )))                                                                          as cpi_id
    from source

)

select * from staged

