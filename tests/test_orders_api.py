"""Step 17 read-only order REST API tests."""

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


def test_order_api_returns_complete_read_only_status(client, _use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "api-order")
    response = client.get(f"/orders/{created.order_id}?session_id=api-order")
    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == created.order_id
    assert body["payment"]["status"] == "succeeded"
    assert body["fulfillment"]["fulfillment_type"] == "pickup"
    assert body["eligibility"]["cancellation"]["eligible"] is True


def test_latest_and_focused_order_endpoints(client, _use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "api-latest")
    assert client.get("/orders/latest?session_id=api-latest").json()["order_id"] == created.order_id
    assert client.get(f"/orders/{created.order_id}/status?session_id=api-latest").json()["order_status"] == "confirmed"
    assert client.get(f"/orders/{created.order_id}/payment?session_id=api-latest").json()["status"] == "succeeded"
    assert client.get(f"/orders/{created.order_id}/fulfillment?session_id=api-latest").json()["status"] == "processing"
    assert "return_eligibility" in client.get(
        f"/orders/{created.order_id}/eligibility?session_id=api-latest"
    ).json()


def test_order_api_enforces_session_isolation(client, _use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "api-owner")
    response = client.get(f"/orders/{created.order_id}?session_id=wrong-session")
    assert response.status_code == 404
    assert response.json()["code"] == "ORDER_NOT_FOUND"
