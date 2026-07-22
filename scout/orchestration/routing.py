"""Routing: translate the Supervisor's decision into a graph destination.

Step 10 will wire `route_from_supervisor` into an actual LangGraph
`StateGraph` as a conditional edge function; for now it is a small,
independently testable pure function with no graph attached.

This function deliberately contains no planning intelligence of its
own - it only maps `state.next_agent` (a decision already made and
validated by supervisor_node) to a destination name. Which agent runs,
in what order, and whether multiple agents are needed is decided
entirely by the Supervisor's decision and plan
(scout/orchestration/supervisor_decision.py,
scout/orchestration/supervisor.py) - never hardcoded here. This is what
"do not hide the complete plan inside hardcoded routing" means in
practice: swap the Supervisor's policy for a different plan and this
function's behavior changes with it, because it only ever reads
`next_agent`.
"""

from langgraph.graph import END

from scout.orchestration.state import RetailGraphState

_PAUSED_OR_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "stopped_at_limit",
    "awaiting_confirmation",
    "awaiting_clarification",
}

_DECISION_TO_NODE = {
    "recommendation": "recommendation_agent",
    "inventory": "inventory_agent",
    "order": "order_agent",
    "support": "support_agent",
    "verification": "verification_agent",
}
"""Only the five decisions that route to a specialist agent appear
here. "finish" and "safe_failure" end the graph; "clarification" and
"confirmation" pause it - both are already handled by the
workflow_status check below, since supervisor_node always sets one of
_PAUSED_OR_TERMINAL_STATUSES for those four decisions."""


def route_from_supervisor(state: RetailGraphState) -> str:
    """Return the LangGraph destination name for the current state.

    Reads only `state.workflow_status` and `state.next_agent`, both set
    exclusively by `supervisor_node`'s application of the Supervisor's
    decision. An unrecognized or missing `next_agent` falls back to
    `END` - the safe default when it is unclear where to route, rather
    than guessing a destination.
    """
    if state.workflow_status in _PAUSED_OR_TERMINAL_STATUSES:
        return END

    return _DECISION_TO_NODE.get(state.next_agent, END)
