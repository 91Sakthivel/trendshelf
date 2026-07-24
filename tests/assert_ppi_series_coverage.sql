-- Singular test: fail if stg_fred_ppi has fewer than var('min_ppi_monthly_rows') monthly
-- rows. int_macro_trend_features.sql's ppi_yoy_value = LAG(ppi_value, 12) needs 13 rows
-- of history for even the most recent month to produce a non-null year-over-year
-- comparison (12 preceding rows plus the current row); below that threshold the entire
-- YoY feature is unconditionally NULL for every row - a silent truncation (partial pull,
-- quota cutoff, or a collector regression), not an explicit failure.
-- dbt treats any returned row as a test failure.
select 1 as violation
from (select count(*) as n from {{ ref('stg_fred_ppi') }})
where n < {{ var('min_ppi_monthly_rows') }}
