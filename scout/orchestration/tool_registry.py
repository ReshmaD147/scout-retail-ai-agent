"""Code-enforced tool registries for autonomous Scout agents.

This module is intentionally independent from the MCP server registry:
the MCP server can expose tools used by REST endpoints or explicit user
actions, while autonomous agents must pass through these narrower allow
lists and deterministic preconditions before any tool call is attempted.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Set

from pydantic import BaseModel, Field

from scout.orchestration.state import RetailGraphState, ToolCallTrace, WorkflowError

AgentName = Literal["recommendation", "inventory", "external_offer", "order"]

RECOMMENDATION_TOOL_NAMES: Set[str] = {
    "semantic_search_products",
    "search_products",
    "get_product_details",
    "get_promotions",
    "rank_products",
    "find_similar_products",
}

INVENTORY_TOOL_NAMES: Set[str] = {
    "find_store_by_location",
    "check_store_inventory",
    "find_nearby_inventory",
    "check_network_inventory",
    "get_pickup_estimate",
    "get_delivery_estimate",
    "find_available_substitutes",
}

EXTERNAL_OFFER_TOOL_NAMES: Set[str] = {
    "search_external_offers",
    "get_external_offer_details",
    "track_affiliate_click",
}

ORDER_READ_ONLY_TOOL_NAMES: Set[str] = {
    "lookup_order",
    "lookup_latest_order",
    "get_order_status",
    "get_payment_status",
    "get_fulfillment_details",
    "check_order_eligibility",
}

AGENT_TOOL_REGISTRIES: Dict[AgentName, Set[str]] = {
    "recommendation": RECOMMENDATION_TOOL_NAMES,
    "inventory": INVENTORY_TOOL_NAMES,
    "external_offer": EXTERNAL_OFFER_TOOL_NAMES,
    "order": ORDER_READ_ONLY_TOOL_NAMES,
}

AUTONOMOUS_TOOL_NAMES: Set[str] = set().union(*AGENT_TOOL_REGISTRIES.values())

EXPLICITLY_REJECTED_TOOL_NAMES: Set[str] = {
    "create_checkout",
    "create_checkout_review",
    "create_payment_intent",
    "confirm_payment",
    "confirm_checkout",
    "create_order",
    "reserve_inventory",
    "update_inventory",
    "cancel_order",
    "issue_refund",
    "process_return",
    "process_exchange",
    "update_order",
    "update_shipping_address",
    "execute_sql",
    "run_sql",
    "generic_sql_execution",
    "execute_repository",
    "generic_repository_execution",
    "execute_mcp",
    "generic_mcp_execution",
    "shell",
    "shell_execution",
    "run_shell",
    "http_request",
    "unrestricted_http_execution",
}


class ToolRejection(BaseModel):
    agent_name: AgentName
    tool_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    code: Literal["tool_not_allowed", "precondition_failed"]
    validated_arguments: Dict[str, Any] = Field(default_factory=dict)

    def to_workflow_error(self) -> WorkflowError:
        return WorkflowError(
            error_type="validation_error",
            message=self.reason,
            agent=self.agent_name,
            step=self.tool_name,
        )

    def to_tool_trace(self) -> ToolCallTrace:
        return ToolCallTrace(tool_name=self.tool_name, status="error", summary=self.reason)


class ToolValidationResult(BaseModel):
    allowed: bool
    rejection: Optional[ToolRejection] = None


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _reject(agent_name: AgentName, tool_name: str, reason: str, code: Literal["tool_not_allowed", "precondition_failed"], arguments: Dict[str, Any]) -> ToolValidationResult:
    return ToolValidationResult(
        allowed=False,
        rejection=ToolRejection(
            agent_name=agent_name,
            tool_name=tool_name,
            reason=reason,
            code=code,
            validated_arguments=dict(arguments),
        ),
    )


def _has_location_or_selected_store(state: RetailGraphState, arguments: Dict[str, Any]) -> bool:
    intent = state.intent or {}
    return bool(
        arguments.get("latitude") is not None
        and arguments.get("longitude") is not None
        or arguments.get("store_id")
        or intent.get("selected_store_id")
        or intent.get("location_resolved")
    )


def _has_verified_pickup_stock(state: RetailGraphState, arguments: Dict[str, Any]) -> bool:
    product_id = arguments.get("product_id")
    store_id = arguments.get("store_id")
    return any(
        entry.get("product_id") == product_id
        and entry.get("store_id") == store_id
        and entry.get("channel") == "selected_store"
        and entry.get("sellable_quantity", 0) > 0
        for entry in state.inventory_results
    )


def _internal_options_insufficient(state: RetailGraphState) -> bool:
    if state.external_offers:
        return True
    if not state.product_candidates:
        return True
    return not any(entry.get("sellable_quantity", 0) > 0 for entry in state.inventory_results)


def _validate_preconditions(agent_name: AgentName, tool_name: str, arguments: Dict[str, Any], state: RetailGraphState) -> Optional[str]:
    if tool_name == "find_nearby_inventory" and not _has_location_or_selected_store(state, arguments):
        return "Nearby inventory requires a location or selected store."

    if tool_name == "get_pickup_estimate":
        if _blank(arguments.get("store_id")):
            return "Pickup estimate requires a valid store."
        if not _has_verified_pickup_stock(state, arguments):
            return "Pickup estimate requires verified pickup stock at the store."

    if tool_name == "find_available_substitutes":
        structured_intent = state.structured_intent
        has_requirements = bool(
            arguments.get("product_id")
            or state.product_candidates
            or (structured_intent and (structured_intent.product_type or structured_intent.category or structured_intent.attributes))
        )
        if not has_requirements:
            return "Substitutes require a product or product requirements."

    if tool_name == "search_external_offers" and not _internal_options_insufficient(state):
        return "External search requires evidence that internal options are insufficient."

    if tool_name == "lookup_latest_order":
        if _blank(arguments.get("session_id")):
            return "Latest order lookup requires a session identifier."

    if tool_name in ORDER_READ_ONLY_TOOL_NAMES and tool_name != "lookup_latest_order":
        if _blank(arguments.get("session_id")) or _blank(arguments.get("order_id")):
            return "Order lookup requires a session and order identifier."

    if tool_name == "rank_products":
        product_ids = arguments.get("product_ids") or []
        if len(product_ids) < 2:
            return "Comparison requires at least two product IDs."

    return None


def validate_tool_call(
    agent_name: AgentName,
    tool_name: str,
    validated_arguments: Dict[str, Any],
    state: RetailGraphState,
) -> ToolValidationResult:
    """Validate that an autonomous agent may call a specific MCP tool."""
    if tool_name in EXPLICITLY_REJECTED_TOOL_NAMES:
        return _reject(
            agent_name,
            tool_name,
            f"{tool_name} is not available to autonomous agents.",
            "tool_not_allowed",
            validated_arguments,
        )

    allowed_tools = AGENT_TOOL_REGISTRIES[agent_name]
    if tool_name not in allowed_tools:
        return _reject(
            agent_name,
            tool_name,
            f"{tool_name} is not registered for the {agent_name} agent.",
            "tool_not_allowed",
            validated_arguments,
        )

    precondition_reason = _validate_preconditions(agent_name, tool_name, validated_arguments, state)
    if precondition_reason:
        return _reject(agent_name, tool_name, precondition_reason, "precondition_failed", validated_arguments)

    return ToolValidationResult(allowed=True)
