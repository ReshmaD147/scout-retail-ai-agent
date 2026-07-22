"""Server-Sent Events framing helpers (Step 13).

Two independent, small responsibilities live here, kept separate from
scout/api/routes/chat_stream.py's retail-specific event *content*:

- `render_sse` turns one `StreamEvent` into the literal
  `event: ...\\nid: ...\\ndata: ...\\n\\n` text the SSE spec requires.
- `with_heartbeat` wraps any async event generator so a proxy or load
  balancer sitting in front of Scout never sees a connection go quiet
  for longer than one heartbeat interval, without ever emitting a
  heartbeat sooner than that (see its own docstring for how).

Neither function knows anything about LangGraph, RetailGraphState, or
retail business logic - both would be identical for any other
streaming endpoint Scout might add later.
"""

import asyncio
import json
from typing import AsyncIterator, Callable

from scout.api.schemas.events import StreamEvent


def render_sse(event: StreamEvent) -> str:
    """Render one StreamEvent as a literal SSE text frame.

    `model_dump(mode="json")` (not `model_dump()`) so the `timestamp`
    field serializes to an ISO-8601 string, not a raw `datetime`
    object `json.dumps` cannot handle.

    Heartbeat frames omit the `id:` line entirely - they are not part
    of the monotonically increasing event-id sequence real workflow
    events use (a heartbeat carries no new information a client would
    need to resume from), matching the example in the Step 13 prompt.
    """
    payload = json.dumps(event.model_dump(mode="json"))
    if event.event_type == "heartbeat":
        return f"event: heartbeat\ndata: {payload}\n\n"
    return f"event: {event.event_type}\nid: {event.event_id}\ndata: {payload}\n\n"


async def with_heartbeat(
    events: AsyncIterator[StreamEvent],
    heartbeat_interval_seconds: float,
    make_heartbeat: Callable[[], StreamEvent],
) -> AsyncIterator[StreamEvent]:
    """Yield everything `events` yields, plus a heartbeat whenever the
    next real event takes longer than `heartbeat_interval_seconds` to
    arrive.

    Implemented by racing one persistent "get the next real event"
    task against a timeout, using `asyncio.shield` so a slow real event
    is never cancelled, skipped, or duplicated just because a timeout
    fired first - only the *wait* times out, not the underlying work.
    Re-arming just the timeout (never replacing the pending task) on
    every heartbeat is also what keeps heartbeats from firing more
    often than the configured interval actually allows.
    """
    pending = asyncio.ensure_future(events.__anext__())
    try:
        while True:
            try:
                item = await asyncio.wait_for(asyncio.shield(pending), timeout=heartbeat_interval_seconds)
            except asyncio.TimeoutError:
                yield make_heartbeat()
                continue
            except StopAsyncIteration:
                return
            pending = asyncio.ensure_future(events.__anext__())
            yield item
    finally:
        pending.cancel()
