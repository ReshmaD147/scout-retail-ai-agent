"""Step 17 deterministic order-status and eligibility tests."""

from datetime import datetime, timedelta, timezone

import pytest

from scout.database.connection import connection_scope
from scout.services.order_service import OrderServiceError, lookup_latest_order, lookup_order
from tests.order_helpers import create_delivery_order, create_pickup_order


def test_lookup_returns_order_payment_pickup_estimate_and_eligibility(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "service-order")

    view = lookup_order(created.order_id, "service-order", db_path=seeded_db_path)

    assert view.order_status == "confirmed"
    assert view.payment.status == "succeeded"
    assert view.fulfillment.fulfillment_type == "pickup"
    assert view.fulfillment.store_name == "Scout Demo Store - Plymouth"
    assert view.fulfillment.estimated_ready_at is not None
    assert view.fulfillment.tracking.available is False
    assert view.eligibility.cancellation.eligible is True
    assert view.eligibility.return_eligibility.eligible is False
    assert view.eligibility.exchange.eligible is False


def test_delivery_order_reports_address_arrival_estimate_and_pending_tracking(seeded_db_path):
    created = create_delivery_order(seeded_db_path, "delivery-status")

    view = lookup_order(created.order_id, "delivery-status", db_path=seeded_db_path)

    assert view.fulfillment.fulfillment_type == "delivery"
    assert view.fulfillment.shipping_address.city == "Maple Grove"
    assert view.fulfillment.estimated_delivery_at is not None
    assert view.fulfillment.estimated_ready_at is None
    assert view.fulfillment.tracking.available is False
    assert "not been assigned" in view.fulfillment.tracking.message


def test_session_isolation_hides_an_order(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "owner-session")
    with pytest.raises(OrderServiceError) as exc_info:
        lookup_order(created.order_id, "other-session", db_path=seeded_db_path)
    assert exc_info.value.error_type == "order_not_found"


def test_latest_order_lookup_uses_the_current_session(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "latest-session")
    view = lookup_latest_order("latest-session", db_path=seeded_db_path)
    assert view.order_id == created.order_id


def test_persisted_shipping_tracking_is_reported(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "tracked-order")
    now = datetime.now(timezone.utc)
    with connection_scope(seeded_db_path) as connection:
        connection.execute(
            """
            UPDATE order_fulfillments
            SET fulfillment_status = 'shipped', carrier_name = 'Demo Carrier',
                tracking_number = 'TRACK-123', tracking_url = 'https://example.com/track/TRACK-123',
                shipped_at = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (now.isoformat(), now.isoformat(), created.order_id),
        )

    view = lookup_order(created.order_id, "tracked-order", db_path=seeded_db_path)

    assert view.fulfillment.status == "shipped"
    assert view.fulfillment.tracking.available is True
    assert view.fulfillment.tracking.tracking_number == "TRACK-123"
    assert view.eligibility.cancellation.eligible is False


def test_delivered_order_within_policy_window_is_return_and_exchange_eligible(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "completed-order")
    completed_at = datetime.now(timezone.utc) - timedelta(days=2)
    with connection_scope(seeded_db_path) as connection:
        connection.execute(
            """
            UPDATE order_fulfillments
            SET fulfillment_status = 'picked_up', picked_up_at = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (completed_at.isoformat(), completed_at.isoformat(), created.order_id),
        )

    view = lookup_order(created.order_id, "completed-order", db_path=seeded_db_path)

    assert view.eligibility.return_eligibility.eligible is True
    assert view.eligibility.exchange.eligible is True
    assert view.eligibility.cancellation.eligible is False
