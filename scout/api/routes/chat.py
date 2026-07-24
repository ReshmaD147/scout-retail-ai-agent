"""POST /chat (Step 12) - the one HTTP entry point into Scout's existing,
already-tested LangGraph workflow (Steps 1-11).

This module is deliberately thin, per CLAUDE.md section 7's API-layer
rules: it validates the request (via `ChatRequest`, see
scout/api/schemas/chat.py), builds a trusted initial `RetailGraphState`,
invokes the compiled graph (via dependency injection - see
scout/api/dependencies.py), and maps the *already-verified* final state
into `ChatResponse`. No recommendation, inventory, routing, or
verification logic lives here - all of that already exists and is
already tested in scout/agents/ and scout/orchestration/.

Request flow
--------------
    Client
      -> ChatRequest validation (Pydantic, extra="forbid")
      -> build_initial_state() - trusted dict, client controls only
         session_id/message/user_id/store_id/location
      -> compiled_graph.invoke(...) under an asyncio.wait_for timeout
      -> RetailGraphState.model_validate(...) - the verified final state
      -> build_chat_response() - maps state -> ChatResponse
      -> Client

Business outcome vs. validation error vs. service failure vs.
unexpected failure
--------------------------------------------------------------------
- A **business outcome** is any answer the workflow itself reached on
  purpose: a grounded recommendation, "I need more information"
  (clarification), "nothing matched" (no_results), or "I could not
  safely verify anything" (failed, via Step 11's own correction limit
  and SAFE_FAILURE_MESSAGE). All of these are HTTP 200 - the *request*
  was handled correctly, even when the *answer* is "no."
- A **validation error** is a malformed request - never reaches the
  graph at all. HTTP 422, handled automatically by FastAPI/Pydantic
  via `ChatRequest` (scout/api/exceptions.py's existing
  RequestValidationError handler covers this - no new code needed).
- A **service failure** is Scout's own infrastructure not answering in
  time or not being reachable - a workflow timeout, or a tool
  (database) call raising an unhandled error before the graph's own
  per-candidate error handling could catch it. HTTP 503 - the request
  was well-formed, but Scout could not currently serve it.
- An **unexpected failure** is a genuine bug - anything else the graph
  invocation raises. HTTP 500, with no internal detail ever returned.
"""

import asyncio
import logging
import re
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage

from scout.api.dependencies import get_compiled_graph
from scout.api.exceptions import ScoutAppError
from scout.api.schemas.chat import (
    ChatError,
    ChatRequest,
    ChatResponse,
    FulfillmentEvidence,
    FulfillmentOption,
    RequestedLocation,
    SuggestedAction,
    ProtectedActionConfirmationCard,
)
from scout.config import get_settings
from scout.orchestration import events as safe_events
from scout.orchestration.state import RetailGraphState
from scout.mcp.schemas import ProductSummary
from scout.repositories.recommendation_reference_repository import RecommendationReferenceRepository
from scout.repositories.product_repository import ProductRepository
from scout.repositories.promotion_repository import PromotionRepository
from scout.services import promotion_service
from scout.services.product_explanation_service import ProductExplanationEvidence, generate_explanation
from scout.services.order_service import OrderStatusView
from scout.services.memory_service import save_working_memory_from_state, update_session_from_state
from scout.services.support_logging_service import record_chat_observability

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def _compose_customer_query(request: ChatRequest) -> str:
    """Fold an optional location hint into the text the graph parses.

    This is a mechanical string composition, not an interpretation of
    intent - deciding what the customer actually wants stays entirely
    understand_request_node's job (scout/agents/understand_request.py).
    Nothing is added when the customer's own message already mentions
    a location, so this never contradicts what they typed.
    """
    query = request.message
    if request.location and "near" not in query.lower():
        query = f"{query} near {request.location}"
    return query


