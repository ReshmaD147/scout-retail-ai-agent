"""Tests for the four Inventory and Fulfillment Agent nodes.

Uses the real seeded database throughout, leaning on the scenarios
already confirmed by hand against scout/database/seed.py:

- FTW-004 (ComfortPro Shift Support, $89.99) is out of stock at STR-001
  (Maple Grove) and confirmed in stock at STR-002 (Plymouth).
- FTW-010 (TrailMax CanyonGuard Boot) has zero stock everywhere in the
  seed data, so it always needs a substitute.
- FTW-006, checked at STR-002, is similar-priced enough to FTW-004 to
  be a valid substitute reference in other tests.
"""

import sqlite3

import pytest

from scout.config import get_settings
from scout.agents.inventory_agent import (
    availability_evaluation_node,
    inventory_agent_node,
    nearby_store_search_node,
    network_delivery_search_node,
    products_needing_fulfillment,
    substitute_search_node,
)
from scout.mcp.schemas import ProductSummary
from scout.orchestration.state import RetailGraphState


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _product(product_id, name, price, subcategory="Work"):
    return ProductSummary(
        product_id=product_id,
        name=name,
        brand="Test",
        category="Footwear",
        subcategory=subcategory,
        price=price,
        rating=4.5,
        review_count=100,
        active=True,
    )


