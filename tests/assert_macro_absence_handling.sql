-- Singular test: fail if any macro-derived score is non-NULL despite its macro
-- input being absent. This is the regression guard for docs/threshold_decisions.md
-- #7.20 — before that fix, margin_pressure_proxy_score/cost_shock_score/
-- price_position_score/macro_risk_flag all fell back to a fabricated neutral
-- sentinel instead of NULL when FRED/BLS had nothing to resolve, and
-- mart_action_queue's opportunity_tier silently labeled a NULL
-- overall_opportunity_score as 'Low'.
--
-- Currently vacuous against live data (FRED/BLS are collected weekly, #7.6), by
-- design — this is coverage for the day macro data genuinely goes missing, not a
-- check against today's state. Proven RED (fails) against a simulated
-- macro-absent dataset before the #7.20 fix, GREEN (0 rows) after — see the
-- verification note in #7.20.

select 'margin_pressure_proxy_score not null despite ppi_value null' as violation, count(*) as n
from {{ ref('mart_price_margin_scores') }}
where ppi_value is null and retail_price is not null and margin_pressure_proxy_score is not null
having count(*) > 0

union all

select 'cost_shock_score not null despite ppi_value null', count(*)
from {{ ref('mart_price_margin_scores') }}
where ppi_value is null and cost_shock_score is not null
having count(*) > 0

union all

select 'price_position_score not null despite cpi_value null', count(*)
from {{ ref('mart_price_margin_scores') }}
where cpi_value is null and retail_price is not null and price_position_score is not null
having count(*) > 0

union all

select 'macro_risk_flag not null despite macro fully absent', count(*)
from {{ ref('fact_market_signals') }}
where not macro_data_available and macro_risk_flag is not null
having count(*) > 0

union all

select 'opportunity_tier not Unknown despite overall_opportunity_score null', count(*)
from {{ ref('mart_action_queue') }}
where overall_opportunity_score is null and opportunity_tier != 'Unknown'
having count(*) > 0