_FOLLOW_UP_TERMS = (
    "cheaper",
    "less expensive",
    "under",
    "under $",
    "below $",
    "less than $",
    "pickup",
    "pick up",
    "pick it up",
    "delivery",
    "similar",
    "compare",
    "black",
    "promoted",
    "promotion",
)


def _follow_up_context_label(product_id: str, fallback_name: str) -> str:
    product = ProductRepository().get_by_id(product_id)
    if product is None:
        return fallback_name

    category = product.category.lower()
    subcategory = product.subcategory.lower()
    if category == "footwear":
        product_type = "shoes"
    elif category == "bags":
        product_type = "bag"
    else:
        product_type = category
    return f"{product.name} {subcategory} {product_type}".strip()


def _compose_query_with_session_context(request: ChatRequest) -> str:
    """Add only verified last-result product context to short follow-ups.

    The context comes from Scout's backend recommendation snapshot, not
    the browser. This keeps follow-ups like "Show me cheaper options" or
    "Under $50" grounded enough for intent extraction without letting the
    client provide product facts.
    """
    query = _compose_customer_query(request)
    lowered = query.lower()
    if not any(term in lowered for term in _FOLLOW_UP_TERMS):
        return query

    snapshot = RecommendationReferenceRepository().get(request.session_id)
    if snapshot is None or not snapshot.products:
        return query

    context_parts = []
    for product_ref in snapshot.products[:3]:
        name = product_ref.get("name")
        if not name:
            continue
        context_parts.append(_follow_up_context_label(product_ref.get("product_id", ""), name))
    if not context_parts:
        return query

    context = ", ".join(context_parts)
    if "pickup" in lowered or "pick up" in lowered or "pick it up" in lowered:
        return f"Check pickup availability today for {context}. Follow-up request: {query}"
    if "delivery" in lowered:
        return f"Check delivery availability for {context}. Follow-up request: {query}"
    if "similar" in lowered:
        return f"Find products similar to {context}. Follow-up request: {query}"
    if "cheaper" in lowered or "less expensive" in lowered or re.search(r"\bunder\s*\$?\d+", lowered):
        return f"Find cheaper {context} alternatives. Follow-up request: {query}"
    return f"{query} for products similar to {context}"


def build_initial_state(request: ChatRequest, workflow_id: str) -> Dict[str, Any]:
    """Build the one, fully-trusted initial state for this workflow run.

    Every field is either copied from the already-validated `request`
    (session_id, user_id, the composed customer_query,
    requested_store_id, location) or a hardcoded backend default -
    every internal execution field (plan, evidence, retry_count,
    step_count, correction_count, workflow_status, ...) is set here,
    by the backend, to its trusted starting value. The client has no
    way to override any of them: `ChatRequest` (extra="forbid") has no
    field for "plan" or "workflow_status" in the first place.
    """
    customer_query = _compose_query_with_session_context(request)
    return {
        "workflow_id": workflow_id,
        "session_id": request.session_id,
        "user_id": request.user_id,
        "customer_query": customer_query,
        "messages": [HumanMessage(content=customer_query)],
        "requested_store_id": request.store_id,
        "location": request.location,
        "requested_filters": (
            request.filters.model_dump(exclude_none=True) if request.filters is not None else None
        ),
        "intent": None,
        "goal": None,
        "plan": [],
        "completed_steps": [],
        "pending_steps": [],
        "active_agent": None,
        "next_agent": None,
        "product_candidates": [],
        "external_offers": [],
        "inventory_results": [],
        "order_context": None,
        "policy_results": [],
        "tool_results": [],
        "evidence": [],
        "errors": [],
        "retry_count": 0,
        "step_count": 0,
        "correction_count": 0,
        "pending_confirmation": None,
        "workflow_status": "in_progress",
        "final_response": None,
    }


