"""
agent/graph.py -- the Phase 2 state graph.

START -> agent (Claude, native tool use, all 6 VERIFIED_TOOLS plus a 7th
  meta-tool, submit_final_answer -- used to get a structured final answer
  out of the same tool-use loop instead of parsing free text separately)
  -> [tool_calls present?] yes -> execute_tools -> back to agent
                            no  -> check_reliability (agent_node already
                                   synthesized a draft_answer from the
                                   plain-text reply in this branch)
  -> check_reliability (deterministic Python, NOT an LLM call)
  -> [can_ground?] no -> abstain (END)
                    yes -> verify -> [verified?] no -> abstain (END)
                                              yes -> answer (END)

Loop bound: config.AGENT_MAX_TOOL_ITERATIONS (8, marked placeholder in
config.py). On exhaustion, execute_tools force-routes to check_reliability
with whatever was collected -- same path as "Claude is done", not a
separate failure mode.

GAP, flagged not silently worked around: the approved design named
confidence_level, macro_data_available, and has_prior_month_price/ppi as
signals for check_reliability to read. None of the 6 VERIFIED_TOOLS
expose these fields -- they live on mart_confidence_layer's
overall_confidence_score/confidence_level and mart_price_margin_scores'/
mart_shelfrisk_scores' has_prior_month_* columns, which no tool reads.
Per the constraint against modifying a tool or its fixture to make the
graph happy, check_reliability below uses what's actually available:
each tool result's own `found`/`error` fields and check_data_freshness's
`anomaly` flag.
"""
import json
from typing import Optional

from langgraph.graph import END, START, StateGraph

import config
from agent.llm import MODEL_ID, get_client
from agent.schemas import RetrievedChunk
from agent.state import AgentAnswer, AgentState, GroundedClaim, ToolCallRecord
from agent.tools import VERIFIED_TOOLS
from agent.tools.executor import ToolBreaker, ToolDisabledError
from agent.verify import verify as verify_fn

SUBMIT_FINAL_ANSWER = "submit_final_answer"

SYSTEM_PROMPT = """You are the TrendShelf data agent. You answer questions about \
TrendShelf's own CPG pricing-intelligence data for Kroger stores in the \
Dallas-Fort Worth area, grounded ONLY in what your tools actually return.

Tools available:
- query_store_category, get_price_history, check_data_freshness: read \
TrendShelf's own scoring marts (BigQuery). This is CURRENT and HISTORICAL \
data only -- roughly 13 weeks of history, collected weekly. None of these \
tools can tell you about the future. There is no forecasting or prediction \
capability anywhere in this system.
- lookup_methodology, get_threshold_rationale, search_external_context: \
retrieve text passages from internal documentation or external filings \
(10-Ks, FRED/USDA notes). Use these for "how/why does the scoring work" \
or "what does an external source say" questions -- never as a source for \
a number about TrendShelf's own current data. A number you only saw \
inside a retrieved document's text is not the same as a number a data \
tool returned.

Rules:
- Every number you state about TrendShelf's own pricing/scoring data must \
come from query_store_category, get_price_history, or check_data_freshness. \
Never restate a number you only saw in a retrieved document as if it were \
current data.
- If no tool call returns usable data for what was actually asked -- \
including because the question asks for something no tool can provide, \
such as a future price -- say so plainly. Do not guess or extrapolate.
- When you are done, call submit_final_answer exactly once. List every \
factual claim in grounded_claims with the tool call it came from. If you \
cannot ground an answer, call submit_final_answer with an empty \
grounded_claims list and explain why in the narrative.
"""

