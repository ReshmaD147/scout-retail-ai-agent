"""Tests for POST /chat/stream (Step 13).

Mirrors tests/test_chat_api.py's split: focused, isolated tests replace
the compiled-graph dependency with `_StubStreamGraph` (a minimal stand-in
exposing only the async `.astream(...)` interface this route actually
calls) to exercise transport-, timeout-, and error-mapping behavior
without a real database; integration tests call the real, compiled
graph against a real seeded temporary database to confirm the whole
event sequence a real workflow produces.

Scenario -> test name, matching the 21 scenarios the Step 13 prompt
lists explicitly:
    1.  test_valid_streaming_request_returns_200
    2.  test_content_type_is_event_stream
    3.  test_first_event_is_workflow_started
    4.  test_event_ids_increase_in_order
    5.  test_events_contain_workflow_id_and_session_id
    6.  test_product_search_emits_a_safe_catalog_search_event
    7.  test_pickup_request_emits_an_inventory_check_event
    8.  test_nearby_fallback_emits_a_nearby_store_event
    9.  test_verification_emits_verification_events
    10. test_final_response_event_contains_verified_output
    11. test_stream_ends_with_stream_closed
    12. test_vague_request_emits_clarification_required
    13. test_no_match_request_ends_safely_with_no_results
    14. test_tool_failure_emits_workflow_failed
    15. test_workflow_timeout_emits_a_safe_failure
    16. test_raw_exception_text_is_not_exposed
    17. test_prompts_and_chain_of_thought_are_not_exposed
    18. test_client_disconnect_is_handled_safely
    19. test_existing_chat_endpoint_still_passes
    20. test_existing_health_endpoint_still_passes
    21. "all Steps 1-12 tests still pass" is confirmed by running the
        *whole* suite (`pytest`) after adding this file, exactly like
        tests/test_chat_api.py's own item 20 - nothing here modifies
        any existing test or source file's behavior.
"""

import asyncio
import json
import sqlite3
from typing import Any, Dict, List

import pytest

from scout.api.dependencies import get_compiled_graph
from scout.config import get_settings

