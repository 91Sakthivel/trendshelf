"""
agent/verify.py -- STUB. Phase 3 fills this in.

Wired now so the graph shape is final: verify(state) -> {"verified": bool}
is the whole contract graph.py's verify node depends on. This stub always
returns True -- it does NOT check that every GroundedClaim.source_tool_call_id
resolves to a real ToolCallRecord in state["tool_calls"], or that
GroundedClaim.value matches the field it claims to come from. Those are
Phase 3's job. Until Phase 3 lands, nothing in this graph structurally
blocks an ungrounded claim from reaching the final answer -- the typed
contract (agent/state.py) makes that check mechanical when it's built, but
mechanical-and-not-yet-built is not the same as enforced.
"""
from agent.state import AgentState


def verify(state: AgentState) -> dict:
    return {"verified": True}
