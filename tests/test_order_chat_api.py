"""Step 17 chat and SSE integration for order-status requests."""

import json

import pytest

from scout.config import get_settings
from tests.order_helpers import create_pickup_order


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield seeded_db_path
    get_settings.cache_clear()


def _events(text: str):
    parsed = []
    for block in text.strip().split("\n\n"):
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
        if event:
            parsed.append((event, data))
    return parsed


def test_chat_returns_verified_order_status(client, _use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "chat-order")
    response = client.post("/chat", json={"session_id": "chat-order", "message": "Where is my order?"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["order"]["order_id"] == created.order_id
    assert body["products"] == []
    assert "Order Agent retrieving order evidence" in body["activity_events"]


def test_chat_can_lookup_an_explicit_order_id(client, _use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "chat-explicit")
    response = client.post(
        "/chat",
        json={"session_id": "chat-explicit", "message": f"Track order {created.order_id}"},
    )
    assert response.json()["order"]["order_id"] == created.order_id


def test_stream_final_response_contains_order_status(client, _use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "stream-order")
    with client.stream(
        "POST",
        "/chat/stream",
        json={"session_id": "stream-order", "message": "Where is my order?"},
    ) as response:
        text = response.read().decode()
    events = _events(text)
    final = next(data for event, data in events if event == "final_response")
    assert final["data"]["order"]["order_id"] == created.order_id
    labels = {data["label"] for _event, data in events}
    assert "Order Agent retrieving order evidence" in labels