TOOL_DEFINITIONS = [
    {
        "name": "query_store_category",
        "description": (
            "Current pricing-intelligence scores for one store x category, from "
            "mart_pricing_intelligence. All score fields are Optional -- NULL means "
            "the score is genuinely unresolved (e.g. macro data absent), not zero. "
            "found=false + error=null means a valid store/category with no row for "
            "the requested period. A non-null error means store_id or category was "
            "not recognized."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string", "description": "Kroger store id, e.g. '01100002'"},
                "category": {
                    "type": "string",
                    "description": (
                        "beverages | snacks | dairy | frozen foods | breakfast cereal "
                        "| meat seafood | produce | personal care | household | coffee tea"
                    ),
                },
                "reference_month": {
                    "type": "string",
                    "description": "optional, YYYY-MM-DD (first of month). Omit for the latest available month.",
                },
            },
            "required": ["store_id", "category"],
        },
    },
    {
        "name": "get_price_history",
        "description": (
            "Weekly price-gap history for one store x category, from "
            "fct_store_category_weekly. Only ~13 weeks of history exist "
            "project-wide -- historical data only, never a forecast."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "category": {"type": "string"},
                "weeks": {"type": "integer", "description": "how many most-recent weeks to return, default 13"},
            },
            "required": ["store_id", "category"],
        },
    },
    {
        "name": "check_data_freshness",
        "description": "Collection recency for all 5 data sources (Kroger, FRED, BLS, SerpAPI, Google Trends). No arguments.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "lookup_methodology",
        "description": (
            "Semantic search over TrendShelf's internal documentation (scoring "
            "methodology, README, threshold decisions, signal-stability backtest) "
            "for how/why the scoring model works. Returns retrieved text passages, "
            "never a number to treat as current data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "get_threshold_rationale",
        "description": (
            "Semantic search restricted to docs/threshold_decisions.md "
            "specifically, for why a named scoring threshold/constant has the "
            "value it has. Prefer this over lookup_methodology when the question "
            "names a specific threshold or config variable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"threshold_name": {"type": "string"}},
            "required": ["threshold_name"],
        },
    },
    {
        "name": "search_external_context",
        "description": (
            "Semantic search over external sources (Kroger/Walmart 10-Ks, "
            "FRED/USDA methodology notes) for market or competitive context. Does "
            "not cover TrendShelf's own pricing data or scoring -- use the mart "
            "tools for that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": SUBMIT_FINAL_ANSWER,
        "description": (
            "Call this exactly once, when you are done gathering information, to "
            "submit your final answer. Every entry in grounded_claims must cite "
            "the tool call it came from via source_tool_call_id, and the exact "
            "field name on that tool's result via source_field -- never a "
            "retrieved document. If nothing could be grounded, call this with an "
            "empty grounded_claims list and explain why in narrative."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "narrative": {"type": "string"},
                "grounded_claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim_text": {"type": "string"},
                            "value": {"type": "string"},
                            "source_tool": {"type": "string"},
                            "source_tool_call_id": {"type": "string"},
                            "source_field": {
                                "type": "string",
                                "description": "the exact field name on the source tool's result that value comes from, e.g. 'premium_support_proxy_score'",
                            },
                        },
                        "required": ["claim_text", "value", "source_tool", "source_tool_call_id", "source_field"],
                    },
                },
            },
            "required": ["narrative", "grounded_claims"],
        },
    },
]


def _serialize_tool_result(result) -> dict:
    return result.model_dump(mode="json")


def _content_of(message) -> list:
    return message["content"] if isinstance(message, dict) else message.content


