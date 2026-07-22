"""A deterministic SupervisorPolicy for Step 10's fixed pipeline.

scout/orchestration/supervisor_policy.py's LangChainSupervisorPolicy
needs a real chat model, and no model is wired in yet (Ollama
integration is Phase 5's job, still not built). This graph's shape -
recommendation -> inventory -> availability -> nearby -> substitute ->
reranking -> verification - is fixed by design (CLAUDE.md's primary
example workflow), so the Supervisor's one decision for this graph
does not need free-form model reasoning either: it only needs to
decide whether the extracted intent (scout/agents/understand_request.py)
is usable at all, or whether the customer needs to be asked something
first.

`RuleBasedSupervisorPolicy` implements the same `SupervisorPolicy`
protocol `LangChainSupervisorPolicy` does, so `supervisor_node`
(scout/orchestration/supervisor.py) works with either unchanged - swap
this out for a real model-backed policy later without touching the
node or the graph wiring.
"""

from scout.orchestration.state import PlanStep, RetailGraphState
from scout.orchestration.supervisor_decision import SupervisorDecision


class RuleBasedSupervisorPolicy:
    """Decide "clarification" or "recommendation" from extracted intent alone."""

    def decide(self, state: RetailGraphState) -> SupervisorDecision:
        intent = state.intent or {}
        category = intent.get("category")
        max_price = intent.get("max_price")
        location_text = intent.get("location_text")
        pickup_requested = intent.get("pickup_requested", False)
        selected_store_id = intent.get("selected_store_id")

        if category is None and max_price is None and not location_text:
            return SupervisorDecision(
                decision="clarification",
                goal="understand what the customer is looking for",
                decision_summary=(
                    "the request did not include a recognizable product category, "
                    "budget, or location"
                ),
                clarification_question=(
                    "Could you tell me what product you're looking for, your budget, "
                    "and which store or area you'd like to check?"
                ),
            )

        if pickup_requested and location_text and not selected_store_id:
            return SupervisorDecision(
                decision="clarification",
                goal="resolve the pickup location",
                decision_summary=f"could not match {location_text!r} to a known Scout store",
                clarification_question=(
                    f'I couldn\'t find a Scout store matching "{location_text}" - could you '
                    "confirm the city or store name?"
                ),
            )

        plan = [
            PlanStep(step_id="1", description="find candidate products within budget", agent="recommendation"),
            PlanStep(
                step_id="2",
                description="check pickup availability at the selected store",
                agent="inventory",
            ),
        ]
        if pickup_requested and selected_store_id:
            plan.append(
                PlanStep(
                    step_id="3",
                    description="check nearby stores and substitutes if the selected store cannot fulfill",
                    agent="inventory",
                )
            )

        return SupervisorDecision(
            decision="recommendation",
            goal=f"find {category or 'a matching product'} within budget and confirm fulfillment",
            decision_summary="request understood; starting product search",
            plan=plan,
            needs_multiple_agents=True,
        )
