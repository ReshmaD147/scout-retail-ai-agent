"""The Supervisor node: deterministic safety rules wrapped around a
pluggable decision policy.

`supervisor_node(state, policy)` is a plain function, not yet wired
into a LangGraph graph (Step 10's job) - it takes the current state and
a `SupervisorPolicy` (scout/orchestration/supervisor_policy.py) and
returns a partial state update dict, exactly the contract
scout/orchestration/state.py describes for any graph node.

Two layers, checked in this order, every turn:

1. Deterministic safety and stopping rules (allowed to be hardcoded
   per this phase's instructions) - these run *before* the policy is
   ever consulted, so a misbehaving or unavailable model can never
   bypass a limit:
   - Already terminal or paused (completed/failed/stopped_at_limit/
     awaiting_confirmation/awaiting_clarification): do nothing further
     - this is what makes calling supervisor_node twice on a finished
       workflow safe (no duplicate work, CLAUDE.md section 3).
   - `step_count >= max_workflow_steps`: stop with "stopped_at_limit".
   - `retry_count >= max_retries`: stop with "failed".
2. Otherwise, ask the policy for a `SupervisorDecision` and translate
   it into a state update. Nothing about *which* agent, *how many*
   agents, or *what* the plan is gets hardcoded here - that
   intelligence lives entirely in the decision the policy returns.
"""

from typing import Any, Dict

from scout.config import get_settings
from scout.orchestration.state import RetailGraphState, ToolCallTrace, WorkflowError
from scout.orchestration.supervisor_policy import SupervisorPolicy

SAFE_FAILURE_MESSAGE = (
    "I wasn't able to complete this request safely. Please try again, "
    "or rephrase what you're looking for."
)
"""Shown to the customer for both `stopped_at_limit` and `failed`
outcomes reached via the deterministic limit checks or a
"safe_failure" decision - a fixed, safe sentence, never the model's own
words or any internal detail (CLAUDE.md section 12)."""

_TERMINAL_OR_PAUSED_STATUSES = {
    "completed",
    "failed",
    "stopped_at_limit",
    "awaiting_confirmation",
    "awaiting_clarification",
}

_NON_RETRYABLE_DECISIONS = {"finish", "safe_failure", "clarification", "confirmation"}


def supervisor_node(state: RetailGraphState, policy: SupervisorPolicy) -> Dict[str, Any]:
    """Decide the workflow's next move, or safely stop it.

    Args:
        state: The current shared graph state.
        policy: Anything implementing `SupervisorPolicy.decide()` - a
            real `LangChainSupervisorPolicy` in production, a fake in
            tests.

    Returns:
        A partial state update dict (see scout/orchestration/state.py
        for how LangGraph merges this in). Never mutates `state`.
    """
    if state.workflow_status in _TERMINAL_OR_PAUSED_STATUSES:
        return {}

    settings = get_settings()

    if state.step_count >= settings.max_workflow_steps:
        return {
            "workflow_status": "stopped_at_limit",
            "next_agent": None,
            "errors": [
                WorkflowError(
                    error_type="workflow_limit_reached",
                    message="Maximum workflow steps reached before the goal was completed.",
                    agent="supervisor",
                )
            ],
            "final_response": SAFE_FAILURE_MESSAGE,
        }

    if state.retry_count >= settings.max_retries:
        return {
            "workflow_status": "failed",
            "next_agent": None,
            "errors": [
                WorkflowError(
                    error_type="workflow_limit_reached",
                    message="Maximum retries reached for the current step.",
                    agent="supervisor",
                )
            ],
            "final_response": SAFE_FAILURE_MESSAGE,
        }

    decision = policy.decide(state)

    # A "retry" is the Supervisor routing to the same agent it just
    # routed to last turn (i.e. the previous attempt did not resolve
    # things) - moving on to a different agent, or a control decision
    # like "finish", is forward progress and resets the retry budget.
    is_retry = decision.decision == state.next_agent and decision.decision not in _NON_RETRYABLE_DECISIONS
    new_retry_count = state.retry_count + 1 if is_retry else 0

    update: Dict[str, Any] = {
        "step_count": state.step_count + 1,
        "retry_count": new_retry_count,
        "goal": decision.goal,
        "active_agent": "supervisor",
        "next_agent": decision.decision,
        "workflow_status": "in_progress",
        "tool_results": [
            ToolCallTrace(
                tool_name="supervisor_decision", status="success", summary=decision.decision_summary
            )
        ],
    }

    if decision.plan:
        update["plan"] = decision.plan
        update["pending_steps"] = [step.step_id for step in decision.plan if step.status != "completed"]

    if decision.decision == "clarification":
        update["workflow_status"] = "awaiting_clarification"
        update["final_response"] = decision.clarification_question
    elif decision.decision == "confirmation":
        update["workflow_status"] = "awaiting_confirmation"
        # The specific action awaiting confirmation (state.pending_confirmation)
        # is set by the specialist agent that proposed it, not here - the
        # Supervisor only routes into this pause. No specialist exists
        # yet to set it (Order Agent, Phase 15); revisit once one does.
    elif decision.decision == "finish":
        update["workflow_status"] = "completed"
        # Placeholder: the real customer-facing answer belongs to the
        # Response Verification Agent (Phase 11), which does not exist
        # yet. decision_summary is already required to be customer-safe
        # (see SupervisorDecision), so it is a reasonable stand-in
        # final_response until that agent exists to construct one from
        # verified evidence.
        update["final_response"] = decision.decision_summary
    elif decision.decision == "safe_failure":
        update["workflow_status"] = "failed"
        update["final_response"] = SAFE_FAILURE_MESSAGE

    return update