def _build_activity_events(state: RetailGraphState) -> List[str]:
    """A fixed vocabulary of customer-safe phrases - never raw tool
    output or a model's reasoning. "Understanding your request" always
    leads, since interpreting the request is always the first thing
    that happens; every other phrase only appears once its
    corresponding tool call actually succeeded this workflow. The
    tool_name -> label mapping and de-duplication live in
    scout/orchestration/events.py (Step 13) so /chat and /chat/stream
    describe the same activity the same way.
    """
    return ["Understanding request"] + safe_events.activity_labels_for_tool_results(state.tool_results)


def _map_workflow_status(state: RetailGraphState) -> str:
    """Translate the graph's internal workflow_status into one of
    ChatResponse's five customer-facing statuses."""
    if state.workflow_status == "awaiting_clarification":
        return "clarification_required"
    if state.workflow_status == "awaiting_confirmation":
        return "confirmation_required"
    if state.workflow_status in ("failed", "stopped_at_limit"):
        return "failed"
    if state.workflow_status == "completed":
        if (state.intent or {}).get("request_type") == "order":
            return "completed"
        return "completed" if (state.product_candidates or state.external_offers or state.order_context) else "no_results"
    # "in_progress" should never reach here - the graph always resolves
    # to a terminal or paused status. Treated as a safe failure rather
    # than ever silently claiming success on an unfinished workflow.
    return "failed"


def _build_fulfillment_options(state: RetailGraphState) -> List[FulfillmentOption]:
    """Every confirmed-fulfillable inventory_results entry, already
    re-verified by scout/agents/response_verification.py - never a
    fresh, unverified query made by the route itself."""
    options: List[FulfillmentOption] = []
    for entry in state.inventory_results:
        # Keep a checked selected store even when unavailable so the UI
        # can honestly show "requested store: out of stock" beside the
        # verified nearby/delivery fallback. Other zero-quantity rows are
        # internal dead ends and stay out of the public response.
        if entry.get("sellable_quantity", 0) <= 0 and entry.get("channel") != "selected_store":
            continue
        options.append(
            FulfillmentOption(
                product_id=entry.get("product_id"),
                channel=entry.get("channel", "unknown"),
                store_id=entry.get("store_id"),
                store_name=entry.get("store_name"),
                sellable_quantity=entry.get("sellable_quantity", 0),
                distance_miles=entry.get("distance_miles"),
                substitute_for=entry.get("substitute_for"),
                delivery_min_days=entry.get("delivery_min_days"),
                delivery_max_days=entry.get("delivery_max_days"),
            )
        )
    return options


def _build_fulfillment_evidence(state: RetailGraphState) -> List[FulfillmentEvidence]:
    evidence_rows: List[FulfillmentEvidence] = []
    checked_at = state.workflow_started_at
    for index, entry in enumerate(state.inventory_results, start=1):
        channel = entry.get("channel")
        quantity = entry.get("sellable_quantity")
        if channel not in {"selected_store", "nearby_store", "delivery"}:
            continue
        if quantity is not None:
            quantity = int(quantity)
        is_delivery = channel == "delivery"
        evidence_rows.append(
            FulfillmentEvidence(
                availability_type="network" if is_delivery else channel,
                product_id=str(entry.get("product_id")),
                store_id=entry.get("store_id"),
                store_name=entry.get("store_name"),
                quantity=quantity,
                pickup_available=(None if is_delivery else bool(quantity and quantity > 0)),
                delivery_available=(bool(quantity and quantity > 0) if is_delivery else None),
                delivery_estimate=(
                    f"{entry.get('delivery_min_days')}-{entry.get('delivery_max_days')} days"
                    if is_delivery and entry.get("delivery_min_days") is not None and entry.get("delivery_max_days") is not None
                    else None
                ),
                estimate_type=("prototype" if is_delivery else None),
                checked_at=checked_at,
                evidence_ids=[f"inventory-result-{index}"],
            )
        )
    return evidence_rows


