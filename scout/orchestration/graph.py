"""Scout's first complete LangGraph workflow (Step 10; Step 11 adds the
response_verification correction loop).

    START
      -> understand_request
      -> supervisor
      -> [recommendation_agent | order_agent | END] (route_from_supervisor)
      -> inventory_agent
      -> availability_evaluation
      -> [nearby_store_search | reranking]          (route_after_availability)
      -> [substitute_search | reranking]            (route_after_nearby)
      -> reranking
      -> response_verification
      -> [recommendation_agent | END]               (route_after_verification)

See README.md for the diagram and a plain-language explanation of
every node and edge. This module only wires already-built node
functions together - no business logic lives here.

Why the two fallback conditional edges only ever go two places
--------------------------------------------------------
`route_after_availability` and `route_after_nearby` both ask the same
question - are there still candidates with no confirmed sellable stock
anywhere (`products_needing_fulfillment`, scout/agents/inventory_agent.py)
- and either continue the fallback chain or skip straight to reranking.
Nothing about *which* products need fallback or *why* is decided here;
this file only reads the answer an agent node already computed and
recorded in `state.inventory_results`.

Why response_verification can loop back to recommendation_agent
----------------------------------------------------------------
`scout/agents/response_verification.py` (Step 11) rejects any
candidate it cannot re-verify against the catalog and its own
evidence. If *every* candidate fails, it is safe to try again - this
pipeline is entirely read-only until a customer confirms a protected
action (none exist yet), so a fresh pass through
recommendation_agent -> ... -> response_verification cannot repeat any
side effect. `route_after_verification` reads the outcome the verifier
already decided (`workflow_status` back to "in_progress" means "one
more pass, please") - it does not decide anything itself. The verifier
bounds this with `correction_count` / `max_correction_attempts`
(scout/config.py) *in addition to* the graph-wide `step_count` budget
every node already checks, so this can never loop unboundedly even if
both limits were misconfigured.

Why route_from_supervisor's mapping is defensively complete
----------------------------------------------------------------
The graph now contains both the recommendation path and Step 17's
read-only `order_agent`. Unsupported future destinations such as
`support_agent` still map to END. That keeps the shared routing
function safe: a policy cannot send this graph to a node that has not
been implemented yet.
"""

from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from scout.agents.external_offer_agent import external_offer_fallback_node
from scout.agents.order_agent import order_agent_node
from scout.agents.policy_agent import policy_agent_node
from scout.agents.inventory_agent import (
    availability_evaluation_node,
    inventory_agent_node,
    nearby_store_search_node,
    network_delivery_search_node,
    products_needing_fulfillment,
    substitute_search_node,
)
from scout.agents.recommendation_agent import recommendation_agent_node, rerank_node
from scout.agents.response_verification import response_verification_node
from scout.agents.understand_request import understand_request_node
from scout.config import get_settings
from scout.orchestration.limits import account_for_node_update, check_workflow_limits
from scout.orchestration.routing import route_from_supervisor
from scout.orchestration.state import RetailGraphState
from scout.orchestration.supervisor import supervisor_node
from scout.orchestration.supervisor_policy import SupervisorPolicy, get_supervisor_policy

_SUPERVISOR_ROUTES = {
    "recommendation_agent": "recommendation_agent",
    "inventory_agent": "inventory_agent",
    "order_agent": "order_agent",
    "external_offer_agent": "external_offer_agent",
    "policy_agent": "policy_agent",
    "verification_agent": "verification_agent",
    END: "response_renderer",
}


def route_after_availability(state: RetailGraphState) -> str:
    """Skip nearby-store search when every candidate is already fulfillable."""
    return "nearby_store_search" if products_needing_fulfillment(state) else "reranking"


def route_after_nearby(state: RetailGraphState) -> str:
    """Check network delivery only for products still unfulfilled nearby."""
    return "network_delivery_search" if products_needing_fulfillment(state) else "reranking"


def route_after_network_delivery(state: RetailGraphState) -> str:
    """Search internal substitutes only when delivery is also unavailable."""
    return "substitute_search" if products_needing_fulfillment(state) else "reranking"


def route_after_reranking(state: RetailGraphState) -> str:
    """External fallback is reachable only when no internal candidate survived."""
    return "external_offer_fallback" if not state.product_candidates else "response_verification"


def route_after_verification(state: RetailGraphState) -> str:
    """Loop back for one more attempt if the Verifier requested a safe correction.

    response_verification_node sets workflow_status back to
    "in_progress" (rather than "completed" or "failed") exactly when it
    wants a fresh pass - see scout/agents/response_verification.py's
    _request_correction_or_fail. Every other status ends the graph.
    """
    return "recommendation_agent" if state.workflow_status == "in_progress" else END


def inventory_specialist_node(state: RetailGraphState) -> Dict[str, Any]:
    """Run one bounded inventory/fulfillment action, then return to Supervisor."""
    last_correction_index = -1
    for index, trace in enumerate(state.tool_results):
        if trace.tool_name == "response_verification" and trace.status == "error":
            last_correction_index = index
    tool_names = [trace.tool_name for trace in state.tool_results[last_correction_index + 1 :]]
    if "check_store_inventory" not in tool_names:
        return inventory_agent_node(state)
    if "availability_evaluation" not in tool_names:
        return availability_evaluation_node(state)
    if products_needing_fulfillment(state) and "find_nearby_inventory" not in tool_names:
        return nearby_store_search_node(state)
    if products_needing_fulfillment(state) and "check_network_inventory" not in tool_names:
        return network_delivery_search_node(state)
    if products_needing_fulfillment(state) and "find_available_substitutes" not in tool_names:
        return substitute_search_node(state)
    return rerank_node(state)


