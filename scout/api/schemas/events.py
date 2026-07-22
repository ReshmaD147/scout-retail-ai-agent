"""Typed schemas for POST /chat/stream's Server-Sent Events (Step 13).

`StreamEvent` is the one shape every frame on the wire carries, before
`scout/api/streaming.py` renders it into the literal SSE text
(`event: <event_type>\\nid: <event_id>\\ndata: <json>\\n\\n`). Kept
separate from `scout/api/schemas/chat.py`'s `ChatRequest`/`ChatResponse`:
those describe one whole HTTP request/response; this describes one
frame of an ongoing stream. `ChatRequest` is still reused as-is for
`POST /chat/stream`'s request body - there is no `StreamChatRequest`.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "workflow_started",
    "plan_created",
    "agent_selected",
    "tool_started",
    "tool_completed",
    "workflow_replanned",
    "verification_started",
    "verification_completed",
    "clarification_required",
    "confirmation_required",
    "final_response",
    "workflow_failed",
    "stream_closed",
    "heartbeat",
]
"""Every event type Step 13 supports. Not every request emits every
type - see scout/api/routes/chat_stream.py for which ones a given
workflow outcome actually produces."""


class StreamEvent(BaseModel):
    """One customer-safe Server-Sent Event.

    `data` is deliberately a plain, small `dict` (not a nested model
    per event type) so each event carries only the safe payload it
    actually needs - never a raw tool result, a prompt, a model's
    reasoning, SQL, or an internal exception (CLAUDE.md section 12).
    `event_id` is monotonically increasing within one stream, except
    for "heartbeat" events, which are not part of that sequence (see
    scout/api/streaming.py's render_sse).
    """

    event_id: int
    event_type: EventType
    workflow_id: str
    session_id: str
    label: str
    """A short, human-readable, customer-safe phrase (e.g. "Searching
    the product catalog") - see scout/orchestration/events.py."""
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
