"""Tests for LangChainSupervisorPolicy, using a hand-written fake chat
model instead of a real LangChain BaseChatModel/Ollama - it only needs
to satisfy `with_structured_output(schema).invoke(messages)`, the exact
shape LangChainSupervisorPolicy calls.
"""

import langchain_ollama

from scout.config import get_settings
from scout.mcp.schemas import ProductSummary
from scout.orchestration.state import RetailGraphState, ToolCallTrace
from scout.orchestration.supervisor_decision import SupervisorDecision
from scout.orchestration.supervisor_policy import (
    LangChainSupervisorPolicy,
    OllamaBackedSupervisorPolicy,
    get_supervisor_policy,
)

class _FakeStructuredRunnable:
    def __init__(self, result):
        self._results = list(result) if isinstance(result, list) else [result]
        self.invoked_with = None

    def invoke(self, messages):
        self.invoked_with = messages
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _FakeChatModel:
    def __init__(self, result):
        self._result = result
        self.requested_schema = None
        self.structured_runnable = None

    def with_structured_output(self, schema):
        self.requested_schema = schema
        self.structured_runnable = _FakeStructuredRunnable(self._result)
        return self.structured_runnable


class _CapturingChatOllama(_FakeChatModel):
    created_with = None

    def __init__(self, **kwargs):
        super().__init__(SupervisorDecision(decision="finish", goal="done", decision_summary="all set"))
        type(self).created_with = kwargs


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


def _product(product_id: str = "FTW-004") -> ProductSummary:
    return ProductSummary(
        product_id=product_id,
        name="ComfortPro Shift Support",
        brand="ComfortPro",
        category="Footwear",
        subcategory="Work",
        price=89.99,
        rating=4.7,
        review_count=401,
        active=True,
    )


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
    assert policy.last_decision_source == "ollama"


def test_ollama_backed_policy_falls_back_to_rule_based_on_model_error():
    chat_model = _RaisingChatModel(RuntimeError("Ollama server unreachable"))
    policy = OllamaBackedSupervisorPolicy(chat_model)

    # A vague query with no category/budget/location - RuleBasedSupervisorPolicy's
    # documented behavior for this exact input is "clarification".
    result = policy.decide(_state(customer_query="find something nice"))

    assert result.decision == "clarification"
    assert result.clarification_question
    assert policy.last_decision_source == "rule_based_fallback"


def test_ollama_backed_policy_records_retry_source_after_first_model_error():
    decision = SupervisorDecision(decision="recommendation", goal="find shoes", decision_summary="searching")
    chat_model = _FakeChatModel([RuntimeError("first call failed"), decision])
    policy = OllamaBackedSupervisorPolicy(chat_model)

    result = policy.decide(_state())

    assert result is decision
    assert policy.last_decision_source == "retry"


def test_ollama_backed_policy_allows_inventory_decision():
    # The cyclic graph can route inventory decisions directly.
    decision = SupervisorDecision(
        decision="inventory", goal="check stock", decision_summary="checking inventory directly"
    )
    chat_model = _FakeChatModel(decision)
    policy = OllamaBackedSupervisorPolicy(chat_model)

    result = policy.decide(_state(customer_query="find something nice"))

    assert result is decision
    assert policy.last_decision_source == "ollama"


def test_ollama_backed_policy_rejects_stale_recommendation_repeat():
    decision = SupervisorDecision(
        decision="recommendation",
        goal="find shoes",
        decision_summary="search products again",
    )
    chat_model = _FakeChatModel(decision)
    policy = OllamaBackedSupervisorPolicy(chat_model)

    result = policy.decide(
        _state(
            intent={"category": "Footwear", "subcategory": "Work", "max_price": 100.0},
            product_candidates=[_product()],
            tool_results=[
                ToolCallTrace(
                    tool_name="semantic_search_products",
                    status="success",
                    summary="found 1 candidate",
                    validated_arguments={"query_text": "Work shoes under $100"},
                )
            ],
        )
    )

    assert result.decision == "inventory"
    assert policy.last_decision_source == "rule_based_fallback"


def test_ollama_backed_policy_rejects_stale_inventory_repeat():
    decision = SupervisorDecision(
        decision="inventory",
        goal="check stock again",
        decision_summary="check inventory again",
    )
    chat_model = _FakeChatModel(decision)
    policy = OllamaBackedSupervisorPolicy(chat_model)

    result = policy.decide(
        _state(
            intent={"category": "Footwear", "subcategory": "Work", "max_price": 100.0},
            product_candidates=[_product()],
            inventory_results=[{"product_id": "FTW-004", "sellable_quantity": 3}],
            tool_results=[
                ToolCallTrace(
                    tool_name="find_nearby_inventory",
                    status="success",
                    summary="FTW-004: found at Scout Demo Store - Plymouth",
                    validated_arguments={"product_id": "FTW-004", "location_text": "Maple Grove"},
                ),
                ToolCallTrace(
                    tool_name="rank_products",
                    status="success",
                    summary="reranked 1 fulfillable candidate(s), returning the top 1",
                    validated_arguments={"product_ids": ["FTW-004"], "phase": "fulfillment_rerank"},
                )
            ],
        )
    )

    assert result.decision == "verification"
    assert policy.last_decision_source == "rule_based_fallback"


def test_ollama_backed_policy_passes_through_every_currently_reachable_decision():
    # Guards against a future edit accidentally shrinking or typo-ing
    # _REACHABLE_DECISIONS - every value the real graph can route
    # somewhere useful for must not be silently treated as a failure.
    reachable_examples = {
        "recommendation": SupervisorDecision(decision="recommendation", goal="g", decision_summary="s"),
        "inventory": SupervisorDecision(decision="inventory", goal="g", decision_summary="s"),
        "order": SupervisorDecision(decision="order", goal="g", decision_summary="s"),
        "support": SupervisorDecision(decision="support", goal="g", decision_summary="s"),
        "verification": SupervisorDecision(decision="verification", goal="g", decision_summary="s"),
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


def test_ollama_policy_factory_uses_configured_low_temperature(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("SUPERVISOR_POLICY", "ollama")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "scout-test-model")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_CHAT_TEMPERATURE", "0.2")
    monkeypatch.setattr(langchain_ollama, "ChatOllama", _CapturingChatOllama)

    try:
        policy = get_supervisor_policy()
    finally:
        get_settings.cache_clear()

    assert isinstance(policy, OllamaBackedSupervisorPolicy)
    assert _CapturingChatOllama.created_with == {
        "model": "scout-test-model",
        "base_url": "http://localhost:11434",
        "temperature": 0.2,
    }


def test_supervisor_policy_factory_defaults_to_ollama(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("SUPERVISOR_POLICY", raising=False)
    monkeypatch.setattr(langchain_ollama, "ChatOllama", _CapturingChatOllama)

    try:
        policy = get_supervisor_policy()
    finally:
        get_settings.cache_clear()

    assert isinstance(policy, OllamaBackedSupervisorPolicy)
    assert _CapturingChatOllama.created_with["temperature"] == 0.1
