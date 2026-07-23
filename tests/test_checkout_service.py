"""Step 16 deterministic checkout service tests."""

import sqlite3

import pytest

from scout.config import get_settings
from scout.services import cart_service, checkout_service
from scout.services.checkout_service import CheckoutServiceError, ShippingAddress
from scout.services.payment_service import PaymentIntentResult, WebhookEvent

PRODUCT = "FTW-004"
PICKUP_STORE = "STR-002"


def _pickup_cart(db_path: str, session_id: str = "checkout-session"):
    cart_service.add_item(session_id, PRODUCT, 1, db_path=db_path)
    cart_service.set_fulfillment(session_id, "pickup", PICKUP_STORE, db_path=db_path)


def _delivery_address() -> ShippingAddress:
    return ShippingAddress(
        full_name="Scout Customer",
        line1="123 Main Street",
        city="Maple Grove",
        state="MN",
        postal_code="55369",
    )


def test_checkout_requires_a_nonempty_cart(seeded_db_path):
    with pytest.raises(CheckoutServiceError) as exc_info:
        checkout_service.create_checkout_review("missing-cart", db_path=seeded_db_path)
    assert exc_info.value.error_type == "cart_not_found"


def test_checkout_requires_fulfillment_selection(seeded_db_path):
    cart_service.add_item("s1", PRODUCT, 1, db_path=seeded_db_path)
    with pytest.raises(CheckoutServiceError) as exc_info:
        checkout_service.create_checkout_review("s1", db_path=seeded_db_path)
    assert exc_info.value.error_type == "fulfillment_required"


def test_delivery_requires_shipping_address(seeded_db_path):
    cart_service.add_item("s1", PRODUCT, 1, db_path=seeded_db_path)
    cart_service.set_fulfillment("s1", "delivery", None, db_path=seeded_db_path)
    with pytest.raises(CheckoutServiceError) as exc_info:
        checkout_service.create_checkout_review("s1", db_path=seeded_db_path)
    assert exc_info.value.error_type == "shipping_address_required"


def test_review_calculates_discount_tax_shipping_and_total_server_side(seeded_db_path):
    _pickup_cart(seeded_db_path)
    review = checkout_service.create_checkout_review("checkout-session", db_path=seeded_db_path)

    assert review.subtotal == round(sum(item.line_subtotal for item in review.items), 2)
    assert review.discount_total == round(review.subtotal - review.merchandise_total, 2)
    assert review.tax_total == round(review.merchandise_total * get_settings().checkout_tax_rate, 2)
    assert review.shipping_total == 0.0  # pickup
    assert review.total == round(review.merchandise_total + review.tax_total, 2)
    assert review.payment_provider == "mock"


def test_delivery_review_persists_the_address(seeded_db_path):
    cart_service.add_item("s1", PRODUCT, 1, db_path=seeded_db_path)
    cart_service.set_fulfillment("s1", "delivery", None, db_path=seeded_db_path)
    review = checkout_service.create_checkout_review(
        "s1", _delivery_address(), db_path=seeded_db_path
    )
    assert review.shipping_address is not None
    assert review.shipping_address.city == "Maple Grove"


def test_confirmation_must_be_explicit(seeded_db_path):
    _pickup_cart(seeded_db_path)
    review = checkout_service.create_checkout_review("checkout-session", db_path=seeded_db_path)
    with pytest.raises(CheckoutServiceError) as exc_info:
        checkout_service.confirm_checkout(
            checkout_id=review.checkout_id,
            session_id="checkout-session",
            idempotency_key="checkout-key-0001",
            confirm_payment=False,
            db_path=seeded_db_path,
        )
    assert exc_info.value.error_type == "confirmation_required"


