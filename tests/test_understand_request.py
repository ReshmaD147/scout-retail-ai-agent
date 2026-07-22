"""Tests for understand_request_node.

Uses the real seeded database (via find_store_by_location) rather than
a mock, since this node's whole point is to resolve a free-text
location against a real Scout store - never a guessed store_id.
"""

import pytest

from scout.config import get_settings
from scout.agents.understand_request import understand_request_node
from scout.orchestration.state import RetailGraphState


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
