"""Tests for LangChainSupervisorPolicy, using a hand-written fake chat
model instead of a real LangChain BaseChatModel/Ollama - it only needs
to satisfy `with_structured_output(schema).invoke(messages)`, the exact
shape LangChainSupervisorPolicy calls.
"""

from scout.orchestration.state import RetailGraphState
from scout.orchestration.supervisor_decision import SupervisorDecision
from scout.orchestration.supervisor_policy import LangChainSupervisorPolicy


class _FakeStructuredRunnable:
    def __init__(self, result):
        self._result = result
        self.invoked_with = None

    def invoke(self, messages):
        self.invoked_with = messages
        return self._result


class _FakeChatModel:
    def __init__(self, result):
        self._result = result
        self.requested_schema = None
        self.structured_runnable = None

    def with_structured_output(self, schema):
        self.requested_schema = schema
        self.structured_runnable = _FakeStructuredRunnable(self._result)
        return self.structured_runnable


def _state(**overrides):
    defaults = {"session_id": "S1", "customer_query": "find comfortable work shoes under $100"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


def test_policy_requests_structured_output_for_the_supervisor_decision_schema():
    decision = SupervisorDecision(decision="finish", goal="done", decision_summary="all set")
    chat_model = _FakeChatModel(decision)

    LangChainSupervisorPolicy(chat_model)

    assert chat_model.requested_schema is SupervisorDecision


def test_decide_returns_the_model_instance_the_chat_model_produces():
    decision = SupervisorDecision(decision="recommendation", goal="find shoes", decision_summary="searching")
    chat_model = _FakeChatModel(decision)
    policy = LangChainSupervisorPolicy(chat_model)

    result = policy.decide(_state())

    assert result is decision


def test_decide_coerces_a_dict_result_into_a_supervisor_decision():
    raw = {"decision": "safe_failure", "goal": "find shoes", "decision_summary": "giving up safely"}
    chat_model = _FakeChatModel(raw)
    policy = LangChainSupervisorPolicy(chat_model)

    result = policy.decide(_state())

    assert isinstance(result, SupervisorDecision)
    assert result.decision == "safe_failure"


def test_decide_invokes_with_a_system_and_human_message():
    decision = SupervisorDecision(decision="finish", goal="done", decision_summary="all set")
    chat_model = _FakeChatModel(decision)
    policy = LangChainSupervisorPolicy(chat_model)

    policy.decide(_state(customer_query="find comfortable work shoes under $100"))

    messages = chat_model.structured_runnable.invoked_with
    assert len(messages) == 2
    assert "find comfortable work shoes under $100" in messages[1].content
