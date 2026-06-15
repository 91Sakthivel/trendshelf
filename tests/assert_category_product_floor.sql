-- Singular test: fail if any category has fewer than 30 non-null-price products
-- in the latest collected partition. Catches API hiccups where a category
-- returns near-empty (e.g. token expiry mid-run, rate-limit truncation).
-- dbt treats any returned rows as a test failure.
select category, count(*) as n
from {{ ref('stg_kroger_prices') }}
where price_regular is not null
group by category
having count(*) < 30
