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
from scout.mcp.product_tools import get_product_details as _real_get_product_details
from scout.orchestration.graph import build_retail_graph, run_graph
from scout.orchestration.limits import SAFE_FAILURE_MESSAGE


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
    assert [c.product_id for c in result.product_candidates] == ["FTW-004"]
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
    calls = {"count": 0}

    def _flaky_get_product_details(product_id):
        calls["count"] += 1
        result = _real_get_product_details(product_id)
        if calls["count"] == 1 and result.error is None:
            corrupted = result.model_copy(deep=True)
            corrupted.product.name = "Corrupted Name From A Bad Read"
            return corrupted
        return result

    monkeypatch.setattr("scout.agents.response_verification.get_product_details", _flaky_get_product_details)

    result = run_graph(
        session_id="S9",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    assert result.workflow_status == "completed"
    assert result.correction_count == 1
    assert "ComfortPro Shift Support" in result.final_response
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

    result = run_graph(
        session_id="S10",
        customer_query="Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    )

    settings = get_settings()
    assert result.workflow_status == "failed"
    assert result.final_response == SAFE_FAILURE_MESSAGE
    assert result.correction_count == settings.max_correction_attempts
    assert sum(1 for error in result.errors if error.step == "verify_product_name") >= settings.max_correction_attempts + 1


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
