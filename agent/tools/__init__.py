"""
agent/tools/__init__.py -- the VERIFIED_TOOLS registry.

A tool is only listed here once tests/agent/test_tools_known_values.py has
a passing hand-verified fixture for it (Phase 2 build instructions). This
dict is what graph.py will hand to Claude as the available tool set once
it exists -- an unverified tool can't be wired in even by accident, because
it simply isn't in this dict. All 6 tools currently pass their fixtures;
see the Phase 2 build report for the actual queried values.
"""
from agent.tools.docs import get_threshold_rationale, lookup_methodology, search_external_context
from agent.tools.marts import check_data_freshness, get_price_history, query_store_category

VERIFIED_TOOLS = {
    "query_store_category": query_store_category,
    "get_price_history": get_price_history,
    "check_data_freshness": check_data_freshness,
    "lookup_methodology": lookup_methodology,
    "get_threshold_rationale": get_threshold_rationale,
    "search_external_context": search_external_context,
}
