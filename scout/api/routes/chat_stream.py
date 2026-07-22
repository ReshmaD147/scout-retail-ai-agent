"""POST /chat/stream (Step 13) - live, customer-safe workflow activity
over Server-Sent Events, for the exact same workflow POST /chat
(Step 12) already runs.

This module deliberately reuses, rather than duplicates, Step 12's
work: `build_initial_state` and `build_chat_response`
(scout/api/routes/chat.py) are imported directly, so the initial state
this endpoint builds and the final response it emits are exactly the
ones /chat itself would build and return - only *how the workflow's
progress reaches the client* differs.

Request flow
--------------
    Client
      -> ChatRequest validation (identical to /chat - no new schema)
      -> workflow_started (emitted immediately, before the graph runs)
      -> build_initial_state() - the same trusted dict /chat builds
      -> compiled_graph.astream(..., stream_mode="updates") - one
         event (or a small handful) is derived from each node's
         partial state update as it arrives, never buffered until the
         end
      -> a final "business outcome" event when relevant
         (clarification_required / confirmation_required /
         workflow_failed), matching /chat's own status classification
      -> final_response - built by the *same* build_chat_response()
         /chat uses, so the two endpoints can never disagree about
         what a given final state means
      -> stream_closed
      -> connection closes

Internal workflow events vs. customer-safe events vs. the final API
response
--------------------------------------------------------------------
- An **internal workflow event** is whatever a LangGraph node's
  partial state update actually contains - `state.tool_results`
  entries, `state.plan`, `state.next_agent`, and so on. This can name
  real tool names and internal agent names, but never a prompt or a
  model's reasoning (CLAUDE.md section 9 already required this of
  `ToolCallTrace`/`EvidenceEntry`, not something new for streaming).
- A **customer-safe event** (`StreamEvent`, scout/api/schemas/events.py)
  is what this module derives from an internal event via
  scout/orchestration/events.py's fixed label vocabulary - a short,
  human-readable phrase, never the internal identifier itself beyond a
  known-safe tool/agent name already used elsewhere (e.g.
  `data={"tool_name": "find_nearby_inventory"}`, never a raw SQL
  string or the tool's full arguments).
- The **final API response** (the `final_response` event's `data`) is
  the same `ChatResponse` shape /chat returns as its whole HTTP body -
  a verified, customer-safe answer, never a raw workflow dump.

Why chain-of-thought must not be streamed
------------------------------------------
Nothing in `RetailGraphState` holds chain-of-thought to begin with
(CLAUDE.md section 9: "do not store hidden chain-of-thought" - enforced
at the state layer, Step 8) - there is no reasoning text this module
could accidentally forward even if it tried. Streaming only widens
*when* a customer sees safe activity, never *what kind* of information
they can see; the same fixed, reviewed label vocabulary
(scout/orchestration/events.py) that already governs /chat's
`activity_events` governs every event here too.

How client disconnect handling works
--------------------------------------
`_generate_events` is a plain async generator. When a client
disconnects, Starlette's `StreamingResponse` stops iterating it and
calls `.aclose()` on it, which raises `GeneratorExit` at whatever
`await`/`yield` point the generator is currently suspended - caught
here (logged, and used to close the underlying LangGraph `astream`
generator too) without ever needing a separate background task to
"cancel": there is no separate task to begin with, since LangGraph's
`astream` is itself a native async generator this function drives
directly, one step at a time.
"""

import asyncio
import logging
import sqlite3
import time
import uuid
from itertools import count
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from scout.api.dependencies import get_compiled_graph
from scout.api.routes.chat import build_chat_response, build_initial_state, save_recommendation_snapshot
from scout.api.schemas.chat import ChatRequest
from scout.api.schemas.events import StreamEvent
from scout.api.streaming import render_sse, with_heartbeat
from scout.config import get_settings
from scout.orchestration import events as safe_events
from scout.orchestration.limits import SAFE_FAILURE_MESSAGE
from scout.orchestration.state import RetailGraphState

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_REDUCER_FIELDS = {"tool_results", "evidence", "errors", "completed_steps", "messages"}
"""Fields RetailGraphState declares with an append-only reducer
(scout/orchestration/state.py's module docstring) - merged by
concatenation below, exactly like LangGraph's own `operator.add`/
`add_messages` reducers merge them. Every other field is a plain
"replace," matching that same docstring."""


