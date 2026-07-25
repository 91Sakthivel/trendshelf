-- Singular test: fail if pitch_readiness_floor is not strictly below expand_readiness_threshold.
-- mart_action_queue.sql's PITCH rule is `expansion_readiness_score BETWEEN pitch_readiness_floor
-- AND expand_readiness_threshold`. If the floor is ever raised to or above the ceiling, the range
-- either inverts (silently zero rows, no error) or collapses to a single point (technically
-- non-empty but almost certainly a misconfiguration) - neither is a valid PITCH window. This
-- compares the two vars directly (no live data involved), so it fails at test time regardless of
-- what's in the warehouse. See docs/threshold_decisions.md #7.15.
select
    {{ var('pitch_readiness_floor') }}      as pitch_readiness_floor,
    {{ var('expand_readiness_threshold') }} as expand_readiness_threshold
from UNNEST([1])
where {{ var('pitch_readiness_floor') }} >= {{ var('expand_readiness_threshold') }}
