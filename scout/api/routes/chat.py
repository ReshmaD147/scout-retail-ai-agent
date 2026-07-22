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
import sqlite3
import time
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage

from scout.api.dependencies import get_compiled_graph
from scout.api.exceptions import ScoutAppError
from scout.api.schemas.chat import ChatError, ChatRequest, ChatResponse, FulfillmentOption
from scout.config import get_settings
from scout.orchestration import events as safe_events
from scout.orchestration.state import RetailGraphState
from scout.repositories.recommendation_reference_repository import RecommendationReferenceRepository

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
    customer_query = _compose_customer_query(request)
    return {
        "workflow_id": workflow_id,
        "session_id": request.session_id,
        "user_id": request.user_id,
        "customer_query": customer_query,
        "messages": [HumanMessage(content=customer_query)],
        "requested_store_id": request.store_id,
        "location": request.location,
        "intent": None,
        "goal": None,
        "plan": [],
        "completed_steps": [],
        "pending_steps": [],
        "active_agent": None,
        "next_agent": None,
        "product_candidates": [],
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
    return ["Understanding your request"] + safe_events.activity_labels_for_tool_results(state.tool_results)


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
        return "completed" if state.product_candidates else "no_results"
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
        if entry.get("sellable_quantity", 0) <= 0:
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
            )
        )
    return options


def _build_chat_errors(state: RetailGraphState) -> List[ChatError]:
    """Every WorkflowError the workflow recorded, translated 1:1 -
    each one is already customer-safe by construction (CLAUDE.md
    section 12), so no further filtering is needed here."""
    return [ChatError(code=error.error_type.upper(), message=error.message) for error in state.errors]


def build_chat_response(state: RetailGraphState, workflow_id: str) -> ChatResponse:
    """Map a verified final RetailGraphState into the public ChatResponse."""
    return ChatResponse(
        workflow_id=workflow_id,
        session_id=state.session_id,
        status=_map_workflow_status(state),
        answer=state.final_response,
        products=list(state.product_candidates),
        fulfillment_options=_build_fulfillment_options(state),
        activity_events=_build_activity_events(state),
        errors=_build_chat_errors(state),
    )


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

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    logger.info(
        "workflow_completed",
        extra={"workflow_id": workflow_id, "status": response.status, "duration_ms": duration_ms},
    )

    return response
