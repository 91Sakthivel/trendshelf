"""
tests/agent/test_verify.py -- offline, no LLM calls. Pure unit tests of
agent/verify.py's verify() and agent/graph.py's abstain_node(), both plain
functions of AgentState.

RED-before-GREEN proof for this file is recorded in the Phase 3 build
report, not here -- this file is the FINAL, passing version. The report
pastes the actual pytest output from running this same file against (a)
the original stub, (b) an intermediate provenance-only implementation
that does everything except check claim.value, and (c) the real
implementation.
"""
from agent.state import AgentAnswer, AgentState, GroundedClaim, ToolCallRecord
from agent.verify import verify
from agent.graph import abstain_node


def _tool_call(call_id, tool_name, result, error=None):
    return ToolCallRecord(call_id=call_id, tool_name=tool_name, args={}, result=result, error=error)


def _state(tool_calls=None, draft_answer=None, retrieved_chunks=None, verified=None, abstain_reason=None):
    return {
        "question": "q",
        "messages": [],
        "tool_calls": tool_calls or [],
        "retrieved_chunks": retrieved_chunks or [],
        "iteration_count": 1,
        "can_ground": True,
        "abstain_reason": abstain_reason,
        "draft_answer": draft_answer,
        "verified": verified,
    }


# ── verify(): provenance checks ──────────────────────────────────────────

def test_claim_with_unknown_call_id_fails_verification():
    tc = _tool_call("call_1", "query_store_category", {"found": True, "premium_support_proxy_score": 54.76})
    claim = GroundedClaim(
        claim_text="premium support proxy score is 54.76", value=54.76,
        source_tool="query_store_category", source_tool_call_id="call_DOES_NOT_EXIST",
        source_field="premium_support_proxy_score",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[claim]))
    result = verify(state)
    assert result["verified"] is False


def test_claim_citing_rag_tool_as_source_fails_verification():
    tc = _tool_call("call_1", "lookup_methodology", {"chunks": [{"chunk_text": "some doc text with a number 54.76 in it"}]})
    claim = GroundedClaim(
        claim_text="the doc says 54.76", value=54.76,
        source_tool="lookup_methodology", source_tool_call_id="call_1", source_field="chunks",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[claim]))
    result = verify(state)
    assert result["verified"] is False


def test_claim_with_missing_source_field_fails_verification():
    tc = _tool_call("call_1", "query_store_category", {"found": True, "premium_support_proxy_score": 54.76})
    claim = GroundedClaim(
        claim_text="x", value=99, source_tool="query_store_category",
        source_tool_call_id="call_1", source_field="field_that_does_not_exist",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[claim]))
    result = verify(state)
    assert result["verified"] is False


def test_claim_with_source_tool_mismatched_to_actual_call_fails_verification():
    """call_1 was really a query_store_category call; a claim citing call_1
    but naming get_price_history as source_tool must fail even though
    get_price_history is itself a valid quant tool."""
    tc = _tool_call("call_1", "query_store_category", {"found": True, "premium_support_proxy_score": 54.76})
    claim = GroundedClaim(
        claim_text="x", value=54.76, source_tool="get_price_history",
        source_tool_call_id="call_1", source_field="premium_support_proxy_score",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[claim]))
    result = verify(state)
    assert result["verified"] is False


# ── verify(): the value-match hole (background finding 2) ───────────────

def test_claim_with_fabricated_value_fails_verification():
    """THE HOLE. call_id resolves, source_tool is a real quant tool,
    source_field exists on the result -- everything about provenance is
    correct. Only the claimed VALUE is wrong (fabricated). Must still fail."""
    tc = _tool_call("call_1", "query_store_category", {"found": True, "premium_support_proxy_score": 54.76})
    claim = GroundedClaim(
        claim_text="premium support proxy score is 99.99", value=99.99,
        source_tool="query_store_category", source_tool_call_id="call_1",
        source_field="premium_support_proxy_score",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[claim]))
    result = verify(state)
    assert result["verified"] is False


def test_fully_correct_numeric_claim_verifies():
    tc = _tool_call("call_1", "query_store_category", {"found": True, "premium_support_proxy_score": 54.76})
    claim = GroundedClaim(
        claim_text="premium support proxy score is 54.76", value=54.76,
        source_tool="query_store_category", source_tool_call_id="call_1",
        source_field="premium_support_proxy_score",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[claim]))
    result = verify(state)
    assert result["verified"] is True


def test_string_valued_claim_matching_float_result_verifies():
    """Realistic path: the submit_final_answer tool schema declares `value`
    as a JSON string, so Claude's real claims arrive as e.g. "54.76", not a
    JSON number, while the tool result field is a Python float. Must still
    match numerically, not fail on type mismatch."""
    tc = _tool_call("call_1", "query_store_category", {"found": True, "premium_support_proxy_score": 54.76})
    claim = GroundedClaim(
        claim_text="premium support proxy score is 54.76", value="54.76",
        source_tool="query_store_category", source_tool_call_id="call_1",
        source_field="premium_support_proxy_score",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[claim]))
    result = verify(state)
    assert result["verified"] is True


