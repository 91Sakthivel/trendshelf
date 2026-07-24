-- Singular test: fail if stg_fred_ppi returns zero rows, i.e. the configured
-- scoring_ppi_series_id is not present in fred_ppi_raw. A typo, a wrong series ID, a
-- discontinued FRED series, or a collector change that stops pulling this series would
-- all silently make stg_fred_ppi empty rather than raise any error - PPI would just
-- disappear and every downstream cost score (margin_pressure_proxy_score, cost_shock_score,
-- cost_passthrough_rate, ppi_trend_direction, normalized_ppi_growth_score) would silently
-- shift to its NULL-handling defaults with no signal that anything changed.
-- dbt treats any returned row as a test failure.
select 1 as violation
from (select count(*) as n from {{ ref('stg_fred_ppi') }})
where n = 0
