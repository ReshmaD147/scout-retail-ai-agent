"""Tests for LangChainSupervisorPolicy, using a hand-written fake chat
model instead of a real LangChain BaseChatModel/Ollama - it only needs
to satisfy `with_structured_output(schema).invoke(messages)`, the exact
shape LangChainSupervisorPolicy calls.
"""

from scout.orchestration.state import RetailGraphState
from scout.orchestration.supervisor_decision import SupervisorDecision
from scout.orchestration.supervisor_policy import LangChainSupervisorPolicy
from scout.orchestration.supervisor_policy import LangChainSupervisorPolicy, OllamaBackedSupervisorPolicy

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

class _RaisingChatModel:
    """A fake chat model whose structured output call always raises,
    simulating an unreachable/misbehaving Ollama server."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def with_structured_output(self, schema):
        return _RaisingStructuredRunnable(self._exc)


class _RaisingStructuredRunnable:
    def __init__(self, exc: Exception):
        self._exc = exc

    def invoke(self, messages):
        raise self._exc


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

def test_ollama_backed_policy_returns_a_reachable_decision_unchanged():
    decision = SupervisorDecision(decision="recommendation", goal="find shoes", decision_summary="searching")
    chat_model = _FakeChatModel(decision)
    policy = OllamaBackedSupervisorPolicy(chat_model)

    result = policy.decide(_state())

    assert result is decision


def test_ollama_backed_policy_falls_back_to_rule_based_on_model_error():
    chat_model = _RaisingChatModel(RuntimeError("Ollama server unreachable"))
    policy = OllamaBackedSupervisorPolicy(chat_model)

    # A vague query with no category/budget/location - RuleBasedSupervisorPolicy's
    # documented behavior for this exact input is "clarification".
    result = policy.decide(_state(customer_query="find something nice"))

    assert result.decision == "clarification"
    assert result.clarification_question


def test_ollama_backed_policy_falls_back_when_the_model_chooses_an_unreachable_decision():
    # "inventory" is a schema-valid SupervisorDecisionType, but this graph's
    # current shape (scout/orchestration/graph.py's _SUPERVISOR_ROUTES) has
    # no path from it to anywhere but END - the exact failure mode this
    # policy must catch and safely reroute around.
    decision = SupervisorDecision(
        decision="inventory", goal="check stock", decision_summary="checking inventory directly"
    )
    chat_model = _FakeChatModel(decision)
    policy = OllamaBackedSupervisorPolicy(chat_model)

    result = policy.decide(_state(customer_query="find something nice"))

    assert result.decision == "clarification"
    assert result is not decision


def test_ollama_backed_policy_passes_through_every_currently_reachable_decision():
    # Guards against a future edit accidentally shrinking or typo-ing
    # _REACHABLE_DECISIONS - every value the real graph can route
    # somewhere useful for must not be silently treated as a failure.
    reachable_examples = {
        "recommendation": SupervisorDecision(decision="recommendation", goal="g", decision_summary="s"),
        "order": SupervisorDecision(decision="order", goal="g", decision_summary="s"),
        "finish": SupervisorDecision(decision="finish", goal="g", decision_summary="s"),
        "safe_failure": SupervisorDecision(decision="safe_failure", goal="g", decision_summary="s"),
        "confirmation": SupervisorDecision(decision="confirmation", goal="g", decision_summary="s"),
        "clarification": SupervisorDecision(
            decision="clarification", goal="g", decision_summary="s", clarification_question="Which store?"
        ),
    }
    for expected_decision, decision in reachable_examples.items():
        chat_model = _FakeChatModel(decision)
        policy = OllamaBackedSupervisorPolicy(chat_model)

        result = policy.decide(_state())

        assert result is decision, f"expected {expected_decision!r} to pass through unchanged"

        