"""Step 16 checkout REST API integration tests."""

import pytest

from scout.config import get_settings

PRODUCT = "FTW-004"
STORE = "STR-002"


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _prepare_pickup_cart(client, session_id: str):
    assert client.post(
        "/cart/items", json={"session_id": session_id, "product_id": PRODUCT, "quantity": 1}
    ).status_code == 200
    assert client.put(
        f"/cart/{session_id}/fulfillment",
        json={"fulfillment_type": "pickup", "store_id": STORE},
    ).status_code == 200


def test_create_review_and_confirm_order(client):
    _prepare_pickup_cart(client, "api-checkout")
    review_response = client.post(
        "/checkout/sessions", json={"session_id": "api-checkout", "shipping_address": None}
    )
    assert review_response.status_code == 200
    review = review_response.json()
    assert review["total"] > 0

    confirmation = client.post(
        f"/checkout/sessions/{review['checkout_id']}/confirm",
        json={
            "session_id": "api-checkout",
            "idempotency_key": "api-checkout-key-0001",
            "confirm_payment": True,
            "payment_method_token": "mock_success",
        },
    )
    assert confirmation.status_code == 200
    body = confirmation.json()
    assert body["status"] == "confirmed"
    assert body["payment"]["status"] == "succeeded"


def test_confirm_without_explicit_confirmation_returns_structured_error(client):
    _prepare_pickup_cart(client, "api-no-confirm")
    review = client.post(
        "/checkout/sessions", json={"session_id": "api-no-confirm"}
    ).json()
    response = client.post(
        f"/checkout/sessions/{review['checkout_id']}/confirm",
        json={
            "session_id": "api-no-confirm",
            "idempotency_key": "api-checkout-key-0002",
            "confirm_payment": False,
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "CONFIRMATION_REQUIRED"


def test_duplicate_api_confirmation_is_idempotent(client):
    _prepare_pickup_cart(client, "api-idempotent")
    review = client.post(
        "/checkout/sessions", json={"session_id": "api-idempotent"}
    ).json()
    payload = {
        "session_id": "api-idempotent",
        "idempotency_key": "api-checkout-key-0003",
        "confirm_payment": True,
    }
    first = client.post(f"/checkout/sessions/{review['checkout_id']}/confirm", json=payload)
    second = client.post(f"/checkout/sessions/{review['checkout_id']}/confirm", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["order_id"] == second.json()["order_id"]
