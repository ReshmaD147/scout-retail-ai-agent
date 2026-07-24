from fastapi.testclient import TestClient

from scout.api.app import create_app
from scout.config import get_settings
from scout.services.protected_action_service import ProtectedActionProposalRequest, propose_action
from tests.order_helpers import create_pickup_order


def _client_for_db(db_path: str, monkeypatch) -> TestClient:
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", db_path)
    get_settings.cache_clear()
    try:
        return TestClient(create_app())
    finally:
        get_settings.cache_clear()


def test_protected_action_confirm_endpoint_rejects_other_customer(seeded_db_path, monkeypatch):
    client = _client_for_db(seeded_db_path, monkeypatch)
    created = create_pickup_order(seeded_db_path, "api-pa-owner")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="api-pa-owner",
            customer_id="cust-api-owner",
            action_type="cancel_order",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )

    response = client.post(
        "/protected-actions/confirm",
        json={
            "confirmation_id": proposal.confirmation_id,
            "session_id": "api-pa-owner",
            "customer_id": "cust-api-other",
            "decision": "approve",
        },
    )

    assert response.status_code == 403


def test_protected_action_proposal_and_approval_api(seeded_db_path, monkeypatch):
    client = _client_for_db(seeded_db_path, monkeypatch)
    created = create_pickup_order(seeded_db_path, "api-pa-approve")

    proposal_response = client.post(
        "/protected-actions/proposals",
        json={
            "session_id": "api-pa-approve",
            "customer_id": "cust-api-approve",
            "action_type": "cancel_order",
            "order_id": created.order_id,
        },
    )
    assert proposal_response.status_code == 200
    confirmation_id = proposal_response.json()["confirmation_id"]

    confirm_response = client.post(
        "/protected-actions/confirm",
        json={
            "confirmation_id": confirmation_id,
            "session_id": "api-pa-approve",
            "customer_id": "cust-api-approve",
            "decision": "approve",
        },
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json()["result_state"] == "canceled"
