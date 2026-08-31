"""
agent/state.py -- the graph's state shape and the output-side Pydantic
contracts (ToolCallRecord, AgentAnswer, GroundedClaim, AbstainResult).

The grounding contract (Phase 2 proposal, point 5): GroundedClaim.value
must trace to a ToolCallRecord.call_id that actually exists in
state["tool_calls"]. ToolCallRecord.result is always one of the 6 tools'
own typed Pydantic results, serialized via .model_dump() -- never a
RetrievedChunk. That type-level separation (typed numeric tool results vs.
text-only RetrievedChunk, agent/schemas.py) is what makes it structurally
impossible for a grounded claim to trace back to a retrieved document
instead of a tool call. Phase 3's verify.py checks this; this file just
carries the data it needs to check it against.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict, Union

from pydantic import BaseModel, Field

from agent.schemas import RetrievedChunk


class ToolCallRecord(BaseModel):
    """Full provenance for one tool call: what was asked, what came back.
    call_id is Anthropic's own tool_use block id -- reused rather than
    inventing a second id scheme, since Claude already sees and can cite it
    via the tool_result it gets back."""
    call_id: str
    tool_name: str
    args: dict[str, Any]
    result: dict[str, Any]  # one of the 6 tools' Pydantic results, .model_dump()'d
    error: Optional[str] = None  # mirrors result.get("error") for cheap filtering


class GroundedClaim(BaseModel):
    claim_text: str
    value: Union[float, str]
    source_tool: str
    source_tool_call_id: str
    # Phase 3 (docs/threshold_decisions.md, verifier build): the field name
    # on the source tool's result that `value` claims to come from, e.g.
    # "premium_support_proxy_score". Required, not optional -- a claim with
    # no named field is not verifiable even in principle, so it must not be
    # constructible without one.
    source_field: str


class AgentAnswer(BaseModel):
    narrative: str
    grounded_claims: list[GroundedClaim] = Field(default_factory=list)


class AbstainResult(BaseModel):
    reason: str
    attempted_tools: list[str] = Field(default_factory=list)


class AgentState(TypedDict):
    question: str
    # Plain Anthropic-SDK-shaped message dicts, appended via list concat --
    # deliberately NOT langgraph.graph.message.add_messages, which expects/
    # coerces LangChain BaseMessage objects. The stack lock says no
    # LangChain base library; pulling it in through a state reducer would
    # violate that as quietly as importing it directly.
    messages: Annotated[list, operator.add]
    tool_calls: Annotated[list[ToolCallRecord], operator.add]
    retrieved_chunks: Annotated[list[RetrievedChunk], operator.add]
    iteration_count: int
    can_ground: Optional[bool]
    abstain_reason: Optional[str]
    draft_answer: Optional[AgentAnswer]
    verified: Optional[bool]