def _build_requested_location(state: RetailGraphState) -> Optional[RequestedLocation]:
    intent = state.intent or {}
    latitude = intent.get("selected_store_latitude")
    longitude = intent.get("selected_store_longitude")
    label = intent.get("location_text") or intent.get("selected_store_name")
    if latitude is None or longitude is None or not label:
        return None
    return RequestedLocation(label=str(label), latitude=float(latitude), longitude=float(longitude))


def _build_chat_errors(state: RetailGraphState) -> List[ChatError]:
    """Every WorkflowError the workflow recorded, translated 1:1 -
    each one is already customer-safe by construction (CLAUDE.md
    section 12), so no further filtering is needed here."""
    return [ChatError(code=error.error_type.upper(), message=error.message) for error in state.errors]


def build_chat_response(state: RetailGraphState, workflow_id: str) -> ChatResponse:
    """Map a verified final RetailGraphState into the public ChatResponse."""
    verification_result = state.verification_result if isinstance(state.verification_result, dict) else {}
    approved_claims = verification_result.get("approved_claims", [])
    approved_promotion_ids = {
        (claim.get("product_id"), claim.get("promotion_id"))
        for claim in approved_claims
        if isinstance(claim, dict) and claim.get("type") == "active_promotion"
    }
    display_products = [
        _with_verified_promotion(product, approved_promotion_ids)
        for product in state.product_candidates
    ]
    display_products = [
        _with_grounded_explanation(product, state, approved_claims)
        for product in display_products
    ]
    product_ids = {product.product_id for product in state.product_candidates}
    display_by_id = {product.product_id: product.model_dump(mode="json") for product in display_products}
    product_groups = []
    missing_targets = []
    for group in state.product_groups:
        products = [
            display_by_id[product.get("product_id")]
            for product in group.get("products", [])
            if product.get("product_id") in product_ids and product.get("product_id") in display_by_id
        ]
        missing = bool(group.get("missing")) or not products
        message = group.get("message") if missing else None
        normalized = {
            "target_label": group.get("target_label"),
            "products": products,
            "missing": missing,
            "message": message,
        }
        product_groups.append(normalized)
        if missing:
            missing_targets.append({"label": group.get("target_label"), "message": message})
    final_answer = state.final_response
    if missing_targets and final_answer:
        missing_text = "; ".join(str(item["label"]) for item in missing_targets if item.get("label"))
        if missing_text:
            final_answer = f"{final_answer} I could not verify a matching product for: {missing_text}."
    return ChatResponse(
        workflow_id=workflow_id,
        session_id=state.session_id,
        status=_map_workflow_status(state),
        answer=final_answer,
        products=display_products,
        product_groups=product_groups,
        missing_product_targets=missing_targets,
        fulfillment_options=_build_fulfillment_options(state),
        fulfillment_evidence=_build_fulfillment_evidence(state),
        requested_location=_build_requested_location(state),
        external_offers=list(state.external_offers),
        order=(OrderStatusView.model_validate(state.order_context) if state.order_context else None),
        activity_events=_build_activity_events(state),
        errors=_build_chat_errors(state),
        approved_claims=approved_claims if isinstance(approved_claims, list) else [],
        request_id=workflow_id,
        assistant_message_id=f"assistant-{workflow_id}",
        message_type=_message_type_for_response(state, display_products),
        product_ids=[product.product_id for product in display_products],
        suggested_actions=_suggested_actions(state, display_products),
        quick_replies=_quick_replies(state),
        protected_action=_build_protected_action_card(state),
    )


def _build_protected_action_card(state: RetailGraphState) -> Optional[ProtectedActionConfirmationCard]:
    pending = state.pending_confirmation
    if pending is None or not pending.confirmation_id:
        return None
    return ProtectedActionConfirmationCard(
        confirmation_id=pending.confirmation_id,
        action_type=pending.action_type,
        resource_type=pending.resource_type or "order",
        resource_id=pending.target_id or "",
        proposal_summary=pending.description,
        customer_effects=list(pending.customer_effects),
        financial_effects=list(pending.financial_effects),
        eligibility_status=pending.eligibility_status or "eligible",
        eligibility_reason_code=pending.eligibility_reason_code or "eligible",
        expires_at=pending.expires_at or "",
    )


