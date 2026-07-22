"""Tests for recommendation_agent_node and rerank_node."""

import pytest

from scout.config import get_settings
from scout.agents.recommendation_agent import recommendation_agent_node, rerank_node
from scout.mcp.schemas import SemanticSearchProductsResult, ToolError
from scout.orchestration.state import RetailGraphState


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _state(**overrides):
    defaults = {"session_id": "S1", "customer_query": "find work shoes under $100"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


# ---------------------------------------------------------------------------
# recommendation_agent_node
# ---------------------------------------------------------------------------


def test_finds_the_single_matching_candidate_within_budget():
    state = _state(intent={"category": "Footwear", "keyword": "work", "max_price": 100.0})

    update = recommendation_agent_node(state)

    candidates = update["product_candidates"]
    assert [c.product_id for c in candidates] == ["FTW-004"]
    assert all(c.price <= 100.0 for c in candidates)
    assert update["evidence"][0].claim.startswith("ComfortPro Shift Support")


def test_excludes_a_candidate_above_budget():
    # FTW-004 ($89.99) is the only Footwear product whose description
    # contains "work" - lowering the budget below it must exclude it,
    # not silently substitute something else.
    state = _state(intent={"category": "Footwear", "keyword": "work", "max_price": 50.0})

    update = recommendation_agent_node(state)

    assert update["product_candidates"] == []


def test_records_a_workflow_error_when_search_products_fails(monkeypatch):
    def _fake_semantic_search_products(**kwargs):
        return SemanticSearchProductsResult(
            products=[],
            count=0,
            retrieval_method="semantic",
            candidates_considered=0,
            error=ToolError(error_type="validation_error", message="max_price must be >= 0"),
        )

    monkeypatch.setattr(
        "scout.agents.recommendation_agent.semantic_search_products", _fake_semantic_search_products
    )
    state = _state(intent={"category": "Footwear", "max_price": -5})

    update = recommendation_agent_node(state)

    assert update["product_candidates"] == []
    assert update["errors"][0].error_type == "validation_error"
    assert update["tool_results"][0].status == "error"


def test_stops_at_the_step_budget(monkeypatch):
    monkeypatch.setenv("MAX_WORKFLOW_STEPS", "1")
    get_settings.cache_clear()
    state = _state(step_count=1, intent={"category": "Footwear"})

    update = recommendation_agent_node(state)

    assert update["workflow_status"] == "stopped_at_limit"


# ---------------------------------------------------------------------------
# rerank_node
# ---------------------------------------------------------------------------


def test_drops_candidates_with_no_confirmed_stock_and_reranks_the_rest():
    state = _state(
        product_candidates=[
            {
                "product_id": "FTW-004",
                "name": "ComfortPro Shift Support",
                "brand": "ComfortPro",
                "category": "Footwear",
                "subcategory": "Work",
                "price": 89.99,
                "rating": 4.7,
                "review_count": 401,
                "active": True,
            },
            {
                "product_id": "FTW-002",
                "name": "TrailMax Ridge Hiker",
                "brand": "TrailMax",
                "category": "Footwear",
                "subcategory": "Hiking",
                "price": 109.99,
                "rating": 4.6,
                "review_count": 245,
                "active": True,
            },
        ],
        inventory_results=[
            {"product_id": "FTW-004", "channel": "nearby_store", "sellable_quantity": 7},
            {"product_id": "FTW-002", "channel": "selected_store", "sellable_quantity": 0},
        ],
    )

    update = rerank_node(state)

    assert [c.product_id for c in update["product_candidates"]] == ["FTW-004"]


def test_returns_empty_candidates_when_nothing_survives():
    state = _state(
        product_candidates=[
            {
                "product_id": "FTW-002",
                "name": "TrailMax Ridge Hiker",
                "brand": "TrailMax",
                "category": "Footwear",
                "subcategory": "Hiking",
                "price": 109.99,
                "rating": 4.6,
                "review_count": 245,
                "active": True,
            }
        ],
        inventory_results=[{"product_id": "FTW-002", "channel": "selected_store", "sellable_quantity": 0}],
    )

    update = rerank_node(state)

    assert update["product_candidates"] == []
    assert "nothing to rerank" in update["tool_results"][0].summary


def test_rerank_stops_at_the_step_budget(monkeypatch):
    monkeypatch.setenv("MAX_WORKFLOW_STEPS", "1")
    get_settings.cache_clear()
    state = _state(step_count=1)

    update = rerank_node(state)

    assert update["workflow_status"] == "stopped_at_limit"


def test_rerank_caps_the_final_result_at_max_recommended_products(monkeypatch):
    monkeypatch.setenv("MAX_RECOMMENDED_PRODUCTS", "1")
    get_settings.cache_clear()
    state = _state(
        product_candidates=[
            {
                "product_id": "FTW-004",
                "name": "ComfortPro Shift Support",
                "brand": "ComfortPro",
                "category": "Footwear",
                "subcategory": "Work",
                "price": 89.99,
                "rating": 4.7,
                "review_count": 401,
                "active": True,
            },
            {
                "product_id": "FTW-002",
                "name": "TrailMax Ridge Hiker",
                "brand": "TrailMax",
                "category": "Footwear",
                "subcategory": "Hiking",
                "price": 109.99,
                "rating": 4.6,
                "review_count": 245,
                "active": True,
            },
        ],
        inventory_results=[
            {"product_id": "FTW-004", "channel": "nearby_store", "sellable_quantity": 7},
            {"product_id": "FTW-002", "channel": "selected_store", "sellable_quantity": 3},
        ],
    )

    update = rerank_node(state)

    assert len(update["product_candidates"]) == 1
    get_settings.cache_clear()