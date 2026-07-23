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

import logging
from typing import Any, Protocol

from scout.config import get_settings
from scout.orchestration.rule_based_policy import RuleBasedSupervisorPolicy
from scout.orchestration.state import RetailGraphState
from scout.orchestration.supervisor_decision import SupervisorDecision
from scout.orchestration.supervisor_prompt import build_supervisor_prompt, format_state_summary

logger = logging.getLogger(__name__)

_REACHABLE_DECISIONS = frozenset(
    {"recommendation", "order", "clarification", "confirmation", "finish", "safe_failure"}
)
"""Decisions that actually lead somewhere in this graph's current shape
(scout/orchestration/graph.py's _SUPERVISOR_ROUTES / routing.py's
_DECISION_TO_NODE) - "inventory", "support", and "verification" are
valid per the SupervisorDecision schema (they exist for a future,
multi-turn Supervisor graph) but currently dead-end at END in this
single-turn-Supervisor pipeline. A decision outside this set is treated
as a policy failure, not trusted, so an LLM choosing a currently-inert
option can never silently strand a workflow the way it did before this
check existed."""


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

class OllamaBackedSupervisorPolicy:
    """A SupervisorPolicy that asks a real local Ollama chat model for
    each routing decision, falling back to RuleBasedSupervisorPolicy if
    the model call fails for any reason (server unreachable, malformed
    output, timeout). Mirrors this codebase's existing "never crash the
    workflow over one bad call" philosophy (scout/agents/inventory_agent.py's
    per-candidate tool-call wrapping) applied here to the Supervisor's
    own decision instead of an inventory tool call.
    """

    def __init__(self, chat_model: StructuredChatModel):
        self._llm_policy = LangChainSupervisorPolicy(chat_model)
        self._fallback_policy = RuleBasedSupervisorPolicy()

    def decide(self, state: RetailGraphState) -> SupervisorDecision:
        try:
            decision = self._llm_policy.decide(state)
        except Exception as exc:  # noqa: BLE001 - any model/provider failure degrades safely
            logger.warning(
                "Ollama-backed Supervisor decision failed (%s); falling back to rule-based routing.",
                exc,
            )
            return self._fallback_policy.decide(state)

        if decision.decision not in _REACHABLE_DECISIONS:
            logger.warning(
                "Ollama-backed Supervisor chose %r, which this graph cannot currently route "
                "anywhere useful; falling back to rule-based routing instead.",
                decision.decision,
            )
            return self._fallback_policy.decide(state)

        return decision
    
def get_supervisor_policy() -> SupervisorPolicy:
    """Build the SupervisorPolicy selected by centralized configuration.

    Mirrors scout.services.embedding_service.get_embedding_provider()'s
    existing hashing/ollama pattern: "rule_based" (settings default)
    requires no model and is what every current test and demo path
    depends on; "ollama" wires a real local chat model in behind the
    same SupervisorPolicy interface, with an automatic, safe fallback
    to rule-based routing if that model is ever unreachable, rather
    than failing the whole workflow.
    """
    settings = get_settings()
    if settings.supervisor_policy == "ollama":
        from langchain_ollama import ChatOllama

        chat_model = ChatOllama(model=settings.ollama_chat_model, base_url=settings.ollama_base_url)
        return OllamaBackedSupervisorPolicy(chat_model)
    return RuleBasedSupervisorPolicy()