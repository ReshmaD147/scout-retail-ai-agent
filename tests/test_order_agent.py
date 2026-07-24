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


def test_order_agent_uses_latest_session_order_and_requires_verification(_use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "agent-order")
    state = RetailGraphState(
        session_id="agent-order",
        customer_query="Where is my order?",
        intent={"request_type": "order", "order_id": None, "order_action": "tracking"},
    )

    update = order_agent_node(state)

    assert update["workflow_status"] == "in_progress"
    assert update["order_context"]["order_id"] == created.order_id
    assert "Payment status: succeeded" in update["final_response"]
    assert any(claim["type"] == "order_ownership" for claim in update["proposed_claims"])
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


def test_real_graph_handles_missing_package_with_policy_context(_use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "agent-missing-package")
    result = run_graph(
        session_id="agent-missing-package",
        customer_query=f"My package is marked delivered but missing for order {created.order_id}",
    )

    assert result.workflow_status == "completed"
    assert result.order_context["order_id"] == created.order_id
    assert result.policy_results
    assert result.policy_results[0]["policy_file"] == "missing_packages.md"
    assert "No replacement, refund, or investigation was opened" in result.final_response
    assert "Source: missing_packages.md" in result.final_response
    approved_types = {claim["type"] for claim in result.verification_result["approved_claims"]}
    assert {"order_ownership", "order_status", "payment_status", "policy_section"} <= approved_types


def test_real_graph_reports_refund_status_without_creating_refund(_use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "agent-refund-status")
    result = run_graph(
        session_id="agent-refund-status",
        customer_query=f"What is the refund status for order {created.order_id}?",
    )

    assert result.workflow_status == "completed"
    assert result.order_context["order_id"] == created.order_id
    assert "do not see a verified refund record" in result.final_response
    assert "No refund was created or changed" in result.final_response
    assert result.policy_results[0]["policy_file"] == "refunds.md"


def test_explicit_order_lookup_enforces_session_ownership(_use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "agent-owner")
    state = RetailGraphState(
        session_id="agent-intruder",
        customer_query=f"Status for order {created.order_id}",
        intent={"request_type": "order", "order_id": created.order_id, "order_action": "status"},
    )

    update = order_agent_node(state)

    assert update["workflow_status"] == "completed"
    assert update["order_context"] is None
    assert "No order was found" in update["final_response"]
    assert update["errors"][0].step == "verify_order_ownership"


def test_missing_package_creates_controlled_support_case(_use_seeded_database):
    from scout.repositories.support_repository import SupportRepository

    created = create_pickup_order(_use_seeded_database, "agent-case")
    result = run_graph(
        session_id="agent-case",
        customer_query=f"I am upset that my package is marked delivered but missing for order {created.order_id}",
    )

    cases = SupportRepository(_use_seeded_database).list_cases_for_session("agent-case")
    assert len(cases) == 1
    assert cases[0]["category"] == "missing_package"
    assert cases[0]["risk_level"] == "high"
    assert cases[0]["case_reference"] in result.final_response