def _with_verified_promotion(product: ProductSummary, approved_promotion_ids: set[tuple[object, object]]) -> ProductSummary:
    product_repo = ProductRepository()
    promotion_repo = PromotionRepository()
    catalog_product = product_repo.get_by_id(product.product_id)
    if catalog_product is None:
        return product
    promotions = promotion_repo.list_active(product_id=product.product_id)
    for promotion in promotions:
        if (product.product_id, promotion.promotion_id) not in approved_promotion_ids:
            continue
        summary = promotion_service.build_verified_promotion_summary(catalog_product, promotions, promotion.promotion_id)
        if summary is not None:
            return product.model_copy(update={"verified_promotion": summary})
    return product


def _with_grounded_explanation(
    product: ProductSummary,
    state: RetailGraphState,
    approved_claims: list[dict[str, Any]],
) -> ProductSummary:
    evidence = _build_explanation_evidence(product, state, approved_claims)
    explanation = generate_explanation(evidence, state.customer_query)
    return product.model_copy(
        update={
            "explanation": explanation.explanation,
            "explanation_source": explanation.source,
        }
    )


def _build_explanation_evidence(
    product: ProductSummary,
    state: RetailGraphState,
    approved_claims: list[dict[str, Any]],
) -> ProductExplanationEvidence:
    max_price = (state.intent or {}).get("max_price")
    relevance_entries = [
        entry for entry in state.evidence
        if entry.source == "product_relevance_service" and entry.data.get("product_id") == product.product_id
    ]
    matched_attributes: list[str] = []
    if relevance_entries:
        matched_attributes = [
            str(item) for item in relevance_entries[-1].data.get("matched_attributes", [])
        ]
    if not matched_attributes:
        matched_attributes = [
            label for label in _attribute_labels(product.attributes or {})[:4]
        ]
    inventory = _inventory_for_product(product.product_id, state.inventory_results)
    promotion = product.verified_promotion if product.verified_promotion and product.verified_promotion.get("verified") else None
    return ProductExplanationEvidence(
        product_id=product.product_id,
        product_name=product.name,
        category=product.category,
        product_type=product.subcategory,
        regular_price=product.price,
        promotional_price=(promotion or {}).get("promotional_price"),
        budget_compliant=(product.price <= float(max_price) if max_price is not None else None),
        matched_attributes=matched_attributes,
        matched_use_case=(state.intent or {}).get("keyword") or (state.intent or {}).get("use_case"),
        inventory=inventory,
        fulfillment=inventory,
        promotion=promotion,
        rating=product.rating,
        review_count=product.review_count,
        evidence_ids=[
            str(index)
            for index, entry in enumerate(state.evidence, start=1)
            if entry.data.get("product_id") == product.product_id
        ],
    )