def _merge_delta(running_state: Dict[str, Any], delta: Dict[str, Any]) -> None:
    """Apply one node's partial update to our own running copy of the
    workflow state, using the same reducer semantics LangGraph itself
    applies (see `_REDUCER_FIELDS`).

    This is bookkeeping for streaming only - it never substitutes for
    LangGraph's own, authoritative merge (that still happens inside
    `compiled_graph.astream`); it only lets this generator read fields
    like `intent` and `workflow_status` *as they stand so far*, so it
    can build accurate event labels (e.g. naming the resolved location)
    while the workflow is still running, and so the final chunk can be
    re-validated into a real `RetailGraphState` once the graph is done.
    """
    for key, value in delta.items():
        if key in _REDUCER_FIELDS:
            running_state[key] = list(running_state.get(key) or []) + list(value)
        else:
            running_state[key] = value


def _failure_code_and_message(final_state: RetailGraphState) -> Tuple[str, str]:
    """A safe {code, message} pair for a workflow that finished, but
    without a verified answer (`stopped_at_limit` or `failed`) - the
    same fixed, customer-safe text those statuses already carry via
    `final_response` (scout/orchestration/limits.py,
    scout/agents/response_verification.py), never a raw exception."""
    message = final_state.final_response or SAFE_FAILURE_MESSAGE
    if final_state.workflow_status == "stopped_at_limit":
        return "WORKFLOW_LIMIT_REACHED", message
    return "VERIFICATION_FAILED", message


def _events_for_delta(
    node_name: str,
    delta: Dict[str, Any],
    running_state: Dict[str, Any],
    workflow_id: str,
    session_id: str,
    counter: "count[int]",
) -> List[StreamEvent]:
    """Turn one node's partial state update into zero or more safe
    `StreamEvent` objects. Only ever reads `delta` (this node's own,
    already-safe return value) and `running_state` (built solely by
    `_merge_delta` from earlier deltas) - never anything else about how
    the node arrived at its answer.
    """

    def make(event_type: str, label: str, data: Optional[Dict[str, Any]] = None) -> StreamEvent:
        return StreamEvent(
            event_id=next(counter),
            event_type=event_type,
            workflow_id=workflow_id,
            session_id=session_id,
            label=label,
            data=data or {},
        )

    produced: List[StreamEvent] = []

    if node_name == "supervisor":
        plan = delta.get("plan")
        if plan:
            produced.append(make("plan_created", "Creating a shopping plan", {"step_count": len(plan)}))
        next_agent = delta.get("next_agent")
        label = safe_events.NEXT_AGENT_LABELS.get(next_agent) if next_agent else None
        if label:
            produced.append(make("agent_selected", label, {"agent": next_agent}))
        return produced

    intent = running_state.get("intent") or {}
    location_text = intent.get("location_text")

    for trace in delta.get("tool_results") or []:
        if trace.tool_name == "check_store_inventory":
            label = safe_events.label_for_store_inventory_check(location_text)
        else:
            label = safe_events.label_for_tool(trace.tool_name, node_name=node_name)
        if not label:
            continue

        if node_name == "response_verification":
            produced.append(make("verification_started", label, {"tool_name": trace.tool_name}))
            produced.append(
                make("verification_completed", label, {"tool_name": trace.tool_name, "status": trace.status})
            )
        else:
            produced.append(make("tool_started", label, {"tool_name": trace.tool_name}))
            produced.append(
                make("tool_completed", label, {"tool_name": trace.tool_name, "status": trace.status})
            )

    if node_name == "response_verification" and delta.get("workflow_status") == "in_progress":
        produced.append(
            make(
                "workflow_replanned",
                "Trying another option",
                {"correction_count": delta.get("correction_count")},
            )
        )

    return produced


