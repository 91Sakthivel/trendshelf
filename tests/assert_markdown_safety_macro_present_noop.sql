-- Singular test: proves the macro-absent reweight of markdown_safety_score
-- (docs/threshold_decisions.md #7.20, the named exception citing the #7.11
-- precedent) is a genuine no-op whenever macro_data_available = TRUE — not just
-- claimed in a comment. Recomputes the original 3-term formula inline
-- (margin_pressure_proxy_score 0.45, promo_risk_score 0.30, demand_decay_risk
-- 0.25) and requires it to match the live column within 0.02.
--
-- Why 0.02, not exact: the live markdown_safety_score is computed inside
-- mart_pricing_intelligence.sql's `scored` CTE from UNROUNDED intermediate
-- inputs, but this test can only read margin_pressure_proxy_score /
-- promo_risk_score / demand_decay_risk from the mart's final output, where
-- each is independently ROUND(...,2). Recomputing from three already-rounded
-- inputs at combined weight 1.0 can drift by at most ~3 x 0.005 x 0.45 (the
-- largest single weight) = ~0.0068 from cascading rounding alone -- 0.02 is a
-- generous bound above that floor, wide enough to absorb the rounding cascade
-- but far too tight to hide a real formula divergence (which would show up as
-- a difference of multiple points, not hundredths).
-- Fails (returns rows) if the two branches ever diverge beyond that tolerance
-- for a macro-present row -- that would mean the reweight condition leaked
-- into the macro-present case.
--
-- CAVEAT: this test passes VACUOUSLY when macro is absent for every row --
-- the WHERE macro_data_available clause simply matches nothing. It is only a
-- meaningful check when run against a macro-present dataset. See
-- docs/threshold_decisions.md #7.21 for how this was discovered and confirmed.

select
    store_id,
    category_name,
    markdown_safety_score,
    LEAST(100, GREATEST(0,
        100 - (
            margin_pressure_proxy_score * 0.45
            + COALESCE(promo_risk_score, 30) * 0.30
            + COALESCE(demand_decay_risk, 35) * 0.25
        )
    )) as recomputed_original_formula
from {{ ref('mart_pricing_intelligence') }}
where macro_data_available
  and ABS(markdown_safety_score - LEAST(100, GREATEST(0,
        100 - (
            margin_pressure_proxy_score * 0.45
            + COALESCE(promo_risk_score, 30) * 0.30
            + COALESCE(demand_decay_risk, 35) * 0.25
        )
    ))) > 0.02
