"""Step 16 checkout REST API integration tests."""

import sqlite3

import pytest

from scout.config import get_settings
from scout.services.payment_service import PaymentServiceError, WebhookEvent

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


def test_checkout_preflight_allows_localhost_and_127_origins(client):
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.options(
            "/checkout/sessions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


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


def test_stripe_webhook_rejects_invalid_signature(client, monkeypatch):
    class RejectingProvider:
        def verify_webhook(self, payload, signature):
            raise PaymentServiceError("invalid_webhook_signature", "Invalid Stripe webhook signature.")

    monkeypatch.setattr("scout.api.routes.checkout.get_payment_provider", lambda: RejectingProvider())

    response = client.post("/checkout/stripe/webhook", content=b"{}", headers={"stripe-signature": "bad"})

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_WEBHOOK_SIGNATURE"


def test_stripe_webhook_processing_updates_payment_state(client, seeded_db_path, monkeypatch):
    _prepare_pickup_cart(client, "api-stripe-processing")
    review = client.post("/checkout/sessions", json={"session_id": "api-stripe-processing"}).json()
    with sqlite3.connect(seeded_db_path) as connection:
        connection.execute(
            """
            UPDATE checkout_sessions
            SET status = 'processing',
                payment_provider = 'stripe_test',
                payment_intent_id = 'pi_processing',
                payment_status = 'payment_processing',
                confirm_idempotency_key = 'stripe-api-key'
            WHERE checkout_id = ?
            """,
            (review["checkout_id"],),
        )

    class ProcessingProvider:
        def verify_webhook(self, payload, signature):
            return WebhookEvent(
                event_id="evt_processing",
                event_type="payment_intent.processing",
                payment_intent_id="pi_processing",
                checkout_id=review["checkout_id"],
                session_id="api-stripe-processing",
            )

    monkeypatch.setattr("scout.api.routes.checkout.get_payment_provider", lambda: ProcessingProvider())

    response = client.post("/checkout/stripe/webhook", content=b"{}", headers={"stripe-signature": "ok"})

    assert response.status_code == 200
    assert response.json()["status"] == "payment_processing"