async def _generate_events(
    request: ChatRequest, compiled_graph: Any, workflow_id: str
) -> AsyncIterator[StreamEvent]:
    """The core Step 13 event source - no SSE framing, no heartbeat,
    just one `StreamEvent` per safe thing that happened, in order.
    `scout/api/routes/chat_stream.py`'s route function wraps this with
    `with_heartbeat` and `render_sse` (scout/api/streaming.py) to
    produce the actual HTTP response body.
    """
    session_id = request.session_id
    counter = count(1)
    settings = get_settings()

    def make_event(event_type: str, label: str, data: Optional[Dict[str, Any]] = None) -> StreamEvent:
        return StreamEvent(
            event_id=next(counter),
            event_type=event_type,
            workflow_id=workflow_id,
            session_id=session_id,
            label=label,
            data=data or {},
        )

    yield make_event("workflow_started", "Understanding your request", {"workflow_id": workflow_id})

    initial_state = build_initial_state(request, workflow_id)
    running_state: Dict[str, Any] = dict(initial_state)

    agen = compiled_graph.astream(
        initial_state, config={"recursion_limit": settings.max_workflow_steps + 20}, stream_mode="updates"
    )
    deadline = time.monotonic() + settings.scout_workflow_timeout_seconds

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError

            try:
                chunk = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                break

            for node_name, delta in chunk.items():
                _merge_delta(running_state, delta)
                for event in _events_for_delta(
                    node_name, delta, running_state, workflow_id, session_id, counter
                ):
                    yield event
    except asyncio.TimeoutError:
        logger.error("stream_workflow_timeout", extra={"workflow_id": workflow_id})
        yield make_event(
            "workflow_failed",
            "Scout could not finish in time",
            {"code": "WORKFLOW_TIMEOUT", "message": "Scout could not complete the request in time. Please try again."},
        )
        yield make_event("stream_closed", "Stream closed", {"status": "closed"})
        return
    except sqlite3.Error:
        logger.error("stream_tool_unavailable", extra={"workflow_id": workflow_id})
        yield make_event(
            "workflow_failed",
            "A required data source is unavailable",
            {
                "code": "TOOL_UNAVAILABLE",
                "message": "A required data source is temporarily unavailable. Please try again shortly.",
            },
        )
        yield make_event("stream_closed", "Stream closed", {"status": "closed"})
        return
    except GeneratorExit:
        logger.info("stream_client_disconnected", extra={"workflow_id": workflow_id})
        raise
    except Exception:
        logger.error("stream_unexpected_error", exc_info=True, extra={"workflow_id": workflow_id})
        yield make_event(
            "workflow_failed",
            "Scout could not process this request",
            {"code": "INTERNAL_ERROR", "message": "Scout could not process this request. Please try again."},
        )
        yield make_event("stream_closed", "Stream closed", {"status": "closed"})
        return
    finally:
        await agen.aclose()

    final_state = RetailGraphState.model_validate(running_state)
    response = build_chat_response(final_state, workflow_id)
    save_recommendation_snapshot(response)

    if response.status == "clarification_required":
        yield make_event(
            "clarification_required", "Scout needs more information", {"question": response.answer}
        )
    elif response.status == "confirmation_required":
        description = (
            final_state.pending_confirmation.description if final_state.pending_confirmation else response.answer
        )
        yield make_event("confirmation_required", "Please confirm this action", {"description": description})
    elif response.status == "failed":
        code, message = _failure_code_and_message(final_state)
        yield make_event("workflow_failed", "Scout could not verify a safe answer", {"code": code, "message": message})

    yield make_event("final_response", "Here is what Scout found", response.model_dump(mode="json"))
    yield make_event("stream_closed", "Stream closed", {"status": "closed"})


def _make_heartbeat(workflow_id: str, session_id: str) -> StreamEvent:
    return StreamEvent(
        event_id=0,
        event_type="heartbeat",
        workflow_id=workflow_id,
        session_id=session_id,
        label="Still working on it",
        data={"status": "processing"},
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, compiled_graph: Any = Depends(get_compiled_graph)) -> StreamingResponse:
    """Handle one customer message end to end, streaming safe activity
    as it happens. Kept as thin as /chat itself: build state, drive the
    graph, map events - see the module docstring for the full flow.
    """
    workflow_id = str(uuid.uuid4())
    settings = get_settings()
    start_time = time.perf_counter()
    event_count = 0

    logger.info("stream_started", extra={"workflow_id": workflow_id, "session_id": request.session_id})

    events = with_heartbeat(
        _generate_events(request, compiled_graph, workflow_id),
        heartbeat_interval_seconds=settings.scout_stream_heartbeat_seconds,
        make_heartbeat=lambda: _make_heartbeat(workflow_id, request.session_id),
    )

    async def render() -> AsyncIterator[str]:
        nonlocal event_count
        try:
            async for event in events:
                event_count += 1
                yield render_sse(event)
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(
                "stream_completed",
                extra={"workflow_id": workflow_id, "event_count": event_count, "duration_ms": duration_ms},
            )

    return StreamingResponse(
        render(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
