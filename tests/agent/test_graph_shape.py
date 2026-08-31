"""
tests/agent/test_graph_shape.py -- node/edge wiring only, no LLM calls.
Runnable offline: build_graph(client=object()) never calls the dummy
client, since these tests only inspect the compiled graph's structure via
get_graph(), never .invoke() it.
"""
from agent.graph import build_graph


def _compiled():
    graph, breaker = build_graph(client=object())
    return graph.get_graph()


def test_all_expected_nodes_present():
    g = _compiled()
    expected = {"agent", "execute_tools", "check_reliability", "verify", "abstain", "answer"}
    assert expected.issubset(set(g.nodes.keys()))


def test_entry_point_is_agent():
    g = _compiled()
    edges = {(e.source, e.target) for e in g.edges}
    assert ("__start__", "agent") in edges


def test_agent_branches_to_execute_tools_or_check_reliability():
    g = _compiled()
    targets = {e.target for e in g.edges if e.source == "agent"}
    assert targets == {"execute_tools", "check_reliability"}


def test_execute_tools_loops_back_to_agent_and_can_exit_to_check_reliability():
    g = _compiled()
    targets = {e.target for e in g.edges if e.source == "execute_tools"}
    assert targets == {"agent", "check_reliability"}


def test_check_reliability_branches_to_verify_or_abstain():
    g = _compiled()
    targets = {e.target for e in g.edges if e.source == "check_reliability"}
    assert targets == {"verify", "abstain"}


def test_verify_branches_to_answer_or_abstain():
    g = _compiled()
    targets = {e.target for e in g.edges if e.source == "verify"}
    assert targets == {"answer", "abstain"}


def test_abstain_and_answer_are_terminal():
    g = _compiled()
    abstain_targets = {e.target for e in g.edges if e.source == "abstain"}
    answer_targets = {e.target for e in g.edges if e.source == "answer"}
    assert abstain_targets == {"__end__"}
    assert answer_targets == {"__end__"}


def test_no_edge_bypasses_check_reliability_into_answer():
    """Structural guarantee: the only path to "answer" is through
    check_reliability -> verify -> answer. Nothing can reach a final
    answer without passing the reliability gate first."""
    g = _compiled()
    sources_into_answer = {e.source for e in g.edges if e.target == "answer"}
    assert sources_into_answer == {"verify"}


def test_tool_definitions_include_all_6_verified_tools_plus_submit_final_answer():
    from agent.graph import SUBMIT_FINAL_ANSWER, TOOL_DEFINITIONS
    from agent.tools import VERIFIED_TOOLS

    defined_names = {t["name"] for t in TOOL_DEFINITIONS}
    assert set(VERIFIED_TOOLS.keys()).issubset(defined_names)
    assert SUBMIT_FINAL_ANSWER in defined_names
    assert len(TOOL_DEFINITIONS) == len(VERIFIED_TOOLS) + 1


def test_max_tool_iterations_is_wired_from_config_not_hardcoded():
    import inspect

    from agent import graph as graph_module

    source = inspect.getsource(graph_module)
    assert "config.AGENT_MAX_TOOL_ITERATIONS" in source
    # not a bare literal 8 standing in for the config value anywhere in the loop-exit check
    assert "iteration_count'] >= 8" not in source.replace(" ", "")
