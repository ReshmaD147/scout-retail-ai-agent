"""Step 17 Order Agent node and graph integration tests."""

import pytest

from scout.agents.order_agent import order_agent_node
from scout.config import get_settings
from scout.orchestration.graph import run_graph
from scout.orchestration.rule_based_policy import RuleBasedSupervisorPolicy
from scout.orchestration.state import RetailGraphState
from tests.order_helpers import create_pickup_order


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield seeded_db_path
    get_settings.cache_clear()


def test_order_agent_uses_latest_session_order_and_completes(_use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "agent-order")
    state = RetailGraphState(
        session_id="agent-order",
        customer_query="Where is my order?",
        intent={"request_type": "order", "order_id": None, "order_action": "tracking"},
    )

    update = order_agent_node(state)

    assert update["workflow_status"] == "completed"
    assert update["order_context"]["order_id"] == created.order_id
    assert "Payment status: succeeded" in update["final_response"]
    assert update["tool_results"][0].tool_name == "lookup_latest_order"


def test_order_agent_only_reports_cancellation_eligibility(_use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "agent-cancel")
    state = RetailGraphState(
        session_id="agent-cancel",
        customer_query=f"Can I cancel order {created.order_id}?",
        intent={
            "request_type": "order",
            "order_id": created.order_id,
            "order_action": "cancel_eligibility",
        },
    )
    update = order_agent_node(state)
    assert "Cancellation eligibility" in update["final_response"]
    assert "No cancellation was performed" in update["final_response"]
    assert update.get("pending_confirmation") is None


def test_rule_based_supervisor_routes_order_request_to_order_agent():
    state = RetailGraphState(
        session_id="s1",
        customer_query="Where is my order?",
        intent={"request_type": "order", "order_id": None, "order_action": "tracking"},
    )
    decision = RuleBasedSupervisorPolicy().decide(state)
    assert decision.decision == "order"
    assert decision.plan[0].agent == "order"


def test_real_graph_handles_order_status_request(_use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "graph-order")
    result = run_graph(session_id="graph-order", customer_query="Where is my order?")
    assert result.workflow_status == "completed"
    assert result.order_context is not None
    assert result.order_context["order_id"] == created.order_id
    assert result.product_candidates == []
