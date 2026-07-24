"""End-to-end tests for Scout's first complete LangGraph workflow (Step 10).

Each test runs the real, compiled graph (`run_graph`) against the real
seeded database - no mocked tools - so these exercise the actual
routing, not just each node in isolation. Scenarios are the same ones
confirmed by hand against scout/database/seed.py:

- The acceptance query resolves via the nearby-store fallback
  (FTW-004 is out of stock at Maple Grove, in stock at Plymouth).
- A request for an "outdoor boot" near Brooklyn Park forces the
  substitute-search fallback (FTW-010 is out of stock everywhere;
  FTW-002 is a valid in-budget substitute at Brooklyn Park).
- A completely vague request pauses for clarification without ever
  reaching the Recommendation or Inventory agents.
- An unreasonably low MAX_WORKFLOW_STEPS stops the workflow safely
  instead of letting it run unbounded.
- A simulated database failure at the selected store does not crash
  the workflow - it is recorded and the pipeline still recovers via
  the nearby-store fallback.
- A transient Response Verification (Step 11) failure self-heals via
  one correction pass back through the pipeline.
- A persistent Response Verification failure exhausts
  `max_correction_attempts` and safe-fails instead of looping forever.
"""

import sqlite3

import pytest

from scout.config import get_settings
from scout.database.connection import connection_scope
from scout.mcp.product_tools import get_product_details as _real_get_product_details
from scout.orchestration.graph import build_retail_graph, run_graph
from scout.orchestration.limits import SAFE_FAILURE_MESSAGE, account_for_node_update
from scout.orchestration.state import RetailGraphState, ToolCallTrace


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_acceptance_query_resolves_via_nearby_store_fallback():
    result = run_graph(
        session_id="S1",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    assert result.workflow_status == "completed"
    assert [c.product_id for c in result.product_candidates] == ["FTW-004", "FTW-008"]
    assert "ComfortPro Shift Support" in result.final_response
    assert "Plymouth" in result.final_response
    channels = {entry["channel"] for entry in result.inventory_results}
    assert channels == {"selected_store", "nearby_store"}
    assert result.errors == []


def test_a_fully_unavailable_product_resolves_via_substitute_fallback():
    result = run_graph(
        session_id="S2",
        customer_query="Find an outdoor boot under $150 that I can pick up today near Brooklyn Park.",
    )

    assert result.workflow_status == "completed"
    assert [c.product_id for c in result.product_candidates] == ["FTW-002"]
    assert "offered as a substitute for FTW-010" in result.final_response
    channels = [entry["channel"] for entry in result.inventory_results]
    assert "substitute" in channels
    assert "nearby_store" not in channels  # FTW-010 has no stock anywhere nearby either


def test_no_matching_product_produces_the_safe_no_results_message():
    result = run_graph(
        session_id="S3",
        customer_query="Find work shoes under $1 that I can pick up today near Maple Grove.",
    )

    assert result.workflow_status == "completed"
    assert result.product_candidates == []
    assert "couldn't find a product" in result.final_response


def test_a_completely_vague_request_pauses_for_clarification_before_any_agent_runs():
    result = run_graph(session_id="S4", customer_query="hi there")

    assert result.workflow_status == "awaiting_clarification"
    assert result.final_response is not None
    assert result.product_candidates == []
    assert result.inventory_results == []


def test_the_workflow_stops_safely_at_the_step_limit(monkeypatch):
    monkeypatch.setenv("MAX_WORKFLOW_STEPS", "2")
    get_settings.cache_clear()

    result = run_graph(
        session_id="S5",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    assert result.workflow_status == "stopped_at_limit"
    assert result.final_response == SAFE_FAILURE_MESSAGE
    assert any(error.error_type == "workflow_limit_reached" for error in result.errors)


def test_the_workflow_stops_safely_at_the_agent_iteration_limit(monkeypatch):
    monkeypatch.setenv("MAX_AGENT_ITERATIONS", "1")
    get_settings.cache_clear()

    result = run_graph(
        session_id="S5-iterations",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    assert result.workflow_status == "stopped_at_limit"
    assert result.stop_reason == "agent_iteration_limit"
    assert result.final_response == SAFE_FAILURE_MESSAGE


def test_the_workflow_stops_safely_at_the_tool_call_limit(monkeypatch):
    monkeypatch.setenv("MAX_TOOL_CALLS", "1")
    get_settings.cache_clear()

    result = run_graph(
        session_id="S5-tools",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    assert result.workflow_status == "stopped_at_limit"
    assert result.stop_reason == "tool_call_limit"
    assert result.final_response == SAFE_FAILURE_MESSAGE


def test_the_workflow_stops_safely_on_repeated_identical_tool_calls():
    graph = build_retail_graph()
    result = graph.invoke(
        {
            "session_id": "S5-repeat",
            "customer_query": "repeat guard",
            "repeated_call_counts": {'{"summary":"same args","tool_name":"search_products"}': 2},
        }
    )
    state = RetailGraphState.model_validate(result)

    assert state.workflow_status == "stopped_at_limit"
    assert state.stop_reason == "repeated_tool_call_limit"
    assert state.final_response == SAFE_FAILURE_MESSAGE


def test_no_op_tool_traces_do_not_trip_repeated_call_limit():
    state = RetailGraphState(session_id="S5-no-op", customer_query="Work shoes under $100")
    update = {
        "tool_results": [
            ToolCallTrace(tool_name="find_nearby_inventory", status="success", summary="no nearby search needed"),
            ToolCallTrace(tool_name="find_available_substitutes", status="success", summary="no substitute search needed"),
        ]
    }

    accounted = account_for_node_update(state, update, counts_as_iteration=True)

    assert accounted["iteration_count"] == 1
    assert "tool_call_count" not in accounted
    assert accounted["repeated_call_counts"] == {}


def test_a_selected_store_database_failure_does_not_crash_and_recovers_nearby(monkeypatch):
    def _raise(*args, **kwargs):
        raise sqlite3.Error("simulated outage")

    monkeypatch.setattr("scout.agents.inventory_agent.check_store_inventory", _raise)

    result = run_graph(
        session_id="S6",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    assert result.workflow_status == "completed"
    assert any(error.error_type == "database_error" for error in result.errors)
    assert "Plymouth" in result.final_response


def test_a_transient_verification_failure_self_heals_via_one_correction(monkeypatch):
    """The first verification pass sees a corrupted catalog name for
    FTW-004 (simulating a transient bad read) and requests a safe
    correction; the second pass reads the real, matching name and the
    workflow completes normally. Proves the Step 11 correction loop
    (response_verification -> recommendation_agent) actually helps in
    a realistic recoverable scenario, not just that it exists.
    """
    calls = {"pass": 1, "seen": set()}

    def _flaky_get_product_details(product_id):
        if product_id in calls["seen"]:
            calls["pass"] += 1
            calls["seen"] = set()
        calls["seen"].add(product_id)
        result = _real_get_product_details(product_id)
        if calls["pass"] == 1 and result.error is None:
            corrupted = result.model_copy(deep=True)
            corrupted.product.name = "Corrupted Name From A Bad Read"
            return corrupted
        return result

    monkeypatch.setattr("scout.agents.response_verification.get_product_details", _flaky_get_product_details)
    monkeypatch.setenv("MAX_AGENT_ITERATIONS", "20")
    monkeypatch.setenv("MAX_TOOL_CALLS", "20")
    monkeypatch.setenv("MAX_IDENTICAL_TOOL_CALL_COUNT", "2")
    get_settings.cache_clear()

    result = run_graph(
        session_id="S9",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    assert result.workflow_status == "completed"
    assert result.correction_count == 1
    assert any(product.product_id in {"FTW-004", "FTW-008"} for product in result.product_candidates)
    assert "Corrupted Name From A Bad Read" not in result.final_response
    assert any(error.step == "verify_product_name" for error in result.errors)


def test_a_persistent_verification_failure_exhausts_corrections_and_safe_fails(monkeypatch):
    """Every pass sees the same corrupted catalog name, so every
    correction attempt fails too - the workflow must stop with the
    fixed safe-failure message once max_correction_attempts is
    reached, never loop forever and never invent a passing answer.
    """

    def _always_wrong_name(product_id):
        result = _real_get_product_details(product_id)
        if result.error is not None:
            return result
        corrupted = result.model_copy(deep=True)
        corrupted.product.name = "Always Wrong Name"
        return corrupted

    monkeypatch.setattr("scout.agents.response_verification.get_product_details", _always_wrong_name)
    monkeypatch.setenv("MAX_AGENT_ITERATIONS", "20")
    monkeypatch.setenv("MAX_TOOL_CALLS", "20")
    monkeypatch.setenv("MAX_IDENTICAL_TOOL_CALL_COUNT", "2")
    get_settings.cache_clear()

    result = run_graph(
        session_id="S10",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    settings = get_settings()
    assert result.workflow_status == "failed"
    assert result.final_response == SAFE_FAILURE_MESSAGE
    assert result.correction_count == settings.max_correction_attempts
    assert sum(1 for error in result.errors if error.step == "verify_product_name") >= settings.max_correction_attempts


def test_build_retail_graph_compiles_and_is_reusable():
    graph = build_retail_graph()

    first = graph.invoke(
        {"session_id": "S7", "customer_query": "Find work shoes under $100 near Maple Grove."}
    )
    second = graph.invoke(
        {"session_id": "S8", "customer_query": "Find work shoes under $100 near Maple Grove."}
    )

    assert first["workflow_status"] == "completed"
    assert second["workflow_status"] == "completed"


def test_internal_success_never_triggers_external_fallback():
    result = run_graph(
        session_id="S-internal-only",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    assert result.product_candidates
    assert result.external_offers == []
    assert all(trace.tool_name != "search_external_offers" for trace in result.tool_results)


def test_external_fallback_runs_only_after_all_internal_inventory_is_exhausted(monkeypatch):
    monkeypatch.setenv("MAX_TOOL_CALLS", "20")
    get_settings.cache_clear()
    with connection_scope() as connection:
        connection.execute(
            "UPDATE inventory SET quantity_available = 0, quantity_reserved = 0"
        )

    result = run_graph(
        session_id="S-external-fallback",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    assert result.workflow_status == "completed"
    assert result.product_candidates == []
    assert result.external_offers
    assert len(result.external_offers) <= get_settings().max_external_offers
    assert all(offer.match_type == "similar" for offer in result.external_offers)
    assert all(offer.price <= 100 for offer in result.external_offers)
    assert "selected store" in result.final_response
    assert "store-network delivery" in result.final_response
    tool_names = [trace.tool_name for trace in result.tool_results]
    assert "check_network_inventory" in tool_names
    assert "find_available_substitutes" in tool_names
    assert "search_external_offers" in tool_names
    assert tool_names.index("search_external_offers") > tool_names.index("find_available_substitutes")


def test_external_fallback_runs_after_no_internal_catalog_match():
    result = run_graph(
        session_id="S-external-briefcase",
        customer_query="Find executive briefcase under $80 near Maple Grove.",
    )

    tool_names = [trace.tool_name for trace in result.tool_results]
    assert result.workflow_status == "completed"
    assert result.product_candidates == []
    assert [offer.offer_id for offer in result.external_offers] == ["EXT-OFF-010"]
    assert "search_external_offers" in tool_names
    assert tool_names.index("search_external_offers") > tool_names.index("semantic_search_products")


def test_order_status_request_routes_directly_to_order_agent(seeded_db_path):
    from tests.order_helpers import create_pickup_order

    created = create_pickup_order(seeded_db_path, "dynamic-order")

    result = run_graph(
        session_id="dynamic-order",
        customer_query=f"Status for order {created.order_id}",
    )

    tool_names = [trace.tool_name for trace in result.tool_results]
    assert result.workflow_status == "completed"
    assert "lookup_order" in tool_names
    assert "semantic_search_products" not in tool_names
    assert "check_store_inventory" not in tool_names


def test_selected_store_has_stock_skips_nearby_and_substitute_search():
    result = run_graph(
        session_id="dynamic-selected-stock",
        customer_query="Find running shoes under $100 that I can pick up today near Maple Grove.",
    )

    tool_names = [trace.tool_name for trace in result.tool_results]
    assert result.workflow_status == "completed"
    assert "check_store_inventory" in tool_names
    assert "find_nearby_inventory" not in tool_names
    assert "find_available_substitutes" not in tool_names


def test_selected_store_unavailable_supervisor_chooses_another_valid_action():
    result = run_graph(
        session_id="dynamic-selected-unavailable",
        customer_query="Find work shoes under $100 that I can pick up today near Maple Grove.",
    )

    tool_names = [trace.tool_name for trace in result.tool_results]
    assert result.workflow_status == "completed"
    assert "check_store_inventory" in tool_names
    assert any(name in tool_names for name in {"find_nearby_inventory", "check_network_inventory", "find_available_substitutes"})


def test_product_search_without_pickup_does_not_force_external_fallback():
    result = run_graph(session_id="dynamic-product", customer_query="Wireless earbuds under $200")

    tool_names = [trace.tool_name for trace in result.tool_results]
    assert result.workflow_status == "completed"
    assert "semantic_search_products" in tool_names
    assert "search_external_offers" not in tool_names
    assert result.product_candidates or "couldn't find" in result.final_response


def test_pickup_request_uses_recommendation_and_inventory_without_exact_sequence_requirement():
    result = run_graph(
        session_id="dynamic-pickup",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    tool_names = {trace.tool_name for trace in result.tool_results}
    assert result.workflow_status == "completed"
    assert "semantic_search_products" in tool_names
    assert "check_store_inventory" in tool_names
    assert any(
        name in tool_names
        for name in {"find_nearby_inventory", "check_network_inventory", "find_available_substitutes"}
    )
