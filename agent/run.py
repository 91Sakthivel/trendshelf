"""
Orchestrator entrypoint for the Phase 2 agent -- mirrors collect_apis.py's
main() pattern (argparse, banner, exit code).

    python -m agent.run "what's the price position for beverages at store 01100002"
"""
import argparse
import sys

from agent.graph import build_graph, initial_state
from agent.llm import MODEL_ID


def ask(question: str) -> dict:
    """Runs one question through a FRESH graph (fresh ToolBreaker, fresh
    state) and returns the final state dict. Not shared across questions --
    each call is an independent run, same as a user asking a new question."""
    graph, breaker = build_graph()
    final_state = graph.invoke(initial_state(question), config={"recursion_limit": 50})
    return final_state


def main() -> int:
    parser = argparse.ArgumentParser(description="TrendShelf Phase 2 agent")
    parser.add_argument("question", help="the question to ask")
    args = parser.parse_args()

    print("=" * 64)
    print("  TrendShelf Agent")
    print(f"  Model    : {MODEL_ID}")
    print(f"  Question : {args.question}")
    print("=" * 64)

    final_state = ask(args.question)

    draft = final_state.get("draft_answer")
    print()
    print(f"iterations       : {final_state['iteration_count']}")
    print(f"tools called     : {[tc.tool_name for tc in final_state['tool_calls']]}")
    print(f"can_ground       : {final_state.get('can_ground')}")
    print(f"verified         : {final_state.get('verified')}")
    print(f"abstain_reason   : {final_state.get('abstain_reason')}")
    print()
    if draft:
        print("--- narrative ---")
        print(draft.narrative)
        if draft.grounded_claims:
            print()
            print("--- grounded claims ---")
            for c in draft.grounded_claims:
                print(f"  {c.claim_text} = {c.value}  (source: {c.source_tool} / {c.source_tool_call_id})")
    else:
        print("No draft answer produced.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
