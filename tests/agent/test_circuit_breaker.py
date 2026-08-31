"""
tests/agent/test_circuit_breaker.py

Proves the ToolBreaker actually stops calling a repeatedly-failing tool,
per the standing rule: a guard that has never been shown to fail proves
nothing.

test_control_without_breaker_keeps_calling is the RED control: it shows
the raw, unwrapped failure mode (a failing tool_fn gets invoked on every
attempt with nothing gating it) so the problem this breaker exists to
prevent is demonstrably real, not hypothetical.

test_breaker_disables_after_two_errors is the actual guard proof. Build
history: this file was first run against a deliberate no-op ToolBreaker
stub (agent/tools/executor.py before this commit) and FAILED at the
"3rd call blocked" assertion -- confirmed RED. It was then run again
against the real implementation and PASSED -- confirmed GREEN. See the
Phase 2 build report for the actual failure output.
"""
from typing import Optional

from pydantic import BaseModel

from agent.tools.executor import ToolBreaker, ToolDisabledError


class _FakeResult(BaseModel):
    error: Optional[str] = None


def _make_always_failing_tool(call_log: list):
    def tool_fn(**kwargs):
        call_log.append(kwargs)
        return _FakeResult(error="simulated failure")
    return tool_fn


def test_control_without_breaker_keeps_calling():
    """RED control: with no breaker in the loop, a failing tool is invoked
    every single time -- the unmitigated failure mode is real."""
    call_log = []
    tool_fn = _make_always_failing_tool(call_log)
    for _ in range(5):
        tool_fn(store_id="X")
    assert len(call_log) == 5


def test_breaker_disables_after_two_errors():
    """GREEN: same failing tool, wrapped in ToolBreaker -- disabled after
    exactly 2 errors; the 3rd+ attempt never reaches tool_fn at all."""
    call_log = []
    tool_fn = _make_always_failing_tool(call_log)
    breaker = ToolBreaker()

    r1 = breaker.call("fake_tool", tool_fn, store_id="X")
    assert r1.error == "simulated failure"
    assert len(call_log) == 1
    assert not breaker.is_disabled("fake_tool", {"store_id": "X"})

    r2 = breaker.call("fake_tool", tool_fn, store_id="X")
    assert r2.error == "simulated failure"
    assert len(call_log) == 2
    assert breaker.is_disabled("fake_tool", {"store_id": "X"})

    # 3rd attempt: must be blocked BEFORE reaching tool_fn -- call_log must
    # NOT grow. This is the line that failed against the no-op stub.
    raised = False
    try:
        breaker.call("fake_tool", tool_fn, store_id="X")
    except ToolDisabledError:
        raised = True
    assert raised, "expected ToolDisabledError on the 3rd attempt"
    assert len(call_log) == 2, "breaker let a 3rd call reach tool_fn -- guard did not fire"


def test_breaker_is_scoped_to_exact_args_not_just_tool_name():
    """Disabling one (tool, args) pair must not disable a sibling call with
    different args for the same tool."""
    call_log = []
    tool_fn = _make_always_failing_tool(call_log)
    breaker = ToolBreaker()

    breaker.call("fake_tool", tool_fn, store_id="X")
    breaker.call("fake_tool", tool_fn, store_id="X")
    assert breaker.is_disabled("fake_tool", {"store_id": "X"})

    r = breaker.call("fake_tool", tool_fn, store_id="Y")  # different args
    assert r.error == "simulated failure"
    assert len(call_log) == 3


def test_breaker_resets_failure_count_on_success():
    call_log = []

    def flaky(**kwargs):
        call_log.append(kwargs)
        if len(call_log) == 1:
            return _FakeResult(error="one bad call")
        return _FakeResult(error=None)

    breaker = ToolBreaker()
    breaker.call("flaky_tool", flaky, x=1)  # fails once
    breaker.call("flaky_tool", flaky, x=1)  # succeeds -- should reset the count
    assert not breaker.is_disabled("flaky_tool", {"x": 1})
    breaker.call("flaky_tool", flaky, x=1)  # must NOT be blocked
    assert len(call_log) == 3
