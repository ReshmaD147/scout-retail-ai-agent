"""A deterministic SupervisorPolicy for Scout's bounded cyclic graph.

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
    """Choose the next bounded specialist action from current state."""

    def decide(self, state: RetailGraphState) -> SupervisorDecision:
        intent = state.intent or {}
        if intent.get("request_type") == "policy":
            if state.policy_results and state.final_response:
                return SupervisorDecision(
                    decision="verification",
                    goal="answer the public policy question from active policy evidence",
                    decision_summary="policy evidence is ready for verification",
                )
            return SupervisorDecision(
                decision="support",
                goal="answer the public policy question from active policy evidence",
                decision_summary="public policy question detected; routing to the Policy Q&A Agent",
                plan=[PlanStep(step_id="policy_retrieval", description="retrieve active policy sections", agent="support")],
                needs_multiple_agents=False,
            )

        if intent.get("request_type") == "order":
            if state.order_context is not None and intent.get("needs_policy") and not state.policy_results:
                return SupervisorDecision(
                    decision="support",
                    goal="combine private order evidence with relevant public policy",
                    decision_summary="order evidence is verified; retrieving relevant policy context",
                    plan=[PlanStep(step_id="policy_context", description="retrieve active policy context", agent="support")],
                    needs_multiple_agents=True,
                )
            if state.order_context is not None and state.proposed_claims:
                return SupervisorDecision(
                    decision="verification",
                    goal="verify private order support evidence before responding",
                    decision_summary="private order evidence is ready for verification",
                )
            if state.order_context is not None or state.final_response:
                return SupervisorDecision(
                    decision="finish",
                    goal="look up the customer order and report verified status",
                    decision_summary="order evidence has been collected",
                )
            return SupervisorDecision(
                decision="order",
                goal="look up the customer order and report verified status",
                decision_summary="order-status request detected; routing to the Order Agent",
                plan=[
                    PlanStep(
                        step_id="order_lookup",
                        description="look up order, payment, fulfillment, tracking, and eligibility facts",
                        agent="order",
                    )
                ],
                needs_multiple_agents=False,
            )

        category = intent.get("category")
        subcategory = intent.get("subcategory")
        max_price = intent.get("max_price")
        location_text = intent.get("location_text")
        pickup_requested = intent.get("pickup_requested", False)
        selected_store_id = intent.get("selected_store_id")
        deals_only = intent.get("deals_only", False)

        if category is None and subcategory is None and max_price is None and not location_text and not deals_only:
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

        if state.workflow_status in {"failed", "stopped_at_limit"}:
            return SupervisorDecision(
                decision="safe_failure",
                goal=state.goal or "complete the request safely",
                decision_summary="workflow cannot continue safely",
            )

        if pickup_requested and not location_text and not selected_store_id:
            return SupervisorDecision(
                decision="clarification",
                goal="resolve the pickup location",
                decision_summary="pickup was requested without a store or area",
                clarification_question="Which Scout store or city should I check for pickup?",
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

        if not state.product_candidates and not state.external_offers:
            if any(trace.tool_name == "find_available_substitutes" for trace in state.tool_results):
                if any(trace.tool_name == "search_external_offers" for trace in state.tool_results):
                    return SupervisorDecision(
                        decision="verification",
                        goal=state.goal or f"find {category or 'a matching product'} within budget",
                        decision_summary="external fallback evidence is ready for verification",
                    )
                return SupervisorDecision(
                    decision="support",
                    goal=state.goal or f"find {category or 'a matching product'} within budget",
                    decision_summary="internal options are insufficient; routing to external offers",
                )
            if any(trace.tool_name == "semantic_search_products" for trace in state.tool_results):
                if not any(trace.tool_name == "search_external_offers" for trace in state.tool_results):
                    return SupervisorDecision(
                        decision="support",
                        goal=state.goal or f"find {category or subcategory or 'a matching product'} within budget",
                        decision_summary="internal product search returned no matches; routing to external offers",
                    )
                return SupervisorDecision(
                    decision="verification",
                    goal=state.goal or f"find {category or 'a matching product'} within budget",
                    decision_summary="no internal products matched; verifying a no-results response",
                )
            return SupervisorDecision(
                decision="recommendation",
                goal=f"find {category or 'a matching product'} within budget and confirm fulfillment",
                decision_summary="product evidence is missing; routing to the Recommendation Agent",
                plan=[
                    PlanStep(step_id="recommendation", description="find candidate products within budget", agent="recommendation")
                ],
                needs_multiple_agents=bool(pickup_requested),
            )

        if state.product_candidates:
            has_inventory_trace = any(
                trace.tool_name in {
                    "check_store_inventory",
                    "availability_evaluation",
                    "find_nearby_inventory",
                    "check_network_inventory",
                    "find_available_substitutes",
                }
                for trace in state.tool_results
            )
            has_fulfillable_inventory = any(
                entry.get("sellable_quantity", 0) > 0 for entry in state.inventory_results
            )
            has_final_rerank = any(
                trace.tool_name == "rank_products" and trace.summary.startswith("reranked")
                for trace in state.tool_results
            )
            if not has_inventory_trace or not has_fulfillable_inventory or not has_final_rerank:
                return SupervisorDecision(
                    decision="inventory",
                    goal=f"find {category or 'a matching product'} within budget and confirm fulfillment",
                    decision_summary="fulfillment evidence is missing; routing to the Inventory Agent",
                    plan=[
                        PlanStep(step_id="inventory", description="check bounded fulfillment evidence", agent="inventory")
                    ],
                    needs_multiple_agents=True,
                )

            return SupervisorDecision(
                decision="verification",
                goal=f"find {category or 'a matching product'} within budget and confirm fulfillment",
                decision_summary="product and fulfillment evidence are ready for verification",
            )

        if not state.product_candidates and not state.external_offers:
            return SupervisorDecision(
                decision="safe_failure",
                goal=state.goal or "find a matching product",
                decision_summary="no internal or external options are available",
            )

        if state.external_offers:
            return SupervisorDecision(
                decision="verification",
                goal=state.goal or "find a safe external alternative",
                decision_summary="external offer evidence is ready for verification",
            )

        plan = [
            PlanStep(step_id="1", description="find candidate products within budget", agent="recommendation"),
            PlanStep(
                step_id="2",
                description=(
                    "check pickup availability at the selected store"
                    if pickup_requested and selected_store_id
                    else "check verified store-network availability"
                ),
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