def verification_agent_node(state: RetailGraphState) -> Dict[str, Any]:
    return response_verification_node(state)


def response_renderer_node(state: RetailGraphState) -> Dict[str, Any]:
    """Final rendering hook; response_verification already builds final_response."""
    return {
        "current_agent": "response_renderer",
        "active_agent": "response_renderer",
        "stop_reason": state.stop_reason or state.workflow_status,
    }


def _bounded_node(
    node,
    *,
    counts_as_iteration: bool = True,
    counts_tool_calls: bool = True,
    enforce_precheck: bool = True,
):
    def wrapped(state: RetailGraphState) -> Dict[str, Any]:
        if enforce_precheck:
            limit_update = check_workflow_limits(state)
            if limit_update is not None:
                return limit_update
        update = node(state)
        return account_for_node_update(
            state,
            update,
            counts_as_iteration=counts_as_iteration,
            counts_tool_calls=counts_tool_calls,
        )

    return wrapped


def build_retail_graph(policy: Optional[SupervisorPolicy] = None):
    """Build and compile Scout's first complete retail workflow graph.

    Args:
        policy: The Supervisor's decision-maker. Defaults to whatever
            `get_supervisor_policy()` (scout/orchestration/supervisor_policy.py)
            selects from centralized configuration. By default this is
            an Ollama-backed Supervisor that falls back to rule-based
            routing automatically if the local model is unreachable.
            Set `SUPERVISOR_POLICY=rule_based` to force deterministic
            routing. Pass an explicit policy to bypass configuration.

    Returns:
        A compiled LangGraph graph. Call `.invoke(...)` directly, or use
        `run_graph()` below for a result already re-validated into a
        RetailGraphState instance.
    """
    active_policy = policy or get_supervisor_policy()
   
    graph = StateGraph(RetailGraphState)

    graph.add_node("understand_request", _bounded_node(understand_request_node, counts_as_iteration=False))
    graph.add_node("supervisor", lambda state: supervisor_node(state, active_policy))
    graph.add_node("recommendation_agent", _bounded_node(recommendation_agent_node))
    graph.add_node("order_agent", _bounded_node(order_agent_node))
    graph.add_node("inventory_agent", _bounded_node(inventory_specialist_node))
    graph.add_node("external_offer_agent", _bounded_node(external_offer_fallback_node))
    graph.add_node("policy_agent", _bounded_node(policy_agent_node))
    graph.add_node(
        "verification_agent",
        _bounded_node(
            verification_agent_node,
            counts_as_iteration=False,
            counts_tool_calls=False,
            enforce_precheck=False,
        ),
    )
    graph.add_node(
        "response_renderer",
        _bounded_node(
            response_renderer_node,
            counts_as_iteration=False,
            counts_tool_calls=False,
            enforce_precheck=False,
        ),
    )

    graph.add_edge(START, "understand_request")
    graph.add_edge("understand_request", "supervisor")
    graph.add_conditional_edges("supervisor", route_from_supervisor, _SUPERVISOR_ROUTES)
    graph.add_edge("order_agent", "supervisor")
    graph.add_edge("recommendation_agent", "supervisor")
    graph.add_edge("inventory_agent", "supervisor")
    graph.add_edge("external_offer_agent", "supervisor")
    graph.add_edge("policy_agent", "supervisor")
    graph.add_conditional_edges(
        "verification_agent",
        route_after_verification,
        {"recommendation_agent": "recommendation_agent", END: "response_renderer"},
    )
    graph.add_edge("response_renderer", END)

    return graph.compile()


def run_graph(policy: Optional[SupervisorPolicy] = None, **initial_state: Any) -> RetailGraphState:
    """Build, run, and return a fully re-validated RetailGraphState.

    LangGraph's own `.invoke()` returns a plain dict whose list fields
    can contain a mix of raw dicts and already-typed sub-models
    (verified directly against this LangGraph version - see the
    Step 10 test suite) - re-validating through RetailGraphState here
    once, at the end, guarantees every caller gets a single, clean,
    fully-typed state back rather than having to know that detail.

    Passes an explicit `recursion_limit` sized off `max_workflow_steps`
    (scout/config.py) rather than trusting LangGraph's own default
    (25 supersteps). Since Step 11 added a real cycle to this graph
    (response_verification -> recommendation_agent, bounded by
    `correction_count`/`max_correction_attempts`), a customer who
    raises MAX_WORKFLOW_STEPS above LangGraph's default must still be
    bounded by *our* configured limit - `check_step_budget`
    (scout/orchestration/limits.py) - not cut off early by an
    unrelated library default, and not allowed to run past it either.

    The +20 buffer (not +1) matters because `check_step_budget` only
    stops a node from doing further *work* once the limit is reached -
    it does not remove the plain (unconditional) edges already wired
    between nodes, so several more nodes still execute, each
    immediately re-detecting the same limit and passing the stop
    signal along, before the graph reaches a conditional edge that
    actually routes to END. The pipeline has at most ~9 nodes per pass,
    so 20 is comfortably more than enough slack for that pass-through,
    however early the limit trips.
    """
    settings = get_settings()
    compiled = build_retail_graph(policy)
    raw_result: Dict[str, Any] = compiled.invoke(
        initial_state, config={"recursion_limit": settings.max_workflow_steps + 20}
    )
    return RetailGraphState.model_validate(raw_result)
