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
    "search_products": "Searching the product catalog",
    "rank_products": "Ranking matching products",
    "check_store_inventory": "Checking your selected store's inventory",
    "availability_evaluation": "Comparing fulfillment options",
    "find_nearby_inventory": "Searching nearby stores",
    "check_network_inventory": "Checking network availability",
    "get_delivery_estimate": "Estimating delivery options",
    "find_available_substitutes": "Finding available substitutes",
    "search_external_offers": "Searching external retailers",
    "get_external_offer_details": "Verifying external retailer offers",
    "get_product_details": "Verifying product details",
    "response_verification": "Verifying product details",
}
"""tool_name -> customer-safe label. The single source of truth for
"what does this tool call mean to a customer" - both scout/api/routes/
chat.py and scout/api/routes/chat_stream.py read this, instead of each
keeping its own, possibly-drifting copy."""

_NODE_TOOL_LABEL_OVERRIDES: Dict[Tuple[str, str], str] = {
    ("reranking", "rank_products"): "Preparing your response",
}
"""(node_name, tool_name) -> a label override, for the one tool that
means something different depending on which node ran it:
`rank_products` is "an initial ranking" in recommendation_agent, but
"getting the final list ready" once reranking runs after every
fulfillment channel has already been checked (scout/agents/
recommendation_agent.py)."""

NEXT_AGENT_LABELS: Dict[str, str] = {
    "recommendation": "Searching the product catalog",
    "inventory": "Checking inventory",
    "order": "Looking up your order",
    "support": "Checking store policies",
    "verification": "Verifying product details",
}
"""The Supervisor's `next_agent` decision string (scout/orchestration/
supervisor.py) -> a customer-safe label for the "agent_selected"
event. Only "recommendation" is reachable by today's graph (see
scout/orchestration/graph.py's module docstring) - the rest are kept
for forward compatibility with future specialist agents, and are
simply never emitted today."""


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
    if location_text:
        return f"Checking {location_text} inventory"
    return "Checking your selected store's inventory"


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
