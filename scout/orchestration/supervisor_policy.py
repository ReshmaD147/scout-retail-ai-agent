"""The Supervisor's pluggable decision-maker.

`SupervisorPolicy` is the interface scout/orchestration/supervisor.py
depends on - anything with a `decide(state) -> SupervisorDecision`
method. This keeps the node itself free of any concrete model
provider.

`LangChainSupervisorPolicy` is the real implementation: it takes any
LangChain-compatible chat model that supports `with_structured_output`
(any `BaseChatModel` - Ollama, once Phase 5's Ollama integration
exists, would be passed in here as `ChatOllama(...)`; nothing in this
file is Ollama-specific) and uses it to turn the current state into a
validated `SupervisorDecision`, via the prompt and schema this module
does not itself define (see supervisor_prompt.py and
supervisor_decision.py).

Tests use a small hand-written fake implementing the same
`with_structured_output(...).invoke(...)` shape a real `BaseChatModel`
exposes, so the Supervisor's prompt/schema wiring is fully tested
without requiring a running model server.
"""

from typing import Any, Protocol

from scout.orchestration.state import RetailGraphState
from scout.orchestration.supervisor_decision import SupervisorDecision
from scout.orchestration.supervisor_prompt import build_supervisor_prompt, format_state_summary


class SupervisorPolicy(Protocol):
    """Anything that can turn the current state into a SupervisorDecision."""

    def decide(self, state: RetailGraphState) -> SupervisorDecision: ...


class StructuredChatModel(Protocol):
    """The minimal shape of a LangChain chat model this policy needs.

    Matches `langchain_core.language_models.BaseChatModel` - any real
    chat model (including a future `ChatOllama`) already satisfies
    this; it is spelled out narrowly here so tests can provide a fake
    without needing a real model instance.
    """

    def with_structured_output(self, schema: Any) -> Any: ...


class LangChainSupervisorPolicy:
    """A SupervisorPolicy backed by any structured-output-capable chat model."""

    def __init__(self, chat_model: StructuredChatModel):
        self._structured_model = chat_model.with_structured_output(SupervisorDecision)

    def decide(self, state: RetailGraphState) -> SupervisorDecision:
        prompt = build_supervisor_prompt(state)
        messages = prompt.format_messages(state_summary=format_state_summary(state))
        result = self._structured_model.invoke(messages)

        if isinstance(result, SupervisorDecision):
            return result
        # Some structured-output backends return a dict instead of the
        # model instance directly - coerce rather than trust blindly.
        return SupervisorDecision.model_validate(result)
