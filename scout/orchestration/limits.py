"""A shared step-budget guard every Step 10 graph node checks first.

scout/orchestration/supervisor.py already enforces `max_workflow_steps`
at the Supervisor gate, but this graph's pipeline (recommendation ->
inventory -> availability -> nearby -> substitute -> reranking ->
verification) runs several more nodes after the Supervisor's single
decision. `check_step_budget` gives every one of those nodes the same
protection, using the same configuration and the same safe outcome, so
a customer request can never drive an unbounded number of node
executions or tool calls no matter how many candidates or fallback
stages are involved.
"""

import json
from typing import Any, Dict, Optional

from scout.config import get_settings
from scout.orchestration.state import RetailGraphState, ToolCallTrace, WorkflowError
from scout.orchestration.supervisor import SAFE_FAILURE_MESSAGE

__all__ = ["SAFE_FAILURE_MESSAGE", "account_for_node_update", "check_step_budget", "check_workflow_limits"]
"""SAFE_FAILURE_MESSAGE is re-exported here (defined once, in
scout/orchestration/supervisor.py) so every way a Step 10 node can stop
a workflow without a real answer - Supervisor limits or this pipeline's
own limits - shows the customer the exact same fixed sentence, never
two subtly different ones that could drift apart."""


def check_step_budget(state: RetailGraphState) -> Optional[Dict[str, Any]]:
    """Return a stop-update if the step budget is already exhausted.

    Args:
        state: The current shared graph state.

    Returns:
        None if the node calling this should proceed normally. A
        partial state update (workflow_status="stopped_at_limit",
        next_agent=None, a "workflow_limit_reached" WorkflowError, and
        the fixed safe-failure message) if `state.step_count` has
        already reached `max_workflow_steps` - the caller must return
        this immediately without doing any further work (no tool
        calls, no further reads).
    """
    settings = get_settings()
    if state.step_count < settings.max_workflow_steps:
        return None

    return {
        "workflow_status": "stopped_at_limit",
        "next_agent": None,
        "stop_reason": "workflow_step_limit",
        "errors": [
            WorkflowError(
                error_type="workflow_limit_reached",
                message="Maximum workflow steps reached before the goal was completed.",
                agent="graph",
            )
        ],
        "final_response": SAFE_FAILURE_MESSAGE,
    }


_NON_MCP_TRACE_NAMES = {"supervisor_decision", "response_verification", "availability_evaluation"}
_NO_OP_SUMMARY_PREFIXES = (
    "no candidates",
    "no candidate",
    "no nearby search needed",
    "no substitute search needed",
    "no delivery search needed",
)


def _stop_update(reason: str, message: str) -> Dict[str, Any]:
    return {
        "workflow_status": "stopped_at_limit",
        "next_agent": None,
        "stop_reason": reason,
        "errors": [
            WorkflowError(
                error_type="workflow_limit_reached",
                message=message,
                agent="graph",
            )
        ],
        "final_response": SAFE_FAILURE_MESSAGE,
    }


def _trace_is_tool_call(trace: ToolCallTrace) -> bool:
    if trace.tool_name in _NON_MCP_TRACE_NAMES or trace.status not in {"success", "error"}:
        return False
    normalized_summary = trace.summary.strip().lower()
    return not any(normalized_summary.startswith(prefix) for prefix in _NO_OP_SUMMARY_PREFIXES)


def _trace_signature(trace: ToolCallTrace) -> str:
    signature_payload: Dict[str, Any] = {"tool_name": trace.tool_name}
    if trace.validated_arguments:
        signature_payload["validated_arguments"] = trace.validated_arguments
    else:
        signature_payload["summary"] = trace.summary
    return json.dumps(
        signature_payload,
        sort_keys=True,
        separators=(",", ":"),
    )


def check_workflow_limits(state: RetailGraphState) -> Optional[Dict[str, Any]]:
    """Stop before doing more autonomous work when any hard limit is exhausted."""
    step_update = check_step_budget(state)
    if step_update is not None:
        return step_update

    settings = get_settings()
    if state.iteration_count >= settings.max_agent_iterations:
        return _stop_update(
            "agent_iteration_limit",
            "Maximum agent iterations reached before the goal was completed.",
        )
    if state.tool_call_count >= settings.max_tool_calls:
        return _stop_update(
            "tool_call_limit",
            "Maximum tool calls reached before the goal was completed.",
        )
    for signature, count in state.repeated_call_counts.items():
        if count > settings.max_identical_tool_call_count:
            return _stop_update(
                "repeated_tool_call_limit",
                f"Repeated tool-call limit reached for {signature}.",
            )
    return None


def account_for_node_update(
    state: RetailGraphState,
    update: Dict[str, Any],
    *,
    counts_as_iteration: bool,
    counts_tool_calls: bool = True,
) -> Dict[str, Any]:
    """Apply iteration/tool-call accounting to a node update and stop if it crosses a limit."""
    settings = get_settings()
    if not update:
        return update
    if update.get("workflow_status") in {"failed", "stopped_at_limit"}:
        return update

    tool_results = [
        trace for trace in update.get("tool_results", []) if counts_tool_calls and _trace_is_tool_call(trace)
    ]
    next_iteration_count = state.iteration_count + (1 if counts_as_iteration else 0)
    next_tool_call_count = state.tool_call_count + len(tool_results)
    next_repeated = dict(state.repeated_call_counts)
    repeated_limit_hit = False
    for trace in tool_results:
        signature = _trace_signature(trace)
        next_repeated[signature] = next_repeated.get(signature, 0) + 1
        repeated_limit_hit = repeated_limit_hit or next_repeated[signature] > settings.max_identical_tool_call_count

    update = dict(update)
    if counts_as_iteration:
        update["iteration_count"] = 1
    if tool_results:
        update["tool_call_count"] = len(tool_results)
    update["repeated_call_counts"] = next_repeated

    if next_iteration_count > settings.max_agent_iterations:
        update.update(_stop_update("agent_iteration_limit", "Maximum agent iterations reached before the goal was completed."))
    elif next_tool_call_count > settings.max_tool_calls:
        update.update(_stop_update("tool_call_limit", "Maximum tool calls reached before the goal was completed."))
    elif repeated_limit_hit:
        update.update(_stop_update("repeated_tool_call_limit", "A tool call repeated with identical arguments."))
    return update