def test_exact_string_claim_verifies():
    tc = _tool_call("call_1", "query_store_category", {"found": True, "price_position": "Underpriced"})
    claim = GroundedClaim(
        claim_text="price position is Underpriced", value="Underpriced",
        source_tool="query_store_category", source_tool_call_id="call_1",
        source_field="price_position",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[claim]))
    result = verify(state)
    assert result["verified"] is True


def test_string_claim_with_wrong_case_fails_verification():
    """Strings compare exactly, per spec -- no fuzzy/case-insensitive match."""
    tc = _tool_call("call_1", "query_store_category", {"found": True, "price_position": "Underpriced"})
    claim = GroundedClaim(
        claim_text="price position is underpriced", value="underpriced",
        source_tool="query_store_category", source_tool_call_id="call_1",
        source_field="price_position",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[claim]))
    result = verify(state)
    assert result["verified"] is False


def test_one_bad_claim_fails_the_whole_answer_not_just_itself():
    """Spec: any claim failing any check fails the WHOLE answer -- do not
    silently drop the bad claim and keep the rest."""
    tc = _tool_call("call_1", "query_store_category", {
        "found": True, "premium_support_proxy_score": 54.76, "price_position": "Underpriced",
    })
    good_claim = GroundedClaim(
        claim_text="price position is Underpriced", value="Underpriced",
        source_tool="query_store_category", source_tool_call_id="call_1", source_field="price_position",
    )
    bad_claim = GroundedClaim(
        claim_text="premium support proxy score is 99.99", value=99.99,
        source_tool="query_store_category", source_tool_call_id="call_1",
        source_field="premium_support_proxy_score",
    )
    state = _state(tool_calls=[tc], draft_answer=AgentAnswer(narrative="n", grounded_claims=[good_claim, bad_claim]))
    result = verify(state)
    assert result["verified"] is False


# ── verify(): empty claims is valid, not a failure ───────────────────────

def test_empty_grounded_claims_verifies_not_abstains():
    """Phase 2 run (b): a correct pure-methodology answer legitimately has
    zero grounded claims. Must be verified=True, not treated as failure."""
    state = _state(tool_calls=[], draft_answer=AgentAnswer(narrative="pure methodology answer", grounded_claims=[]))
    result = verify(state)
    assert result["verified"] is True


# ── abstain_node: narrative preservation (background finding 3) ─────────

def test_abstain_node_preserves_existing_narrative():
    draft = AgentAnswer(
        narrative=(
            "I can't answer this. None of the tools available to me have any "
            "forecasting or prediction capability."
        ),
        grounded_claims=[],
    )
    state = _state(
        draft_answer=draft, verified=None,
        abstain_reason="no tool was called and no document was retrieved -- nothing to ground an answer in",
    )
    result = abstain_node(state)
    assert "I can't answer this." in result["draft_answer"].narrative
    assert "forecasting or prediction capability" in result["draft_answer"].narrative


def test_abstain_node_tags_model_self_abstain_when_verify_never_ran():
    draft = AgentAnswer(narrative="I can't answer this.", grounded_claims=[])
    state = _state(draft_answer=draft, verified=None, abstain_reason="no tool was called")
    result = abstain_node(state)
    assert "model_self_abstain" in result["abstain_reason"]


def test_abstain_node_tags_verifier_rejected_when_verify_ran_and_failed():
    draft = AgentAnswer(narrative="Here is my answer with a claim.", grounded_claims=[])
    state = _state(draft_answer=draft, verified=False, abstain_reason="verifier rejected a claim: ...")
    result = abstain_node(state)
    assert "verifier_rejected" in result["abstain_reason"]
    assert "Here is my answer with a claim." in result["draft_answer"].narrative


def test_abstain_node_with_no_draft_uses_generic_message():
    """Current/prior behaviour, preserved: no draft_answer at all (the
    iteration-cap-exhaustion edge case) falls back to a generic message,
    since there is no narrative to preserve."""
    state = _state(draft_answer=None, verified=None, abstain_reason="no tool call returned usable data")
    result = abstain_node(state)
    assert result["draft_answer"].narrative.startswith("[ABSTAIN")
    assert "no tool call returned usable data" in result["draft_answer"].narrative


def test_abstain_node_with_blank_narrative_uses_generic_message():
    """An AgentAnswer that technically exists but carries an empty/blank
    narrative is treated the same as no narrative -- nothing to preserve."""
    draft = AgentAnswer(narrative="   ", grounded_claims=[])
    state = _state(draft_answer=draft, verified=None, abstain_reason="no tool call returned usable data")
    result = abstain_node(state)
    assert result["draft_answer"].narrative.strip().startswith("[ABSTAIN")


def test_abstain_node_always_clears_grounded_claims():
    """Even if the draft carried claims (e.g. the ones verify() just
    rejected), the final abstained answer must not keep presenting them."""
    bad_claim = GroundedClaim(
        claim_text="x", value=1, source_tool="query_store_category",
        source_tool_call_id="call_1", source_field="f",
    )
    draft = AgentAnswer(narrative="answer text", grounded_claims=[bad_claim])
    state = _state(draft_answer=draft, verified=False, abstain_reason="verifier rejected a claim: ...")
    result = abstain_node(state)
    assert result["draft_answer"].grounded_claims == []
