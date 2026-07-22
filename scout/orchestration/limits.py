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

from typing import Any, Dict, Optional

from scout.config import get_settings
from scout.orchestration.state import RetailGraphState, WorkflowError
from scout.orchestration.supervisor import SAFE_FAILURE_MESSAGE

__all__ = ["SAFE_FAILURE_MESSAGE", "check_step_budget"]
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
        "errors": [
            WorkflowError(
                error_type="workflow_limit_reached",
                message="Maximum workflow steps reached before the goal was completed.",
                agent="graph",
            )
        ],
        "final_response": SAFE_FAILURE_MESSAGE,
    }
