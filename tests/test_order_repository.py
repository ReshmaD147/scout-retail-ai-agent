"""Step 17 read-only order repository tests."""

from scout.repositories.order_repository import OrderRepository
from tests.order_helpers import create_pickup_order


def test_repository_looks_up_a_session_owned_order(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "repo-order")
    repository = OrderRepository(seeded_db_path)

    order = repository.get_by_id_for_session(created.order_id, "repo-order")

    assert order is not None
    assert order.order_id == created.order_id
    assert repository.get_by_id_for_session(created.order_id, "different-session") is None


def test_repository_returns_payment_items_reservations_and_fulfillment(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "repo-details")
    repository = OrderRepository(seeded_db_path)

    assert repository.get_payment(created.order_id).status == "succeeded"
    assert len(repository.list_items(created.order_id)) == 1
    assert len(repository.list_reservations(created.order_id)) == 1
    fulfillment = repository.get_fulfillment(created.order_id)
    assert fulfillment is not None
    assert fulfillment.fulfillment_status == "processing"
    assert fulfillment.estimated_ready_at is not None


def test_repository_returns_latest_order_for_session(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "repo-latest")
    latest = OrderRepository(seeded_db_path).get_latest_for_session("repo-latest")
    assert latest is not None
    assert latest.order_id == created.order_id
