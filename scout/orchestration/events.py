"""Safe-event vocabulary for Scout's workflow activity (Step 13).

Shared by two callers so the same internal activity is never described
two different ways:

- `scout/api/routes/chat.py` (Step 12) uses `activity_labels_for_tool_results`
  to build the non-streaming `ChatResponse.activity_events` list.
- `scout/api/routes/chat_stream.py` (Step 13) uses everything in this
  module to turn each LangGraph node's partial state update
  (`compiled_graph.astream(..., stream_mode="updates")`) into one or
  more customer-safe `StreamEvent` objects.

Nothing here ever holds a prompt, a model's reasoning, a raw tool
argument, SQL, or an internal exception - only a fixed vocabulary of
short, human-readable phrases mapped from internal, already-safe
identifiers (a node name, a tool name, a `next_agent` decision string).
CLAUDE.md section 9 ("safe trace data") and section 12 ("never log...
hidden prompts, chain-of-thought") apply here exactly as they already
do to `ToolCallTrace` itself - this module only ever *relabels* data
that was already safe to log.
"""

from typing import Dict, List, Optional, Tuple

from scout.orchestration.state import ToolCallTrace

TOOL_LABELS: Dict[str, str] = {
    "semantic_search_products": "Recommendation Agent searching products",
    "search_products": "Recommendation Agent searching products",
    "rank_products": "Preparing response",
    "get_promotions": "Verifying claims",
    "check_store_inventory": "Inventory Agent checking selected store",
    "availability_evaluation": "Preparing response",
    "find_nearby_inventory": "Inventory Agent checking nearby stores",
    "check_network_inventory": "Inventory Agent checking nearby stores",
    "get_delivery_estimate": "Inventory Agent checking nearby stores",
    "find_available_substitutes": "Finding available substitutes",
    "search_external_offers": "External Offer Agent searching alternatives",
    "lookup_order": "Order Agent retrieving order evidence",
    "retrieve_policy_sections": "Policy Agent retrieving policy evidence",
    "lookup_latest_order": "Order Agent retrieving order evidence",
    "get_order_status": "Order Agent retrieving order evidence",
    "get_payment_status": "Order Agent retrieving order evidence",
    "get_fulfillment_details": "Order Agent retrieving order evidence",
    "check_order_eligibility": "Order Agent retrieving order evidence",
    "get_external_offer_details": "Verifying claims",
    "get_product_details": "Verifying claims",
    "response_verification": "Verifying claims",
}
"""tool_name -> customer-safe label. The single source of truth for
"what does this tool call mean to a customer" - both scout/api/routes/
chat.py and scout/api/routes/chat_stream.py read this, instead of each
keeping its own, possibly-drifting copy."""

_NODE_TOOL_LABEL_OVERRIDES: Dict[Tuple[str, str], str] = {
    ("reranking", "rank_products"): "Preparing response",
    ("recommendation_agent", "rank_products"): "Recommendation Agent searching products",
}
"""(node_name, tool_name) -> a label override, for the one tool that
means something different depending on which node ran it:
`rank_products` is "an initial ranking" in recommendation_agent, but
"getting the final list ready" once reranking runs after every
fulfillment channel has already been checked (scout/agents/
recommendation_agent.py)."""

NEXT_AGENT_LABELS: Dict[str, str] = {
    "recommendation": "Recommendation Agent searching products",
    "inventory": "Inventory Agent checking selected store",
    "order": "Order Agent retrieving order evidence",
    "support": "Policy Agent retrieving policy evidence",
    "external_offer_agent": "External Offer Agent searching alternatives",
    "verification": "Verifying claims",
}
"""The Supervisor's `next_agent` decision string (scout/orchestration/
supervisor.py) -> a customer-safe label for the "agent_selected"
event. "recommendation" and Step 17's read-only "order" destination are
reachable today. The remaining labels stay ready for later specialist
agents and are not emitted until those graph nodes exist."""


def label_for_tool(tool_name: str, node_name: Optional[str] = None) -> Optional[str]:
    """The customer-safe label for one tool call, or None if unknown.

    Checking `(node_name, tool_name)` first lets a handful of tools
    mean something different depending on which node ran them (see
    `_NODE_TOOL_LABEL_OVERRIDES`) without affecting every other caller
    of that same tool.
    """
    if node_name is not None:
        override = _NODE_TOOL_LABEL_OVERRIDES.get((node_name, tool_name))
        if override is not None:
            return override
    return TOOL_LABELS.get(tool_name)


def label_for_store_inventory_check(location_text: Optional[str]) -> str:
    """A dynamic label for check_store_inventory, naming the actual
    location the customer asked about when one was resolved (e.g.
    "Checking Maple Grove inventory" - one of Step 13's own required
    example labels) - falling back to a generic, still-safe phrase when
    no location text was extracted."""
    return "Inventory Agent checking selected store"


def activity_labels_for_tool_results(tool_results: List[ToolCallTrace]) -> List[str]:
    """The flat, de-duplicated label list `ChatResponse.activity_events`
    (scout/api/routes/chat.py) needs - kept here so the non-streaming
    endpoint and the stream derive it the same way. Only successful
    tool calls are represented; a label appears once, in first-seen
    order."""
    labels: List[str] = []
    seen = set()
    for trace in tool_results:
        if trace.status != "success":
            continue
        label = TOOL_LABELS.get(trace.tool_name)
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return labels