def test_confirmation_creates_order_payment_and_inventory_reservation_atomically(seeded_db_path):
    _pickup_cart(seeded_db_path)
    review = checkout_service.create_checkout_review("checkout-session", db_path=seeded_db_path)

    with sqlite3.connect(seeded_db_path) as connection:
        before_reserved = connection.execute(
            "SELECT quantity_reserved FROM inventory WHERE product_id = ? AND store_id = ?",
            (PRODUCT, PICKUP_STORE),
        ).fetchone()[0]

    order = checkout_service.confirm_checkout(
        checkout_id=review.checkout_id,
        session_id="checkout-session",
        idempotency_key="checkout-key-0002",
        confirm_payment=True,
        db_path=seeded_db_path,
    )

    assert order.status == "confirmed"
    assert order.payment.status == "succeeded"
    assert order.total == review.total
    assert order.items[0].reservations[0].store_id == PICKUP_STORE

    with sqlite3.connect(seeded_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM inventory_reservations").fetchone()[0] == 1
        after_reserved = connection.execute(
            "SELECT quantity_reserved FROM inventory WHERE product_id = ? AND store_id = ?",
            (PRODUCT, PICKUP_STORE),
        ).fetchone()[0]
        cart_status = connection.execute(
            "SELECT status FROM carts WHERE cart_id = ?", (review.cart_id,)
        ).fetchone()[0]
    assert after_reserved == before_reserved + 1
    assert cart_status == "converted"


def test_duplicate_confirmation_returns_the_same_order_without_double_reserving(seeded_db_path):
    _pickup_cart(seeded_db_path)
    review = checkout_service.create_checkout_review("checkout-session", db_path=seeded_db_path)
    kwargs = dict(
        checkout_id=review.checkout_id,
        session_id="checkout-session",
        idempotency_key="checkout-key-0003",
        confirm_payment=True,
        db_path=seeded_db_path,
    )
    first = checkout_service.confirm_checkout(**kwargs)
    second = checkout_service.confirm_checkout(**kwargs)

    assert first.order_id == second.order_id
    with sqlite3.connect(seeded_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM inventory_reservations").fetchone()[0] == 1


def test_changed_price_requires_a_new_review(seeded_db_path):
    _pickup_cart(seeded_db_path)
    review = checkout_service.create_checkout_review("checkout-session", db_path=seeded_db_path)
    with sqlite3.connect(seeded_db_path) as connection:
        connection.execute("UPDATE products SET price = price + 10 WHERE product_id = ?", (PRODUCT,))

    with pytest.raises(CheckoutServiceError) as exc_info:
        checkout_service.confirm_checkout(
            checkout_id=review.checkout_id,
            session_id="checkout-session",
            idempotency_key="checkout-key-0004",
            confirm_payment=True,
            db_path=seeded_db_path,
        )
    assert exc_info.value.error_type == "checkout_changed"
    with sqlite3.connect(seeded_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_mock_decline_creates_no_order_or_reservation(seeded_db_path):
    _pickup_cart(seeded_db_path)
    review = checkout_service.create_checkout_review("checkout-session", db_path=seeded_db_path)

    with pytest.raises(CheckoutServiceError) as exc_info:
        checkout_service.confirm_checkout(
            checkout_id=review.checkout_id,
            session_id="checkout-session",
            idempotency_key="checkout-key-0005",
            confirm_payment=True,
            payment_method_token="mock_decline",
            db_path=seeded_db_path,
        )
    assert exc_info.value.error_type == "payment_declined"
    with sqlite3.connect(seeded_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM inventory_reservations").fetchone()[0] == 0


class _FakeStripeProvider:
    def create_payment_intent(self, *, checkout_id, session_id, amount, currency, idempotency_key):
        return PaymentIntentResult(
            provider="stripe_test",
            provider_reference=f"pi_{idempotency_key}",
            status="payment_processing",
            amount=amount,
            currency=currency,
            client_secret=f"pi_{idempotency_key}_secret_test",
            publishable_key="pk_test_fake",
        )


@pytest.fixture()
def stripe_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("PAYMENT_PROVIDER", "stripe_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_fake")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_fake")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_stripe_payment_intent_uses_backend_total_and_stores_no_secret(seeded_db_path, stripe_settings, monkeypatch):
    _pickup_cart(seeded_db_path)
    review = checkout_service.create_checkout_review("checkout-session", db_path=seeded_db_path)
    monkeypatch.setattr(checkout_service, "get_payment_provider", lambda: _FakeStripeProvider())

    intent = checkout_service.create_checkout_payment_intent(
        checkout_id=review.checkout_id,
        session_id="checkout-session",
        idempotency_key="stripe-key-0001",
        db_path=seeded_db_path,
    )

    assert intent.amount == review.total
    assert intent.client_secret.endswith("_secret_test")
    with sqlite3.connect(seeded_db_path) as connection:
        row = connection.execute(
            "SELECT payment_intent_id, payment_status, review_json FROM checkout_sessions WHERE checkout_id = ?",
            (review.checkout_id,),
        ).fetchone()
    assert row[0] == "pi_stripe-key-0001"
    assert row[1] == "payment_processing"
    assert "secret" not in row[2]


def test_stripe_webhook_success_creates_order_once(seeded_db_path, stripe_settings, monkeypatch):
    _pickup_cart(seeded_db_path)
    review = checkout_service.create_checkout_review("checkout-session", db_path=seeded_db_path)
    monkeypatch.setattr(checkout_service, "get_payment_provider", lambda: _FakeStripeProvider())
    checkout_service.create_checkout_payment_intent(
        checkout_id=review.checkout_id,
        session_id="checkout-session",
        idempotency_key="stripe-key-0002",
        db_path=seeded_db_path,
    )
    event = WebhookEvent(
        event_id="evt_1",
        event_type="payment_intent.succeeded",
        payment_intent_id="pi_stripe-key-0002",
        amount=review.total,
        currency=review.currency,
        checkout_id=review.checkout_id,
        session_id="checkout-session",
    )

    first = checkout_service.complete_stripe_checkout_from_event(event, db_path=seeded_db_path)
    duplicate = checkout_service.complete_stripe_checkout_from_event(event, db_path=seeded_db_path)

    assert first.status == "order_created"
    assert duplicate.status == "order_created"
    assert first.order_id == duplicate.order_id
    with sqlite3.connect(seeded_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM inventory_reservations").fetchone()[0] == 1


def test_stripe_webhook_rejects_amount_currency_and_session_mismatches(seeded_db_path, stripe_settings, monkeypatch):
    _pickup_cart(seeded_db_path)
    review = checkout_service.create_checkout_review("checkout-session", db_path=seeded_db_path)
    monkeypatch.setattr(checkout_service, "get_payment_provider", lambda: _FakeStripeProvider())
    checkout_service.create_checkout_payment_intent(
        checkout_id=review.checkout_id,
        session_id="checkout-session",
        idempotency_key="stripe-key-0003",
        db_path=seeded_db_path,
    )
    base = {
        "event_id": "evt_bad",
        "event_type": "payment_intent.succeeded",
        "payment_intent_id": "pi_stripe-key-0003",
        "amount": review.total,
        "currency": review.currency,
        "checkout_id": review.checkout_id,
        "session_id": "checkout-session",
    }
    for override, error_type in [
        ({"amount": review.total + 1}, "payment_amount_mismatch"),
        ({"currency": "EUR"}, "payment_currency_mismatch"),
        ({"session_id": "someone-else"}, "payment_session_mismatch"),
    ]:
        with pytest.raises(CheckoutServiceError) as exc_info:
            checkout_service.complete_stripe_checkout_from_event(
                WebhookEvent(**{**base, **override, "event_id": f"evt_{error_type}"}),
                db_path=seeded_db_path,
            )
        assert exc_info.value.error_type == error_type
