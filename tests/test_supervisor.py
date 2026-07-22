"""Tests for supervisor_node.

A FakePolicy stands in for LangChainSupervisorPolicy throughout - these
tests are about the node's own deterministic rules (limits, retry
bookkeeping, idempotency, decision -> state-update translation), not
about any real model's judgment.
"""

import pytest

from scout.config import get_settings
from scout.orchestration.state import RetailGraphState
from scout.orchestration.supervisor import SAFE_FAILURE_MESSAGE, supervisor_node
from scout.orchestration.supervisor_decision import SupervisorDecision


class FakePolicy:
    def __init__(self, decision: SupervisorDecision):
        self._decision = decision
        self.call_count = 0

    def decide(self, state: RetailGraphState) -> SupervisorDecision:
        self.call_count += 1
        return self._decision


def _state(**overrides):
    defaults = {"session_id": "S1", "customer_query": "find comfortable work shoes under $100"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Deterministic safety rules - checked before the policy is ever consulted
# ---------------------------------------------------------------------------


def test_does_not_consult_the_policy_once_workflow_is_completed():
    policy = FakePolicy(SupervisorDecision(decision="finish", goal="g", decision_summary="done"))
    state = _state(workflow_status="completed")

    update = supervisor_node(state, policy)

    assert update == {}
    assert policy.call_count == 0


@pytest.mark.parametrize(
    "workflow_status",
    ["failed", "stopped_at_limit", "awaiting_confirmation", "awaiting_clarification"],
)
def test_does_not_consult_the_policy_for_any_paused_or_terminal_status(workflow_status):
    policy = FakePolicy(SupervisorDecision(decision="finish", goal="g", decision_summary="done"))
    state = _state(workflow_status=workflow_status)

    update = supervisor_node(state, policy)

    assert update == {}
    assert policy.call_count == 0


def test_stops_deterministically_at_the_max_step_limit(monkeypatch):
    monkeypatch.setenv("MAX_WORKFLOW_STEPS", "5")
    get_settings.cache_clear()
    policy = FakePolicy(SupervisorDecision(decision="recommendation", goal="g", decision_summary="s"))
    state = _state(step_count=5)

    update = supervisor_node(state, policy)

    assert policy.call_count == 0
    assert update["workflow_status"] == "stopped_at_limit"
    assert update["next_agent"] is None
    assert update["errors"][0].error_type == "workflow_limit_reached"
    assert update["final_response"] == SAFE_FAILURE_MESSAGE


def test_stops_deterministically_at_the_max_retry_limit(monkeypatch):
    monkeypatch.setenv("MAX_RETRIES", "2")
    get_settings.cache_clear()
    policy = FakePolicy(SupervisorDecision(decision="recommendation", goal="g", decision_summary="s"))
    state = _state(retry_count=2)

    update = supervisor_node(state, policy)

    assert policy.call_count == 0
    assert update["workflow_status"] == "failed"
    assert update["next_agent"] is None
    assert update["errors"][0].error_type == "workflow_limit_reached"
    assert update["final_response"] == SAFE_FAILURE_MESSAGE


# ---------------------------------------------------------------------------
# Applying a policy decision
# ---------------------------------------------------------------------------


def test_routes_to_the_agent_the_policy_chose():
    policy = FakePolicy(
        SupervisorDecision(decision="inventory", goal="check stock", decision_summary="checking stock")
    )
    state = _state(step_count=0)

    update = supervisor_node(state, policy)

    assert policy.call_count == 1
    assert update["next_agent"] == "inventory"
    assert update["active_agent"] == "supervisor"
    assert update["goal"] == "check stock"
    assert update["step_count"] == 1
    assert update["workflow_status"] == "in_progress"
    assert update["tool_results"][0].tool_name == "supervisor_decision"
    assert update["tool_results"][0].summary == "checking stock"


def test_applies_a_new_plan_when_the_policy_provides_one():
    plan = [
        {"step_id": "1", "description": "check selected store", "agent": "inventory", "status": "pending"},
        {"step_id": "2", "description": "check nearby stores", "agent": "inventory", "status": "pending"},
    ]
    policy = FakePolicy(
        SupervisorDecision(decision="inventory", goal="check stock", decision_summary="planning", plan=plan)
    )
    state = _state()

    update = supervisor_node(state, policy)

    assert [step.step_id for step in update["plan"]] == ["1", "2"]
    assert update["pending_steps"] == ["1", "2"]


def test_does_not_touch_the_plan_when_the_policy_provides_none():
    policy = FakePolicy(
        SupervisorDecision(decision="inventory", goal="check stock", decision_summary="continuing")
    )
    state = _state()

    update = supervisor_node(state, policy)

    assert "plan" not in update
    assert "pending_steps" not in update


def test_clarification_decision_pauses_with_the_question_as_final_response():
    policy = FakePolicy(
        SupervisorDecision(
            decision="clarification",
            goal="understand the request",
            decision_summary="request is too vague",
            clarification_question="Which store would you like me to check?",
        )
    )
    state = _state()

    update = supervisor_node(state, policy)

    assert update["workflow_status"] == "awaiting_clarification"
    assert update["final_response"] == "Which store would you like me to check?"


def test_confirmation_decision_pauses_the_workflow():
    policy = FakePolicy(
        SupervisorDecision(
            decision="confirmation", goal="cancel order", decision_summary="needs customer confirmation"
        )
    )
    state = _state()

    update = supervisor_node(state, policy)

    assert update["workflow_status"] == "awaiting_confirmation"


def test_finish_decision_completes_the_workflow():
    policy = FakePolicy(
        SupervisorDecision(decision="finish", goal="find shoes", decision_summary="found a valid option in stock")
    )
    state = _state()

    update = supervisor_node(state, policy)

    assert update["workflow_status"] == "completed"
    assert update["final_response"] == "found a valid option in stock"


def test_safe_failure_decision_fails_with_the_fixed_safe_message():
    policy = FakePolicy(
        SupervisorDecision(decision="safe_failure", goal="find shoes", decision_summary="repeated tool errors")
    )
    state = _state()

    update = supervisor_node(state, policy)

    assert update["workflow_status"] == "failed"
    assert update["final_response"] == SAFE_FAILURE_MESSAGE
    # The model's own summary must never leak into the customer-facing
    # message - only the fixed, safe sentence does.
    assert "repeated tool errors" not in update["final_response"]


# ---------------------------------------------------------------------------
# retry_count bookkeeping
# ---------------------------------------------------------------------------


def test_retry_count_increments_when_the_policy_repeats_the_same_agent():
    policy = FakePolicy(
        SupervisorDecision(decision="inventory", goal="check stock", decision_summary="retrying nearby check")
    )
    state = _state(next_agent="inventory", retry_count=1)

    update = supervisor_node(state, policy)

    assert update["retry_count"] == 2


def test_retry_count_resets_when_the_policy_moves_to_a_different_agent():
    policy = FakePolicy(
        SupervisorDecision(decision="recommendation", goal="find shoes", decision_summary="trying substitutes")
    )
    state = _state(next_agent="inventory", retry_count=2)

    update = supervisor_node(state, policy)

    assert update["retry_count"] == 0


def test_retry_count_does_not_increment_on_the_first_decision():
    policy = FakePolicy(
        SupervisorDecision(decision="recommendation", goal="find shoes", decision_summary="starting search")
    )
    state = _state(next_agent=None, retry_count=0)

    update = supervisor_node(state, policy)

    assert update["retry_count"] == 0


@pytest.mark.parametrize("decision_type", ["finish", "safe_failure"])
def test_retry_count_resets_to_zero_for_terminal_decisions_even_if_repeated(decision_type):
    policy = FakePolicy(
        SupervisorDecision(decision=decision_type, goal="find shoes", decision_summary="stopping")
    )
    state = _state(next_agent=decision_type, retry_count=1)

    update = supervisor_node(state, policy)

    assert update["retry_count"] == 0
