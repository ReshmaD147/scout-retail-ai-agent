"""Tests for understand_request_node.

Uses the real seeded database (via find_store_by_location) rather than
a mock, since this node's whole point is to resolve a free-text
location against a real Scout store - never a guessed store_id.
"""

import pytest

from scout.config import get_settings
import scout.agents.understand_request as understand_module
from scout.agents.understand_request import understand_request_node
from scout.orchestration.state import RetailGraphState
from scout.services.intent_service import IntentExtractionResult, StructuredIntent


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _state(**overrides):
    defaults = {"session_id": "S1", "customer_query": "find comfortable work shoes under $100"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


def _llm_result(intent: StructuredIntent, source: str = "llm") -> IntentExtractionResult:
    return IntentExtractionResult(intent=intent, extraction_source=source)


@pytest.fixture
def fake_llm(monkeypatch):
    def apply(intent: StructuredIntent, source: str = "llm"):
        monkeypatch.setattr(
            understand_module,
            "extract_intent_with_ollama",
            lambda query, fallback_intent: _llm_result(intent, source),
        )

    return apply


def test_extracts_category_budget_pickup_and_resolves_the_location():
    state = _state(
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove."
    )

    update = understand_request_node(state)

    intent = update["intent"]
    assert intent["category"] == "Footwear"
    assert intent["keyword"] == "work"
    assert intent["max_price"] == 100.0
    assert intent["pickup_requested"] is True
    assert intent["location_text"] == "Maple Grove"
    assert intent["selected_store_id"] == "STR-001"
    assert intent["location_resolved"] is True
    assert update["step_count"] == 1
    assert update["evidence"][0].source == "find_store_by_location"


def test_records_a_not_found_error_without_guessing_a_store():
    state = _state(customer_query="Find shoes under $50 near Nowhereville.")

    update = understand_request_node(state)

    intent = update["intent"]
    assert intent["location_resolved"] is False
    assert intent["selected_store_id"] is None
    assert update["errors"][0].error_type == "not_found"
    assert update["errors"][0].agent == "understand_request"


def test_no_location_mentioned_leaves_location_unresolved_without_an_error():
    state = _state(customer_query="Find shoes under $50.")

    update = understand_request_node(state)

    intent = update["intent"]
    assert intent["location_text"] is None
    assert intent["location_resolved"] is False
    assert "errors" not in update


def test_is_idempotent_when_intent_is_already_set():
    state = _state(intent={"category": "Footwear", "already": "set"})

    update = understand_request_node(state)

    assert update == {"step_count": 1}


def test_stops_at_the_step_budget_without_doing_any_extraction(monkeypatch):
    monkeypatch.setenv("MAX_WORKFLOW_STEPS", "3")
    get_settings.cache_clear()
    state = _state(step_count=3)

    update = understand_request_node(state)

    assert update["workflow_status"] == "stopped_at_limit"
    assert update["errors"][0].error_type == "workflow_limit_reached"


def test_extracts_order_request_and_uuid_without_product_search():
    state = _state(
        customer_query="Track order 123e4567-e89b-42d3-a456-426614174000"
    )
    update = understand_request_node(state)
    assert update["intent"]["request_type"] == "order"
    assert update["intent"]["order_id"] == "123e4567-e89b-42d3-a456-426614174000"
    assert update["intent"]["order_action"] == "tracking"
    assert update["intent"]["extraction_source"] == "deterministic_fallback"


def test_extracts_damaged_item_return_with_human_order_id_without_product_search():
    state = _state(
        customer_query="Can I return the coffee maker from order ORD-1005? It arrived damaged."
    )

    update = understand_request_node(state)

    assert update["intent"]["request_type"] == "order"
    assert update["intent"]["order_id"] == "ORD-1005"
    assert update["intent"]["order_action"] == "return_eligibility"
    assert update["intent"]["extraction_source"] == "deterministic_fallback"
    assert "category" not in update["intent"]


def test_order_support_signal_overrides_mistaken_llm_product_search(fake_llm):
    fake_llm(
        StructuredIntent(
            request_type="product_search",
            product_type="Coffee Makers",
            category="Home and Kitchen",
        )
    )

    intent = understand_request_node(
        _state(customer_query="Can I return the coffee maker from order ORD-1005? It arrived damaged.")
    )["intent"]

    assert intent["request_type"] == "order"
    assert intent["order_id"] == "ORD-1005"
    assert intent["order_action"] == "return_eligibility"
    assert intent["extraction_source"] == "deterministic_fallback"


def test_extracts_exact_product_type_and_deals_constraint():
    earbuds = understand_request_node(_state(customer_query="Wireless earbuds"))["intent"]
    assert earbuds["category"] == "Electronics"
    assert earbuds["subcategory"] == "Earbuds"
    assert earbuds["deals_only"] is False

    coffee_deals = understand_request_node(_state(customer_query="Coffee maker deals"))["intent"]
    assert coffee_deals["category"] == "Home and Kitchen"
    assert coffee_deals["subcategory"] == "Coffee Makers"
    assert coffee_deals["deals_only"] is True


def test_structured_filters_override_looser_natural_language_values():
    update = understand_request_node(
        _state(
            customer_query="Show me electronics",
            requested_filters={
                "category": "Electronics",
                "product_type": "Earbuds",
                "max_price": 100.0,
                "attributes": ["connectivity:Bluetooth 5.3"],
                "in_stock_only": True,
                "fulfillment": "delivery",
            },
        )
    )
    intent = update["intent"]
    assert intent["subcategory"] == "Earbuds"
    assert intent["max_price"] == 100.0
    assert intent["attribute_filters"] == ["connectivity:Bluetooth 5.3"]
    assert intent["pickup_requested"] is False
    assert intent["fulfillment"] == "delivery"


def test_llm_product_search_intent_preserves_query_and_legacy_fields(fake_llm):
    fake_llm(
        StructuredIntent(
            request_type="product_search",
            product_type="Work",
            category="Footwear",
            use_case="standing all day",
            attributes=["comfort", "slip resistant"],
            confidence=0.92,
        )
    )

    update = understand_request_node(_state(customer_query="Need comfortable work shoes"))

    intent = update["intent"]
    assert intent["request_type"] == "recommendation"
    assert intent["structured_intent"]["request_type"] == "product_search"
    assert intent["subcategory"] == "Work"
    assert intent["category"] == "Footwear"
    assert intent["keyword"] == "standing all day"
    assert intent["attribute_filters"] == ["comfort", "slip resistant"]
    assert intent["extraction_source"] == "llm"
    assert update["intent_extraction_source"] == "llm"
    assert update["structured_intent"].request_type == "product_search"


def test_llm_deals_intent_sets_existing_deals_flag(fake_llm):
    fake_llm(StructuredIntent(request_type="deals", product_type="Coffee Makers", category="Home and Kitchen"))

    intent = understand_request_node(_state(customer_query="Coffee maker deals"))["intent"]

    assert intent["deals_only"] is True
    assert intent["structured_intent"]["request_type"] == "deals"


def test_llm_compare_intent_keeps_comparison_ids_in_structured_intent(fake_llm):
    fake_llm(
        StructuredIntent(
            request_type="compare",
            comparison_product_ids=["FTW-001", "FTW-004"],
            category="Footwear",
        )
    )

    intent = understand_request_node(_state(customer_query="Compare FTW-001 and FTW-004"))["intent"]

    assert intent["structured_intent"]["request_type"] == "compare"
    assert intent["structured_intent"]["comparison_product_ids"] == ["FTW-001", "FTW-004"]


def test_llm_find_similar_intent_keeps_reference_product_id(fake_llm):
    fake_llm(StructuredIntent(request_type="find_similar", reference_product_id="FTW-004"))

    intent = understand_request_node(_state(customer_query="Find similar products to FTW-004"))["intent"]

    assert intent["structured_intent"]["request_type"] == "find_similar"
    assert intent["structured_intent"]["reference_product_id"] == "FTW-004"


def test_llm_pickup_preference_location_budget_and_urgency(fake_llm):
    fake_llm(
        StructuredIntent(
            request_type="product_search",
            product_type="Work",
            category="Footwear",
            budget_max=100.0,
            location="Maple Grove",
            fulfillment_preference="pickup",
            urgency="today",
        )
    )

    update = understand_request_node(
        _state(customer_query="Find work shoes under $100 for pickup today near Maple Grove")
    )

    intent = update["intent"]
    assert intent["max_price"] == 100.0
    assert intent["pickup_requested"] is True
    assert intent["fulfillment"] == "pickup"
    assert intent["location_text"] == "Maple Grove"
    assert intent["selected_store_id"] == "STR-001"
    assert intent["structured_intent"]["urgency"] == "today"


def test_llm_order_status_intent_uses_order_agent_route(fake_llm):
    fake_llm(
        StructuredIntent(
            request_type="order_status",
            order_id="123e4567-e89b-42d3-a456-426614174000",
        )
    )

    intent = understand_request_node(
        _state(customer_query="Status for order 123e4567-e89b-42d3-a456-426614174000")
    )["intent"]

    assert intent["request_type"] == "order"
    assert intent["order_action"] == "status"
    assert intent["order_id"] == "123e4567-e89b-42d3-a456-426614174000"


def test_llm_cancellation_eligibility_intent_uses_order_agent_route(fake_llm):
    fake_llm(StructuredIntent(request_type="order_eligibility"))

    intent = understand_request_node(_state(customer_query="Can I cancel my order?"))["intent"]

    assert intent["request_type"] == "order"
    assert intent["order_action"] == "cancel_eligibility"


def test_llm_vague_request_keeps_one_clarification_question(fake_llm):
    fake_llm(
        StructuredIntent(
            request_type="clarification",
            needs_clarification=True,
            clarification_question="What product should I look for?",
        )
    )

    intent = understand_request_node(_state(customer_query="I need help"))["intent"]

    assert intent["needs_clarification"] is True
    assert intent["clarification_question"] == "What product should I look for?"


def test_llm_out_of_scope_request_is_recorded_without_domain_facts(fake_llm):
    fake_llm(StructuredIntent(request_type="out_of_scope", needs_clarification=True))

    intent = understand_request_node(_state(customer_query="Write me a poem"))["intent"]

    assert intent["structured_intent"]["request_type"] == "out_of_scope"
    assert intent["category"] is None
    assert intent["max_price"] is None