def abstain_node(state: AgentState) -> dict:
    """Terminal node for every abstain path. Module-level (not a build_graph
    closure) because it has no dependency on client/breaker and needs to be
    unit-testable offline (tests/agent/test_verify.py).

    Preserves Claude's own narrative when one exists instead of replacing it
    -- Phase 2 run (c) found a correct, well-reasoned self-abstain getting
    overwritten by a generic message here; this is the fix. Also tags which
    gate produced the abstain so Phase 4 can separate correct-abstain
    (model_self_abstain) from false-abstain (verifier_rejected) rates
    instead of both collapsing into one string.

    Distinguished by which gate ran, not a separate state field: `verified`
    is False only when verify() actually ran and rejected a specific claim.
    It's still None when check_reliability rejected first -- nothing was
    ever submitted for verification, because there was no groundable data to
    build a claim from in the first place (including Claude correctly
    declining on its own, as in Phase 2 run (c)).
    """
    reason = state.get("abstain_reason") or "could not verify a grounded answer"
    cause = "verifier_rejected" if state.get("verified") is False else "model_self_abstain"
    draft = state.get("draft_answer")

    if draft is not None and draft.narrative.strip():
        narrative = f"{draft.narrative}\n\n[ABSTAIN -- {cause}] {reason}"
    else:
        narrative = f"[ABSTAIN -- {cause}] {reason}"

    return {
        "draft_answer": AgentAnswer(narrative=narrative, grounded_claims=[]),
        "abstain_reason": f"[{cause}] {reason}",
    }


