-- Singular test: fail if fred_ppi_raw ever has more than one row for the same
-- (series_id, observation_date). stg_fred_ppi silently dedupes to the latest
-- collected_at per pair, which would hide a collector regression (e.g. a switch
-- from WRITE_TRUNCATE to WRITE_APPEND, or an added partition decorator) rather
-- than surface it. Checking the raw source is deliberate: checking stg_fred_ppi
-- instead would be circular, since its own QUALIFY guarantees it can never fail.
-- dbt treats any returned row as a test failure.
select series_id, observation_date, count(*) as n
from {{ source('bronze', 'fred_ppi_raw') }}
group by series_id, observation_date
having count(*) > 1
