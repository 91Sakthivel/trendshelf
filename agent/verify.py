"""
agent/verify.py -- Phase 3 grounding verifier.

For each claim in draft_answer.grounded_claims, checks:
  (a) source_tool_call_id resolves to a real ToolCallRecord in state["tool_calls"]
  (b) source_tool is in the quant allowlist (never a RAG tool -- RAG results
      structurally carry no numeric "value" field, agent/schemas.py, so a
      claim citing one is definitionally ungroundable, not just suspicious)
  (c) the claim's own source_tool matches the tool actually named on that
      ToolCallRecord (catches a claim citing the right call_id but the
      wrong tool name)
  (d) source_field exists as a key in that record's result
  (e) claim.value equals result[source_field]

An empty grounded_claims list passes trivially -- a correct pure-methodology
answer (Phase 2 run (b)) legitimately has zero grounded claims; that is not
a failure mode to guard against.

Any single claim failing any check fails the WHOLE answer, not "drop the
bad claim, keep the rest" -- a partially-fabricated answer is not a
partially trustworthy one.

Proven closed, not just implemented: run against three staged versions
(the original always-True stub, then a provenance-only version checking
only a-d, then this full version) -- see the Phase 3 build report for the
actual pytest output at each stage. The provenance-only stage specifically
proved a fabricated value with otherwise-perfect provenance passes without
check (e), i.e. the hole named in Phase 2 background finding 2 was real.
"""
from typing import Any, Optional

from agent.state import AgentState, GroundedClaim, ToolCallRecord

QUANT_TOOL_ALLOWLIST = {"query_store_category", "get_price_history", "check_data_freshness"}

# Floating-point representation safety margin, NOT a data-derived tolerance
# like retail_healthy_pct_divisor (docs/threshold_decisions.md #7.13) or the
# 0.02 cascading-rounding bound for assert_markdown_safety_macro_present_noop
# (#7.21). There is no rounding cascade in this comparison: claim.value is a
# direct copy of a number Claude read verbatim from a tool_result it was
# shown, not a value recomputed from other already-rounded inputs, so there
# is no equivalent "how much could this drift" calculation to derive a bound
# from. 1e-6 exists only to absorb genuine binary float representation noise
# (json <-> float <-> Pydantic round-trips), chosen to be ~4 orders of
# magnitude below 0.01 -- the coarsest rounding precision any numeric field
# in the 6 tools currently emits (every score is ROUND(...,2) at the mart
# layer) -- so it can absorb representation noise without ever being able to
# mask a genuinely different number. If a future tool exposes finer-grained
# floats, this needs re-deriving, not silently trusting.
NUMERIC_TOLERANCE = 1e-6


def _values_match(claimed: Any, actual: Any) -> bool:
    try:
        return abs(float(claimed) - float(actual)) <= NUMERIC_TOLERANCE
    except (TypeError, ValueError):
        # Not both numeric -- strings (and everything else) compare exactly,
        # per spec. No case-folding, no fuzzy match.
        return str(claimed) == str(actual)


def _check_claim(claim: GroundedClaim, tool_calls_by_id: dict[str, ToolCallRecord]) -> Optional[str]:
    """Returns None if the claim passes every check, else a human-readable
    reason it failed."""
    record = tool_calls_by_id.get(claim.source_tool_call_id)
    if record is None:
        return f"source_tool_call_id {claim.source_tool_call_id!r} does not resolve to any tool call in this run"

    if claim.source_tool not in QUANT_TOOL_ALLOWLIST:
        return f"source_tool {claim.source_tool!r} is not a quant tool (RAG results carry no groundable value)"

    if record.tool_name != claim.source_tool:
        return (
            f"claim names source_tool={claim.source_tool!r} but call_id "
            f"{claim.source_tool_call_id!r} was actually a call to {record.tool_name!r}"
        )

    if claim.source_field not in record.result:
        return f"source_field {claim.source_field!r} is not present in {record.tool_name}'s result"

    actual = record.result[claim.source_field]
    if not _values_match(claim.value, actual):
        return f"claim.value={claim.value!r} does not match {record.tool_name}.{claim.source_field}={actual!r}"

    return None


def verify(state: AgentState) -> dict:
    draft = state.get("draft_answer")
    if draft is None or not draft.grounded_claims:
        # No claims to verify is a legitimate outcome, not a failure --
        # see the empty-grounded-claims test.
        return {"verified": True}

    tool_calls_by_id = {tc.call_id: tc for tc in state["tool_calls"]}
    for claim in draft.grounded_claims:
        failure = _check_claim(claim, tool_calls_by_id)
        if failure is not None:
            return {"verified": False, "abstain_reason": f"verifier rejected a claim: {failure}"}

    return {"verified": True}
