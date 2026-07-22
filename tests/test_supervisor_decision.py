"""Validation tests for SupervisorDecision."""

import pytest
from pydantic import ValidationError

from scout.orchestration.state import PlanStep
from scout.orchestration.supervisor_decision import SupervisorDecision


def _decision(**overrides):
    defaults = {
        "decision": "recommendation",
        "goal": "find comfortable work shoes under $100",
        "decision_summary": "starting product search",
    }
    defaults.update(overrides)
    return SupervisorDecision(**defaults)


def test_minimal_decision_applies_defaults():
    decision = _decision()

    assert decision.plan == []
    assert decision.needs_multiple_agents is False
    assert decision.clarification_question is None


def test_decision_rejects_unknown_value():
    with pytest.raises(ValidationError):
        _decision(decision="do_something_else")


def test_goal_is_required_non_empty():
    with pytest.raises(ValidationError):
        _decision(goal="")


def test_decision_summary_is_required_non_empty():
    with pytest.raises(ValidationError):
        _decision(decision_summary="")


def test_clarification_requires_a_clarification_question():
    with pytest.raises(ValidationError):
        _decision(decision="clarification", clarification_question=None)


def test_clarification_rejects_a_blank_clarification_question():
    with pytest.raises(ValidationError):
        _decision(decision="clarification", clarification_question="   ")


def test_clarification_accepts_a_real_question():
    decision = _decision(
        decision="clarification", clarification_question="Which store would you like me to check?"
    )
    assert decision.clarification_question == "Which store would you like me to check?"


def test_non_clarification_decisions_do_not_require_a_question():
    decision = _decision(decision="finish")
    assert decision.clarification_question is None


def test_plan_accepts_plan_step_instances():
    step = PlanStep(step_id="1", description="check selected store", agent="inventory")
    decision = _decision(plan=[step])
    assert decision.plan[0].step_id == "1"


def test_plan_coerces_matching_dicts():
    decision = _decision(
        plan=[{"step_id": "1", "description": "check selected store", "agent": "inventory"}]
    )
    assert isinstance(decision.plan[0], PlanStep)


def test_needs_multiple_agents_accepts_true():
    decision = _decision(needs_multiple_agents=True)
    assert decision.needs_multiple_agents is True


def test_decision_is_json_serializable():
    decision = _decision(
        decision="clarification",
        clarification_question="Which store?",
        plan=[PlanStep(step_id="1", description="ask customer", agent="inventory")],
        needs_multiple_agents=True,
    )
    payload = decision.model_dump_json()
    assert "Which store?" in payload