def build_graph(client=None):
    """Returns a compiled graph plus the ToolBreaker instance driving it
    (so a caller can inspect breaker state after a run, e.g. for tests)."""
    client = client or get_client()
    breaker = ToolBreaker()

    def agent_node(state: AgentState) -> dict:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=state["messages"],
        )
        assistant_message = {"role": "assistant", "content": response.content}
        tool_uses = [b for b in response.content if b.type == "tool_use"]

        if not tool_uses:
            # Claude answered in plain text without calling submit_final_answer.
            # Captured rather than silently dropped -- synthesized as a draft
            # answer with no grounded_claims, since none were structurally
            # declared. check_reliability still gates this the same as any
            # other path: no tool_calls + no retrieved_chunks means abstain
            # regardless of what this text says.
            text = "".join(b.text for b in response.content if b.type == "text")
            return {
                "messages": [assistant_message],
                "draft_answer": AgentAnswer(narrative=text, grounded_claims=[]),
            }
        return {"messages": [assistant_message]}

    def route_after_agent(state: AgentState) -> str:
        content = _content_of(state["messages"][-1])
        has_tool_use = any(getattr(b, "type", None) == "tool_use" for b in content)
        return "execute_tools" if has_tool_use else "check_reliability"

    def execute_tools_node(state: AgentState) -> dict:
        content = _content_of(state["messages"][-1])
        tool_uses = [b for b in content if getattr(b, "type", None) == "tool_use"]

        tool_call_records: list[ToolCallRecord] = []
        tool_result_blocks: list[dict] = []
        new_chunks: list[RetrievedChunk] = []
        draft_answer_update = {}

        for tu in tool_uses:
            call_id, name, tool_input = tu.id, tu.name, tu.input

            if name == SUBMIT_FINAL_ANSWER:
                try:
                    claims = [GroundedClaim(**c) for c in tool_input.get("grounded_claims", [])]
                    draft_answer_update["draft_answer"] = AgentAnswer(
                        narrative=tool_input.get("narrative", ""), grounded_claims=claims
                    )
                    tool_result_blocks.append(
                        {"type": "tool_result", "tool_use_id": call_id, "content": "recorded"}
                    )
                except Exception as e:
                    tool_result_blocks.append(
                        {"type": "tool_result", "tool_use_id": call_id, "content": f"error: {e}", "is_error": True}
                    )
                continue

            if name not in VERIFIED_TOOLS:
                tool_result_blocks.append({
                    "type": "tool_result", "tool_use_id": call_id,
                    "content": f"error: unknown tool {name!r}", "is_error": True,
                })
                continue

            try:
                result = breaker.call(name, VERIFIED_TOOLS[name], **tool_input)
                result_dict = _serialize_tool_result(result)
                error = result_dict.get("error")
            except ToolDisabledError as e:
                result_dict, error = {"error": str(e)}, str(e)
            except Exception as e:
                # Defense in depth -- every VERIFIED_TOOL already catches its own
                # exceptions and returns a typed error result (Phase 2 build
                # step 1), so this should be unreachable in practice. Kept so a
                # malformed tool_input can't crash the whole graph run.
                result_dict = {"error": f"{type(e).__name__}: {e}"}
                error = result_dict["error"]

            tool_call_records.append(ToolCallRecord(
                call_id=call_id, tool_name=name, args=tool_input, result=result_dict, error=error,
            ))
            tool_result_blocks.append({
                "type": "tool_result", "tool_use_id": call_id,
                "content": json.dumps(result_dict, default=str),
                **({"is_error": True} if error else {}),
            })

            if name in ("lookup_methodology", "get_threshold_rationale", "search_external_context"):
                for c in result_dict.get("chunks", []):
                    new_chunks.append(RetrievedChunk(**c))

        update = {
            "messages": [{"role": "user", "content": tool_result_blocks}],
            "tool_calls": tool_call_records,
            "retrieved_chunks": new_chunks,
            "iteration_count": state["iteration_count"] + 1,
        }
        update.update(draft_answer_update)
        return update

    def route_after_execute_tools(state: AgentState) -> str:
        if state.get("draft_answer") is not None:
            return "check_reliability"
        if state["iteration_count"] >= config.AGENT_MAX_TOOL_ITERATIONS:
            return "check_reliability"
        return "agent"

    def check_reliability_node(state: AgentState) -> dict:
        tool_calls = state["tool_calls"]
        has_docs = len(state["retrieved_chunks"]) > 0

        if not tool_calls:
            if has_docs:
                return {"can_ground": True}
            return {
                "can_ground": False,
                "abstain_reason": "no tool was called and no document was retrieved -- nothing to ground an answer in",
            }

        any_quant_found = any(
            tc.tool_name in ("query_store_category", "get_price_history") and tc.result.get("found")
            for tc in tool_calls
        )
        anomaly = next(
            (tc.result.get("anomaly") for tc in tool_calls
             if tc.tool_name == "check_data_freshness" and tc.result.get("anomaly")),
            None,
        )

        if not any_quant_found and not has_docs:
            return {
                "can_ground": False,
                "abstain_reason": "no tool call returned usable data (all found=false / no chunks) and none was retrieved",
            }
        if anomaly:
            return {"can_ground": False, "abstain_reason": f"data freshness anomaly: {anomaly}"}
        return {"can_ground": True, "abstain_reason": None}

    def route_after_check_reliability(state: AgentState) -> str:
        return "verify" if state["can_ground"] else "abstain"

    def route_after_verify(state: AgentState) -> str:
        return "answer" if state["verified"] else "abstain"

    def answer_node(state: AgentState) -> dict:
        return {}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("execute_tools", execute_tools_node)
    graph.add_node("check_reliability", check_reliability_node)
    graph.add_node("verify", verify_fn)
    graph.add_node("abstain", abstain_node)
    graph.add_node("answer", answer_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, {
        "execute_tools": "execute_tools", "check_reliability": "check_reliability",
    })
    graph.add_conditional_edges("execute_tools", route_after_execute_tools, {
        "agent": "agent", "check_reliability": "check_reliability",
    })
    graph.add_conditional_edges("check_reliability", route_after_check_reliability, {
        "verify": "verify", "abstain": "abstain",
    })
    graph.add_conditional_edges("verify", route_after_verify, {
        "answer": "answer", "abstain": "abstain",
    })
    graph.add_edge("abstain", END)
    graph.add_edge("answer", END)

    return graph.compile(), breaker


def initial_state(question: str) -> AgentState:
    return {
        "question": question,
        "messages": [{"role": "user", "content": question}],
        "tool_calls": [],
        "retrieved_chunks": [],
        "iteration_count": 0,
        "can_ground": None,
        "abstain_reason": None,
        "draft_answer": None,
        "verified": None,
    }