def _state(**overrides):
    defaults = {"session_id": "S1", "customer_query": "find work shoes"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


FTW_004 = _product("FTW-004", "ComfortPro Shift Support", 89.99)
FTW_010 = _product("FTW-010", "TrailMax CanyonGuard Boot", 129.99, subcategory="Outdoor")


# ---------------------------------------------------------------------------
# products_needing_fulfillment
# ---------------------------------------------------------------------------


def test_products_needing_fulfillment_finds_unfulfilled_candidates():
    state = _state(
        product_candidates=[FTW_004, FTW_010],
        intent={"selected_store_id": "STR-001"},
        inventory_results=[{"product_id": "FTW-004", "sellable_quantity": 7}],
    )

    assert products_needing_fulfillment(state) == ["FTW-010"]


# ---------------------------------------------------------------------------
# inventory_agent_node
# ---------------------------------------------------------------------------


def test_checks_the_selected_store_and_records_out_of_stock():
    state = _state(product_candidates=[FTW_004], intent={"selected_store_id": "STR-001"})

    update = inventory_agent_node(state)

    entry = update["inventory_results"][0]
    assert entry == {
        "product_id": "FTW-004",
        "channel": "selected_store",
        "store_id": "STR-001",
        "store_name": "Scout Demo Store - Maple Grove",
        "sellable_quantity": 0,
        "status": "out_of_stock",
    }
    assert "not available" in update["evidence"][0].claim


def test_no_candidates_is_a_no_op():
    state = _state(product_candidates=[], intent={"selected_store_id": "STR-001"})

    update = inventory_agent_node(state)

    assert "inventory_results" not in update
    assert update["tool_results"][0].summary == "no candidates to check"


def test_missing_selected_store_skips_pickup_without_a_customer_warning():
    state = _state(product_candidates=[FTW_004], intent={"pickup_requested": False})

    update = inventory_agent_node(state)

    assert "errors" not in update
    assert update["tool_results"][0].status == "success"
    assert "not requested" in update["tool_results"][0].summary


def test_a_database_error_is_recorded_and_does_not_crash(monkeypatch):
    def _raise(*args, **kwargs):
        raise sqlite3.Error("boom")

    monkeypatch.setattr("scout.agents.inventory_agent.check_store_inventory", _raise)
    state = _state(product_candidates=[FTW_004], intent={"selected_store_id": "STR-001"})

    update = inventory_agent_node(state)

    assert update["errors"][0].error_type == "database_error"
    assert update["tool_results"][0].status == "error"


def test_inventory_agent_stops_at_the_step_budget(monkeypatch):
    monkeypatch.setenv("MAX_WORKFLOW_STEPS", "1")
    get_settings.cache_clear()
    state = _state(step_count=1)

    update = inventory_agent_node(state)

    assert update["workflow_status"] == "stopped_at_limit"


# ---------------------------------------------------------------------------
# availability_evaluation_node
# ---------------------------------------------------------------------------


def test_summarizes_how_many_candidates_are_already_fulfilled():
    state = _state(
        product_candidates=[FTW_004, FTW_010],
        intent={"selected_store_id": "STR-001"},
        inventory_results=[{"product_id": "FTW-004", "sellable_quantity": 7}],
    )

    update = availability_evaluation_node(state)

    assert update["tool_results"][0].summary == "1 of 2 candidate(s) confirmed available for pickup today at the selected store"


def test_summarizes_zero_candidates():
    state = _state(product_candidates=[])

    update = availability_evaluation_node(state)

    assert update["tool_results"][0].summary == "no candidates to evaluate"


# ---------------------------------------------------------------------------
# nearby_store_search_node
# ---------------------------------------------------------------------------


def test_finds_the_nearest_fulfillable_store():
    state = _state(
        product_candidates=[FTW_004],
        intent={
            "selected_store_id": "STR-001",
            "selected_store_latitude": 45.0725,
            "selected_store_longitude": -93.4557,
        },
        inventory_results=[
            {
                "product_id": "FTW-004",
                "channel": "selected_store",
                "store_id": "STR-001",
                "sellable_quantity": 0,
            }
        ],
    )

    update = nearby_store_search_node(state)

    nearby_entries = [entry for entry in update["inventory_results"] if entry["channel"] == "nearby_store"]
    assert nearby_entries[0]["store_id"] == "STR-002"
    assert nearby_entries[0]["sellable_quantity"] == 7


def test_skips_the_search_when_nothing_needs_it():
    state = _state(
        product_candidates=[FTW_004],
        inventory_results=[{"product_id": "FTW-004", "channel": "selected_store", "sellable_quantity": 5}],
    )

    update = nearby_store_search_node(state)

    assert "inventory_results" not in update
    assert update["tool_results"][0].summary == "no nearby search needed"


def test_skips_the_search_without_selected_store_coordinates():
    state = _state(
        product_candidates=[FTW_010],
        intent={},
        inventory_results=[{"product_id": "FTW-010", "sellable_quantity": 0}],
    )

    update = nearby_store_search_node(state)

    assert update["tool_results"][0].summary == "no nearby search needed"


def test_a_database_error_is_recorded_and_the_search_continues(monkeypatch):
    def _raise(*args, **kwargs):
        raise sqlite3.Error("boom")

    monkeypatch.setattr("scout.agents.inventory_agent.find_nearby_inventory", _raise)
    state = _state(
        product_candidates=[FTW_004],
        intent={
            "selected_store_id": "STR-001",
            "selected_store_latitude": 45.0725,
            "selected_store_longitude": -93.4557,
        },
        inventory_results=[{"product_id": "FTW-004", "channel": "selected_store", "sellable_quantity": 0}],
    )

    update = nearby_store_search_node(state)

    assert update["errors"][0].error_type == "database_error"




# ---------------------------------------------------------------------------
# network_delivery_search_node
# ---------------------------------------------------------------------------


def test_network_delivery_confirms_store_network_stock_after_local_fallbacks():
    state = _state(
        product_candidates=[FTW_004],
        inventory_results=[
            {"product_id": "FTW-004", "channel": "selected_store", "sellable_quantity": 0},
            {"product_id": "FTW-004", "channel": "nearby_store", "sellable_quantity": 0},
        ],
    )

    update = network_delivery_search_node(state)

    delivery = next(entry for entry in update["inventory_results"] if entry["channel"] == "delivery")
    assert delivery["product_id"] == "FTW-004"
    assert delivery["sellable_quantity"] > 0
    assert delivery["delivery_min_days"] == 3
    assert delivery["delivery_max_days"] == 5
    assert any(trace.tool_name == "get_delivery_estimate" for trace in update["tool_results"])


def test_network_delivery_skips_when_candidate_is_already_fulfilled():
    state = _state(
        product_candidates=[FTW_004],
        inventory_results=[
            {"product_id": "FTW-004", "channel": "nearby_store", "sellable_quantity": 4}
        ],
    )

    update = network_delivery_search_node(state)

    assert "inventory_results" not in update
    assert update["tool_results"][0].summary == "no delivery search needed"


def test_network_delivery_leaves_unavailable_product_for_substitute_search():
    state = _state(
        product_candidates=[FTW_010],
        inventory_results=[
            {"product_id": "FTW-010", "channel": "selected_store", "sellable_quantity": 0}
        ],
    )

    update = network_delivery_search_node(state)

    assert not any(
        entry.get("channel") == "delivery" and entry.get("product_id") == "FTW-010"
        for entry in update["inventory_results"]
    )

# ---------------------------------------------------------------------------
# substitute_search_node
# ---------------------------------------------------------------------------


def test_finds_an_in_budget_substitute_at_the_selected_store():
    state = _state(
        product_candidates=[FTW_010],
        intent={
            "selected_store_id": "STR-003",
            "selected_store_name": "Scout Demo Store - Brooklyn Park",
            "max_price": 150.0,
        },
        inventory_results=[{"product_id": "FTW-010", "channel": "selected_store", "sellable_quantity": 0}],
    )

    update = substitute_search_node(state)

    substitute_ids = [c.product_id for c in update["product_candidates"]]
    assert "FTW-002" in substitute_ids
    entry = next(e for e in update["inventory_results"] if e["channel"] == "substitute")
    assert entry["substitute_for"] == "FTW-010"
    assert entry["store_name"] == "Scout Demo Store - Brooklyn Park"
    assert entry["sellable_quantity"] == 9


def test_rejects_a_substitute_above_the_customers_original_budget():
    state = _state(
        product_candidates=[FTW_010],
        intent={"selected_store_id": "STR-003", "max_price": 50.0},
        inventory_results=[{"product_id": "FTW-010", "channel": "selected_store", "sellable_quantity": 0}],
    )

    update = substitute_search_node(state)

    assert update["product_candidates"] == [FTW_010]
    assert "no in-budget substitute" in update["tool_results"][0].summary


def test_skips_the_search_when_nothing_needs_it():
    state = _state(
        product_candidates=[FTW_004],
        intent={"selected_store_id": "STR-001"},
        inventory_results=[{"product_id": "FTW-004", "sellable_quantity": 5}],
    )

    update = substitute_search_node(state)

    assert update["tool_results"][0].summary == "no substitute search needed"


def test_a_database_error_is_recorded_and_does_not_crash(monkeypatch):
    def _raise(*args, **kwargs):
        raise sqlite3.Error("boom")

    monkeypatch.setattr("scout.agents.inventory_agent.find_available_substitutes", _raise)
    state = _state(
        product_candidates=[FTW_010],
        intent={"selected_store_id": "STR-003", "max_price": 150.0},
        inventory_results=[{"product_id": "FTW-010", "channel": "selected_store", "sellable_quantity": 0}],
    )

    update = substitute_search_node(state)

    assert update["errors"][0].error_type == "database_error"