def _inventory_for_product(product_id: str, inventory_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in inventory_results:
        if item.get("product_id") != product_id or item.get("sellable_quantity", 0) <= 0:
            continue
        channel = item.get("channel")
        scope = "store network" if channel == "delivery" else "selected or nearby store"
        return {
            "quantity": item.get("sellable_quantity"),
            "scope": scope,
            "channel": channel,
            "store_name": item.get("store_name"),
            "delivery_min_days": item.get("delivery_min_days"),
            "delivery_max_days": item.get("delivery_max_days"),
        }
    return None


def _attribute_labels(attributes: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in ("cushioning", "slip_resistance", "width", "water_resistance", "material", "use_case"):
        value = attributes.get(key)
        if isinstance(value, str) and value.strip():
            labels.append(value.replace("-", " ").strip().lower())
    tags = attributes.get("tags")
    if isinstance(tags, list):
        labels.extend(str(item).replace("-", " ").strip().lower() for item in tags if str(item).strip())
    deduped: list[str] = []
    for label in labels:
        if label not in deduped:
            deduped.append(label)
    return deduped


def _message_type_for_response(state: RetailGraphState, products: list[ProductSummary]) -> str:
    status = _map_workflow_status(state)
    if status == "clarification_required":
        return "clarification"
    if status == "failed":
        return "safe_failure"
    if state.order_context or (state.intent or {}).get("request_type") == "order":
        return "order_status"
    if products:
        return "recommendation"
    if state.inventory_results:
        return "fulfillment"
    return "text"


def _suggested_actions(state: RetailGraphState, products: list[ProductSummary]) -> list[SuggestedAction]:
    if state.order_context:
        return [
            SuggestedAction(action_id="view-tracking", label="View tracking", query="View tracking for this order"),
            SuggestedAction(action_id="check-cancellation", label="Check cancellation eligibility", query="Check cancellation eligibility"),
            SuggestedAction(action_id="check-return", label="Check return eligibility", query="Check return eligibility"),
        ]
    if not products:
        return []
    intent = state.intent or {}
    actions = []
    if products or intent.get("max_price") is not None:
        actions.append(SuggestedAction(action_id="show-cheaper", label="Show cheaper options", query="Show me cheaper options"))
    if products:
        actions.append(SuggestedAction(action_id="find-similar", label="Find similar products", query="Find something similar"))
    if len(products) >= 2:
        actions.append(SuggestedAction(action_id="compare-products", label="Compare these products", query="Compare these products"))
    if intent.get("selected_store_name") or intent.get("location_text"):
        location = intent.get("selected_store_name") or intent.get("location_text")
        actions.append(
            SuggestedAction(
                action_id="check-pickup",
                label=f"Check {location} pickup",
                query=f"Can I pick it up today near {location}?",
            )
        )
    else:
        actions.append(
            SuggestedAction(action_id="check-pickup", label="Check pickup", query="Can I pick it up today?")
        )
    promoted_count = sum(1 for product in products if product.verified_promotion)
    if promoted_count == 0 or promoted_count < len(products):
        actions.append(SuggestedAction(action_id="show-promos", label="Show promoted options", query="Show promoted options"))
    return actions[:5]


def _quick_replies(state: RetailGraphState) -> list[SuggestedAction]:
    if _map_workflow_status(state) != "clarification_required":
        return []
    intent = state.intent or {}
    if intent.get("pickup_requested") and not intent.get("selected_store_id"):
        replies = [("maple-grove", "Maple Grove"), ("brooklyn-park", "Brooklyn Park"), ("delivery", "Delivery instead")]
        return [SuggestedAction(action_id=action_id, label=label, query=label) for action_id, label in replies]
    question = (state.final_response or "").lower()
    if "budget" in question:
        replies = [("under-50", "Under $50"), ("under-100", "Under $100"), ("no-budget", "No preference")]
    else:
        replies = [("more-specific", "Show popular options"), ("pickup", "Pickup today"), ("delivery", "Delivery")]
    return [SuggestedAction(action_id=action_id, label=label, query=label) for action_id, label in replies]


def save_recommendation_snapshot(response: ChatResponse) -> None:
    """Persist the verified product list this response just returned,
    so a later Step 15 cart command ("add the first product") can
    resolve an ordinal reference against it - see the long comment
    above session_recommendation_snapshots in scout/database/schema.sql
    for what this narrow cache is and is not for.

    Deliberately best-effort: called after `response` is already fully
    built, so a failure here must never turn a good chat answer into a
    failed request. Only `sqlite3.Error` is caught (a specific,
    expected failure mode - the database being briefly unavailable),
    per CLAUDE.md's "do not silently catch broad exceptions" - anything
    else is a real bug and is allowed to propagate.
    """
    if not response.products:
        return
    try:
        RecommendationReferenceRepository().save(
            session_id=response.session_id,
            workflow_id=response.workflow_id,
            products=[{"product_id": p.product_id, "name": p.name} for p in response.products],
        )
    except sqlite3.Error:
        logger.warning(
            "recommendation_snapshot_save_failed",
            extra={"workflow_id": response.workflow_id, "session_id": response.session_id},
        )


async def _invoke_graph(compiled_graph: Any, initial_state: Dict[str, Any], workflow_id: str) -> RetailGraphState:
    """Run the compiled graph off the event loop, under a hard timeout.

    `compiled_graph.invoke(...)` is a blocking call (LangGraph's own
    API), so it runs in a worker thread via `asyncio.to_thread` -
    otherwise it would block the whole FastAPI event loop, not just
    this one request. `asyncio.wait_for` enforces
    `SCOUT_WORKFLOW_TIMEOUT_SECONDS` (scout/config.py) around it - a
    ceiling on wall-clock time distinct from (and in addition to) the
    graph's own step/retry/correction-count limits, which bound how
    much *work* happens, not how long a customer waits for a response.

    Every failure path here is caught and turned into a safe,
    structured `ScoutAppError` - a raw exception, a stack trace, SQL,
    or a file path is never allowed to reach the client (CLAUDE.md
    section 12).
    """
    settings = get_settings()
    try:
        raw_result = await asyncio.wait_for(
            asyncio.to_thread(
                compiled_graph.invoke,
                initial_state,
                config={"recursion_limit": settings.max_workflow_steps + 20},
            ),
            timeout=settings.scout_workflow_timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        logger.error("workflow_timeout", extra={"workflow_id": workflow_id})
        raise ScoutAppError(
            "Scout could not complete the request in time. Please try again.",
            status_code=503,
            code="WORKFLOW_TIMEOUT",
        ) from exc
    except sqlite3.Error as exc:
        # A tool call failed before the graph's own per-candidate error
        # handling (scout/agents/inventory_agent.py and friends) could
        # catch it - e.g. the database is genuinely unreachable. This
        # is "a required tool is unavailable," not an application bug.
        logger.error("workflow_tool_unavailable", extra={"workflow_id": workflow_id})
        raise ScoutAppError(
            "A required data source is temporarily unavailable. Please try again shortly.",
            status_code=503,
            code="TOOL_UNAVAILABLE",
        ) from exc
    except Exception as exc:
        logger.error("workflow_unexpected_error", exc_info=exc, extra={"workflow_id": workflow_id})
        raise ScoutAppError(
            "Scout could not process this request. Please try again.",
            status_code=500,
            code="INTERNAL_ERROR",
        ) from exc

    return RetailGraphState.model_validate(raw_result)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, compiled_graph: Any = Depends(get_compiled_graph)) -> ChatResponse:
    """Handle one customer message end to end.

    Kept intentionally thin: build state, invoke the graph, map the
    result. See the module docstring for the full request flow and the
    business-outcome/validation/service/unexpected-failure distinction.
    """
    workflow_id = str(uuid.uuid4())
    start_time = time.perf_counter()

    logger.info(
        "workflow_started",
        extra={"workflow_id": workflow_id, "session_id": request.session_id},
    )

    initial_state = build_initial_state(request, workflow_id)
    final_state = await _invoke_graph(compiled_graph, initial_state, workflow_id)
    response = build_chat_response(final_state, workflow_id)
    save_recommendation_snapshot(response)
    try:
        save_working_memory_from_state(final_state)
        update_session_from_state(final_state)
    except sqlite3.Error:
        logger.warning("memory_record_failed", extra={"workflow_id": workflow_id, "session_id": request.session_id})
    try:
        record_chat_observability(request=request, response=response, final_state=final_state)
    except sqlite3.Error:
        logger.warning("support_observability_record_failed", extra={"workflow_id": workflow_id, "session_id": request.session_id})

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    logger.info(
        "workflow_completed",
        extra={"workflow_id": workflow_id, "status": response.status, "duration_ms": duration_ms},
    )

    return response
