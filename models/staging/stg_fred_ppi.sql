{{
    config(
        materialized = 'view',
        description  = 'FRED PCU311311 — Producer Price Index by Industry: Food Manufacturing. A producer-side input-cost index, used as the scoring series as of the PPI series swap (see docs/threshold_decisions.md #7.7). The prior scoring series, PCU42440042440012 (Grocery and Related Product Merchant Wholesalers — a wholesale-trade margin index, not a cost index), remains collected as a supplementary series but is no longer scored. Filtered to a single scoring series (var scoring_ppi_series_id) — every downstream consumer assumes exactly one series flows through this model.'
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

  Dedup: the QUALIFY below keeps the latest collected_at per (series_id, observation_date).
  Not required by the current collector (_upload uses WRITE_TRUNCATE against an undecorated
  destination, replacing the whole fred_ppi_raw table each run rather than appending), but
  this model doesn't rely on that write behavior staying that way. Guarded by
  tests/assert_fred_ppi_raw_no_duplicate_months.sql, which checks the raw source directly
  (checking this model would be circular - the QUALIFY guarantees it can never fail here).
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
    qualify ROW_NUMBER() OVER (
        PARTITION BY series_id, observation_date
        ORDER BY collected_at DESC
    ) = 1

)

select * from staged

