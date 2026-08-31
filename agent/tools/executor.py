"""
agent/tools/executor.py -- the tool-call circuit breaker.

Wraps tool execution so a (tool, exact-args) pair that errors twice gets
disabled for the rest of the run, rather than retried indefinitely against
a persistently broken tool. Graph-adjacent logic that doesn't need graph.py
to exist -- built and proven now (tests/agent/test_circuit_breaker.py),
per the Phase 2 build instructions.

RED-before-GREEN: this file was first a no-op stub (call() just invoked
tool_fn directly, is_disabled() always returned False). Run against that
stub, test_breaker_disables_after_two_errors and
test_breaker_is_scoped_to_exact_args_not_just_tool_name both FAILED --
proving the test can actually detect a missing guard, not just pass
trivially. This is the implementation that turns them GREEN.
"""
from typing import Any, Callable


class ToolDisabledError(Exception):
    """Raised when a (tool, args) pair is blocked after repeated errors."""


class ToolBreaker:
    FAILURE_THRESHOLD = 2

    def __init__(self):
        self._failures: dict[tuple, int] = {}

    @staticmethod
    def _key(tool_name: str, kwargs: dict) -> tuple:
        return (tool_name, tuple(sorted(kwargs.items())))

    def is_disabled(self, tool_name: str, kwargs: dict) -> bool:
        return self._failures.get(self._key(tool_name, kwargs), 0) >= self.FAILURE_THRESHOLD

    def call(self, tool_name: str, tool_fn: Callable[..., Any], **kwargs) -> Any:
        key = self._key(tool_name, kwargs)
        if self._failures.get(key, 0) >= self.FAILURE_THRESHOLD:
            raise ToolDisabledError(
                f"{tool_name}{kwargs} disabled after {self.FAILURE_THRESHOLD} "
                f"consecutive errors for these exact args"
            )
        result = tool_fn(**kwargs)
        if getattr(result, "error", None) is not None:
            self._failures[key] = self._failures.get(key, 0) + 1
        else:
            self._failures[key] = 0  # reset on success
        return result