ACCEPTANCE_QUERY = "Find comfortable work shoes under $100 that I can pick up today near Maple Grove."


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    """Every test in this file runs against a real, freshly seeded
    temporary database - never the development database - even the
    tests whose graph is stubbed out and never touches it."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _parse_sse_events(text: str) -> List[Dict[str, Any]]:
    """Parse raw SSE text into a list of {"event", "id", "data"} dicts.

    `id` is None for frames (only "heartbeat") that omit the id line -
    see scout/api/streaming.py's render_sse.
    """
    events: List[Dict[str, Any]] = []
    for block in text.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        event_type = None
        event_id = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("id:"):
                event_id = int(line[len("id:") :].strip())
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        events.append({"event": event_type, "id": event_id, "data": data})
    return events


def _stream_and_collect(client, payload):
    """POST /chat/stream, fully drain the response, and parse it."""
    with client.stream("POST", "/chat/stream", json=payload) as response:
        status_code = response.status_code
        headers = dict(response.headers)
        text = response.read().decode()
    return status_code, headers, _parse_sse_events(text)


class _StubStreamGraph:
    """A minimal stand-in for the compiled LangGraph app, exposing only
    the async `.astream(...)` interface scout/api/routes/chat_stream.py
    calls - no real node, tool, or database call runs.
    """

    def __init__(self, chunks=None, raise_error: Exception = None, delay: float = 0.0):
        self._chunks = chunks or []
        self._raise_error = raise_error
        self._delay = delay
        self.closed = False

    async def astream(self, state, config=None, stream_mode=None):
        try:
            for chunk in self._chunks:
                if self._delay:
                    await asyncio.sleep(self._delay)
                yield chunk
            if self._raise_error is not None:
                raise self._raise_error
        finally:
            self.closed = True


@pytest.fixture()
def override_graph(client):
    """Replace the `get_compiled_graph` dependency for one test, then
    restore it - the same seam tests/test_chat_api.py already uses.
    """
    applied = {}

    def _apply(stub: _StubStreamGraph) -> None:
        applied["stub"] = stub
        client.app.dependency_overrides[get_compiled_graph] = lambda: stub

    yield _apply
    client.app.dependency_overrides.pop(get_compiled_graph, None)


def _find(events, event_type):
    return next((event for event in events if event["event"] == event_type), None)


def _find_all(events, event_type):
    return [event for event in events if event["event"] == event_type]


# ---------------------------------------------------------------------------
# 1-11: a completed workflow, against the real graph and a real database
# ---------------------------------------------------------------------------


def test_valid_streaming_request_returns_200(client):
    status_code, _, _ = _stream_and_collect(
        client, {"session_id": "s-stream-200", "message": ACCEPTANCE_QUERY}
    )
    assert status_code == 200


def test_content_type_is_event_stream(client):
    _, headers, _ = _stream_and_collect(client, {"session_id": "s-ct", "message": ACCEPTANCE_QUERY})
    assert headers["content-type"].startswith("text/event-stream")


def test_first_event_is_workflow_started(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-first", "message": ACCEPTANCE_QUERY})
    assert events[0]["event"] == "workflow_started"
    assert events[0]["id"] == 1


def test_event_ids_increase_in_order(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-ids", "message": ACCEPTANCE_QUERY})
    ids = [event["id"] for event in events if event["id"] is not None]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert ids[0] == 1


def test_events_contain_workflow_id_and_session_id(client):
    _, _, events = _stream_and_collect(
        client, {"session_id": "demo-session-001", "message": ACCEPTANCE_QUERY}
    )
    workflow_ids = {event["data"]["workflow_id"] for event in events}
    session_ids = {event["data"]["session_id"] for event in events}
    assert len(workflow_ids) == 1
    assert session_ids == {"demo-session-001"}


def test_product_search_emits_a_safe_catalog_search_event(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-catalog", "message": ACCEPTANCE_QUERY})
    labels = {event["data"]["label"] for event in events}
    assert "Recommendation Agent searching products" in labels


def test_pickup_request_emits_an_inventory_check_event(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-pickup", "message": ACCEPTANCE_QUERY})
    labels = {event["data"]["label"] for event in events}
    assert "Inventory Agent checking selected store" in labels


def test_nearby_fallback_emits_a_nearby_store_event(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-nearby", "message": ACCEPTANCE_QUERY})
    labels = {event["data"]["label"] for event in events}
    assert "Inventory Agent checking nearby stores" in labels


def test_verification_emits_verification_events(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-verify", "message": ACCEPTANCE_QUERY})
    labels = {event["data"]["label"] for event in events}
    assert "Verifying claims" in labels


def test_final_response_event_contains_verified_output(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-final", "message": ACCEPTANCE_QUERY})
    final_event = _find(events, "final_response")
    assert final_event is not None
    payload = final_event["data"]["data"]
    assert payload["status"] == "completed"
    assert [p["product_id"] for p in payload["products"]] == ["FTW-004"]
    assert final_event["data"]["label"] == "Completed"


def test_stream_activity_labels_are_canonical_and_not_duplicated(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-canonical", "message": ACCEPTANCE_QUERY})
    activity_labels = [
        event["data"]["label"]
        for event in events
        if event["event"] in {"workflow_started", "agent_selected", "tool_started", "verification_started"}
    ]
    allowed = {
        "Understanding request",
        "Recommendation Agent searching products",
        "Inventory Agent checking selected store",
        "Inventory Agent checking nearby stores",
        "External Offer Agent searching alternatives",
        "Order Agent retrieving order evidence",
        "Verifying claims",
        "Preparing response",
        "Completed",
        "Stopped safely",
    }
    assert set(activity_labels) <= allowed
    assert len(activity_labels) == len(set(activity_labels))


def test_stream_ends_with_stream_closed(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-closed", "message": ACCEPTANCE_QUERY})
    assert events[-1]["event"] == "stream_closed"


# ---------------------------------------------------------------------------
# 12-13: normal business outcomes that are not a completed recommendation
# ---------------------------------------------------------------------------


def test_vague_request_emits_clarification_required(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-vague", "message": "hi there"})
    clarification_event = _find(events, "clarification_required")
    assert clarification_event is not None
    assert clarification_event["data"]["data"]["question"]

    final_event = _find(events, "final_response")
    assert final_event["data"]["data"]["status"] == "clarification_required"
    assert events[-1]["event"] == "stream_closed"


def test_no_match_request_ends_safely_with_no_results(client):
    _, _, events = _stream_and_collect(
        client,
        {
            "session_id": "s-nomatch",
            "message": "Find work shoes under $1 that I can pick up today near Maple Grove.",
        },
    )
    final_event = _find(events, "final_response")
    assert final_event["data"]["data"]["status"] == "no_results"
    assert _find(events, "workflow_failed") is None
    assert events[-1]["event"] == "stream_closed"


# ---------------------------------------------------------------------------
# 14-16: service failures and unexpected errors, via a stubbed graph
# ---------------------------------------------------------------------------


def test_tool_failure_emits_workflow_failed(client, override_graph):
    override_graph(_StubStreamGraph(chunks=[], raise_error=sqlite3.Error("database is locked")))

    status_code, _, events = _stream_and_collect(client, {"session_id": "s-toolfail", "message": "hello"})

    assert status_code == 200
    failed_event = _find(events, "workflow_failed")
    assert failed_event is not None
    assert failed_event["data"]["data"]["code"] == "TOOL_UNAVAILABLE"
    assert "database is locked" not in json.dumps(failed_event["data"])
    assert events[-1]["event"] == "stream_closed"


def test_workflow_timeout_emits_a_safe_failure(client, override_graph, monkeypatch):
    monkeypatch.setenv("SCOUT_WORKFLOW_TIMEOUT_SECONDS", "0.05")
    get_settings.cache_clear()

    override_graph(_StubStreamGraph(chunks=[{"understand_request": {}}], delay=0.5))

    status_code, _, events = _stream_and_collect(client, {"session_id": "s-timeout", "message": "hello"})

    assert status_code == 200
    failed_event = _find(events, "workflow_failed")
    assert failed_event is not None
    assert failed_event["data"]["data"]["code"] == "WORKFLOW_TIMEOUT"
    assert events[-1]["event"] == "stream_closed"

    get_settings.cache_clear()


def test_raw_exception_text_is_not_exposed(client, override_graph):
    override_graph(
        _StubStreamGraph(chunks=[], raise_error=RuntimeError("supervisor secret trace: /etc/passwd key=abc123"))
    )

    status_code, _, events = _stream_and_collect(client, {"session_id": "s-crash", "message": "hello"})

    assert status_code == 200
    failed_event = _find(events, "workflow_failed")
    assert failed_event is not None
    assert failed_event["data"]["data"]["code"] == "INTERNAL_ERROR"

    rendered = json.dumps(events)
    assert "RuntimeError" not in rendered
    assert "/etc/passwd" not in rendered
    assert "secret trace" not in rendered
    assert "Traceback" not in rendered
    assert events[-1]["event"] == "stream_closed"


# ---------------------------------------------------------------------------
# 17: no leaked internals in a normal, successful stream
# ---------------------------------------------------------------------------


def test_prompts_and_chain_of_thought_are_not_exposed(client):
    _, _, events = _stream_and_collect(client, {"session_id": "s-safe", "message": ACCEPTANCE_QUERY})
    rendered = json.dumps(events).lower()

    forbidden_substrings = [
        "select ",
        "insert into",
        "password",
        "secret",
        "api_key",
        "chain of thought",
        "you are a helpful assistant",
        "system prompt",
        "/users/",
        "/scout/agents/",
        "traceback",
    ]
    for forbidden in forbidden_substrings:
        assert forbidden not in rendered


# ---------------------------------------------------------------------------
# 18: client disconnect
# ---------------------------------------------------------------------------


def test_client_disconnect_is_handled_safely(client, override_graph):
    stub = _StubStreamGraph(
        chunks=[{"understand_request": {"step_count": 1}}, {"supervisor": {"step_count": 2}}],
        delay=0.2,
    )
    override_graph(stub)

    with client.stream(
        "POST", "/chat/stream", json={"session_id": "s-disconnect", "message": "hello"}
    ) as response:
        for line in response.iter_lines():
            if line.startswith("event:"):
                break

    # A normal disconnect must not crash the application - the server
    # must still be healthy right afterward.
    health_response = client.get("/health")
    assert health_response.status_code == 200


# ---------------------------------------------------------------------------
# 19-20: the endpoints from earlier phases still work
# ---------------------------------------------------------------------------


def test_existing_chat_endpoint_still_passes(client):
    response = client.post("/chat", json={"session_id": "s-chat-still-works", "message": ACCEPTANCE_QUERY})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_existing_health_endpoint_still_passes(client):
    response = client.get("/health")
    assert response.status_code == 200
