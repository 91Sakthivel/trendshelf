{{
    config(
        materialized = 'view',
        description  = 'Monthly Producer Price Index for energy drink wholesalers (FRED PCU42440042440012). Filtered to a single scoring series (var scoring_ppi_series_id) — every downstream consumer assumes exactly one series flows through this model.'
    )
}}

/*
  Source: fred_ppi_raw
  Data is already flat and typed by collect_apis.py:
    observation_date DATE, ppi_value FLOAT64, series_id STRING, collected_at TIMESTAMP

  Single-series contract: fred_ppi_raw may carry more than one FRED series (the collector
  can pull additional series without switching scoring to them). This model filters down to
  exactly the one series named by var scoring_ppi_series_id, so every downstream model
  (fact_market_signals, mart_price_margin_scores, mart_shelfrisk_scores,
  int_macro_trend_features) can assume a single-series monthly time series with no
  series_id filter or PARTITION BY of its own. Guarded by tests/assert_ppi_series_resolves.sql
  and tests/assert_ppi_series_coverage.sql.
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
      and series_id = '{{ var("scoring_ppi_series_id") }}'

)

select * from staged

