import pytest

from scout.mcp.registry import registered_mcp_tool_names
from scout.mcp.schemas import ProductSummary
from scout.orchestration.state import RetailGraphState
from scout.orchestration.tool_registry import (
    AUTONOMOUS_TOOL_NAMES,
    EXPLICITLY_REJECTED_TOOL_NAMES,
    EXTERNAL_OFFER_TOOL_NAMES,
    INVENTORY_TOOL_NAMES,
    ORDER_READ_ONLY_TOOL_NAMES,
    RECOMMENDATION_TOOL_NAMES,
    validate_tool_call,
)


def _state(**overrides):
    defaults = {"session_id": "SESSION-1", "customer_query": "find comfortable work shoes"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


def _product(product_id: str = "FTW-004") -> ProductSummary:
    return ProductSummary(
        product_id=product_id,
        name="ComfortPro Shift Support",
        brand="ComfortPro",
        category="Footwear",
        subcategory="Work Shoes",
        price=79.99,
        rating=4.5,
        review_count=120,
        active=True,
    )


def test_agent_registries_include_only_expected_read_only_tool_names():
    assert {
        "semantic_search_products",
        "search_products",
        "get_product_details",
        "get_promotions",
        "rank_products",
        "find_similar_products",
    } == RECOMMENDATION_TOOL_NAMES
    assert {
        "find_store_by_location",
        "check_store_inventory",
        "find_nearby_inventory",
        "check_network_inventory",
        "get_pickup_estimate",
        "get_delivery_estimate",
        "find_available_substitutes",
    } == INVENTORY_TOOL_NAMES
    assert {
        "search_external_offers",
        "get_external_offer_details",
    } == EXTERNAL_OFFER_TOOL_NAMES
    assert {
        "lookup_order",
        "lookup_latest_order",
        "get_order_status",
        "get_payment_status",
        "get_fulfillment_details",
        "check_order_eligibility",
    } == ORDER_READ_ONLY_TOOL_NAMES


def test_autonomous_tool_names_are_registered_mcp_tool_names():
    assert AUTONOMOUS_TOOL_NAMES <= registered_mcp_tool_names()


def test_no_autonomous_registry_contains_checkout_or_payment_mutations():
    forbidden = {
        "create_checkout",
        "create_checkout_review",
        "confirm_checkout",
        "create_payment_intent",
        "confirm_payment",
    }
    for registry in (RECOMMENDATION_TOOL_NAMES, INVENTORY_TOOL_NAMES, EXTERNAL_OFFER_TOOL_NAMES, ORDER_READ_ONLY_TOOL_NAMES):
        assert registry.isdisjoint(forbidden)


def test_affiliate_tracking_is_not_autonomous():
    assert "track_affiliate_click" in registered_mcp_tool_names()
    assert "track_affiliate_click" not in AUTONOMOUS_TOOL_NAMES
    for registry in (RECOMMENDATION_TOOL_NAMES, INVENTORY_TOOL_NAMES, EXTERNAL_OFFER_TOOL_NAMES, ORDER_READ_ONLY_TOOL_NAMES):
        assert "track_affiliate_click" not in registry


def test_no_autonomous_registry_contains_order_mutations():
    forbidden = {
        "create_order",
        "cancel_order",
        "issue_refund",
        "process_return",
        "process_exchange",
        "update_order",
    }
    for registry in (RECOMMENDATION_TOOL_NAMES, INVENTORY_TOOL_NAMES, EXTERNAL_OFFER_TOOL_NAMES, ORDER_READ_ONLY_TOOL_NAMES):
        assert registry.isdisjoint(forbidden)


def test_unknown_mcp_tool_is_rejected():
    result = validate_tool_call("recommendation", "mystery_mcp_tool", {}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.code == "tool_not_allowed"


def test_generic_mcp_execution_is_unavailable():
    result = validate_tool_call("inventory", "generic_mcp_execution", {"tool": "check_store_inventory"}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.code == "tool_not_allowed"


@pytest.mark.parametrize(
    "tool_name",
    sorted(EXPLICITLY_REJECTED_TOOL_NAMES),
)
def test_explicitly_rejected_tools_are_never_allowed(tool_name):
    result = validate_tool_call("recommendation", tool_name, {}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.code == "tool_not_allowed"
    assert result.rejection.to_workflow_error().error_type == "validation_error"
    assert result.rejection.to_tool_trace().status == "error"


def test_unregistered_cross_agent_tool_is_rejected():
    result = validate_tool_call("recommendation", "check_store_inventory", {}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.code == "tool_not_allowed"
    assert "not registered" in result.rejection.reason


def test_recommendation_product_search_tool_is_allowed():
    result = validate_tool_call(
        "recommendation",
        "semantic_search_products",
        {"query_text": "comfortable work shoes", "limit": 20},
        _state(),
    )

    assert result.allowed is True
    assert result.rejection is None


def test_nearby_inventory_requires_location_or_selected_store():
    result = validate_tool_call("inventory", "find_nearby_inventory", {"product_id": "FTW-004"}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.code == "precondition_failed"
    assert result.rejection.reason == "Nearby inventory requires a location or selected store."


def test_nearby_inventory_allows_resolved_coordinates():
    result = validate_tool_call(
        "inventory",
        "find_nearby_inventory",
        {"product_id": "FTW-004", "latitude": 45.0, "longitude": -93.0},
        _state(),
    )

    assert result.allowed is True


def test_pickup_estimate_requires_valid_store():
    result = validate_tool_call("inventory", "get_pickup_estimate", {"product_id": "FTW-004"}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.reason == "Pickup estimate requires a valid store."


def test_pickup_estimate_requires_verified_pickup_stock():
    result = validate_tool_call(
        "inventory",
        "get_pickup_estimate",
        {"product_id": "FTW-004", "store_id": "STR-001"},
        _state(inventory_results=[]),
    )

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.reason == "Pickup estimate requires verified pickup stock at the store."


def test_pickup_estimate_allows_verified_pickup_stock():
    state = _state(
        inventory_results=[
            {
                "product_id": "FTW-004",
                "store_id": "STR-001",
                "channel": "selected_store",
                "sellable_quantity": 2,
            }
        ]
    )

    result = validate_tool_call(
        "inventory",
        "get_pickup_estimate",
        {"product_id": "FTW-004", "store_id": "STR-001"},
        state,
    )

    assert result.allowed is True


def test_substitutes_require_product_or_product_requirements():
    result = validate_tool_call("inventory", "find_available_substitutes", {}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.reason == "Substitutes require a product or product requirements."


def test_substitutes_allow_existing_candidate_product():
    result = validate_tool_call(
        "inventory",
        "find_available_substitutes",
        {},
        _state(product_candidates=[_product()]),
    )

    assert result.allowed is True


def test_external_search_requires_insufficient_internal_options():
    state = _state(product_candidates=[_product()], inventory_results=[{"product_id": "FTW-004", "sellable_quantity": 1}])

    result = validate_tool_call("external_offer", "search_external_offers", {"query_text": "shoes"}, state)

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.reason == "External search requires evidence that internal options are insufficient."


def test_external_search_allowed_for_explicit_external_request():
    result = validate_tool_call(
        "external_offer",
        "search_external_offers",
        {"query_text": "external shoes"},
        _state(customer_query="show external shoes from another retailer"),
    )

    assert result.allowed is True


def test_external_search_allowed_after_successful_internal_exhaustion():
    state = _state(
        product_candidates=[_product()],
        inventory_results=[{"product_id": "FTW-004", "sellable_quantity": 0}],
        tool_results=[{"tool_name": "check_network_inventory", "status": "success", "summary": "none available"}],
    )

    result = validate_tool_call("external_offer", "search_external_offers", {"query_text": "shoes"}, state)

    assert result.allowed is True


def test_failed_inventory_check_does_not_prove_external_fallback_allowed():
    state = _state(
        product_candidates=[_product()],
        tool_results=[
            {"tool_name": "check_network_inventory", "status": "error", "summary": "timeout"},
        ],
    )

    result = validate_tool_call("external_offer", "search_external_offers", {"query_text": "shoes"}, state)

    assert result.allowed is False


def test_order_lookup_requires_session_and_order_identifier():
    result = validate_tool_call("order", "lookup_order", {"session_id": "SESSION-1"}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.reason == "Order lookup requires a session and order identifier."


def test_order_lookup_allows_session_and_order_identifier():
    result = validate_tool_call(
        "order",
        "lookup_order",
        {"session_id": "SESSION-1", "order_id": "ord-1"},
        _state(),
    )

    assert result.allowed is True


def test_latest_order_lookup_requires_session_identifier():
    result = validate_tool_call("order", "lookup_latest_order", {}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.reason == "Latest order lookup requires a session identifier."


def test_latest_order_lookup_allows_session_identifier():
    result = validate_tool_call("order", "lookup_latest_order", {"session_id": "SESSION-1"}, _state())

    assert result.allowed is True


def test_comparison_requires_at_least_two_product_ids():
    result = validate_tool_call("recommendation", "rank_products", {"product_ids": ["FTW-004"]}, _state())

    assert result.allowed is False
    assert result.rejection is not None
    assert result.rejection.reason == "Comparison requires at least two product IDs."


def test_comparison_allows_two_product_ids():
    result = validate_tool_call(
        "recommendation",
        "rank_products",
        {"product_ids": ["FTW-004", "FTW-008"]},
        _state(),
    )

    assert result.allowed is True


def test_autonomous_agents_still_do_not_have_support_mutation_tools():
    forbidden = {"issue_refund", "cancel_order", "process_return", "create_payment_intent", "confirm_payment"}
    assert AUTONOMOUS_TOOL_NAMES.isdisjoint(forbidden)
