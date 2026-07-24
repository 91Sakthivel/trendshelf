-- Singular test: fail if any category_name in mart_pricing_intelligence has no entry
-- in the category_elasticity STRUCT. Detection: the COALESCE fallback sets
-- category_premium_tolerance_prior_score = 50, and no real STRUCT entry uses 50
-- (actual values: 25, 30, 35, 55, 70, 75, 80). A matched category never produces 50.
-- dbt treats any returned rows as a test failure.
select distinct category_name
from {{ ref('mart_pricing_intelligence') }}
where category_premium_tolerance_prior_score = 50
