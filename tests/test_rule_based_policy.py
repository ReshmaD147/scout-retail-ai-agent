"""Tests for RuleBasedSupervisorPolicy, Step 10's default SupervisorPolicy."""

from scout.orchestration.rule_based_policy import RuleBasedSupervisorPolicy
from scout.orchestration.state import RetailGraphState


def _state(**overrides):
    defaults = {"session_id": "S1", "customer_query": "find shoes"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


def test_asks_for_clarification_when_the_request_is_completely_vague():
    policy = RuleBasedSupervisorPolicy()
    state = _state(intent={"category": None, "max_price": None, "location_text": None})

    decision = policy.decide(state)

    assert decision.decision == "clarification"
    assert decision.clarification_question is not None


def test_asks_for_clarification_when_a_location_did_not_resolve():
    policy = RuleBasedSupervisorPolicy()
    state = _state(
        intent={
            "category": "Footwear",
            "max_price": 100.0,
            "pickup_requested": True,
            "location_text": "Nowhereville",
            "selected_store_id": None,
        }
    )

    decision = policy.decide(state)

    assert decision.decision == "clarification"
    assert "Nowhereville" in decision.clarification_question


def test_produces_a_two_step_plan_without_pickup():
    policy = RuleBasedSupervisorPolicy()
    state = _state(intent={"category": "Footwear", "max_price": 100.0, "location_text": None})

    decision = policy.decide(state)

    assert decision.decision == "recommendation"
    assert [step.agent for step in decision.plan] == ["recommendation", "inventory"]
    assert "Footwear" in decision.goal


def test_adds_a_third_step_when_pickup_and_a_store_are_both_resolved():
    policy = RuleBasedSupervisorPolicy()
    state = _state(
        intent={
            "category": "Footwear",
            "max_price": 100.0,
            "pickup_requested": True,
            "location_text": "Maple Grove",
            "selected_store_id": "STR-001",
        }
    )

    decision = policy.decide(state)

    assert decision.decision == "recommendation"
    assert len(decision.plan) == 3
    assert decision.needs_multiple_agents is True


def test_treats_missing_intent_as_completely_vague():
    policy = RuleBasedSupervisorPolicy()
    state = _state(intent=None)

    decision = policy.decide(state)

    assert decision.decision == "clarification"
