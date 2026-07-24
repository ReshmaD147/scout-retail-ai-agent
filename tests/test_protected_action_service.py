import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from scout.config import get_settings
from scout.repositories.protected_action_repository import ProtectedActionRepository
from scout.services import cart_service, checkout_service
from scout.services.checkout_service import ShippingAddress
from scout.services.payment_service import PaymentIntentResult
from scout.services.protected_action_service import (
    ProtectedActionDecisionRequest,
    ProtectedActionError,
    ProtectedActionProposalRequest,
    decide_confirmation,
    propose_action,
)
from tests.order_helpers import PRODUCT, create_delivery_order, create_pickup_order


def test_cancel_order_proposal_requires_owned_order(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-owned")

    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-owned",
            customer_id="cust-pa-owned",
            action_type="cancel_order",
            order_id=created.order_id,
            workflow_id="wf-pa-owned",
        ),
        db_path=seeded_db_path,
    )

    assert proposal.status == "awaiting_confirmation"
    assert proposal.resource_id == created.order_id
    assert proposal.eligibility_status == "eligible"


def test_authentication_failure_rejects_blank_customer_id():
    with pytest.raises(ValidationError):
        ProtectedActionProposalRequest(
            session_id="sess-auth",
            customer_id=" ",
            action_type="cancel_order",
            order_id="ORD-1",
        )


def test_proposal_rejects_wrong_session_ownership(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-owner")

    with pytest.raises(ProtectedActionError) as exc_info:
        propose_action(
            ProtectedActionProposalRequest(
                session_id="pa-other",
                customer_id="cust-pa-other",
                action_type="cancel_order",
                order_id=created.order_id,
            ),
            db_path=seeded_db_path,
        )

    assert exc_info.value.error_type == "order_not_found"


def test_explicit_rejection_consumes_confirmation_without_execution(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-reject")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-reject",
            customer_id="cust-pa-reject",
            action_type="cancel_order",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )

    result = decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-reject",
            customer_id="cust-pa-reject",
            decision="reject",
        ),
        db_path=seeded_db_path,
    )

    assert result.execution_status == "rejected"
    with sqlite3.connect(seeded_db_path) as connection:
        assert connection.execute("SELECT status FROM orders WHERE order_id = ?", (created.order_id,)).fetchone()[0] == "confirmed"


def test_explicit_approval_cancels_and_verifies_order(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-approve")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-approve",
            customer_id="cust-pa-approve",
            action_type="cancel_order",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )

    result = decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-approve",
            customer_id="cust-pa-approve",
            decision="approve",
        ),
        db_path=seeded_db_path,
    )

    assert result.execution_status == "verified"
    assert result.result_state == "canceled"
    assert "canceled successfully" in result.message


def test_duplicate_approval_returns_verified_result_once(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-duplicate")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-duplicate",
            customer_id="cust-pa-duplicate",
            action_type="cancel_order",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )
    request = ProtectedActionDecisionRequest(
        confirmation_id=proposal.confirmation_id,
        session_id="pa-duplicate",
        customer_id="cust-pa-duplicate",
        decision="approve",
    )

    first = decide_confirmation(request, db_path=seeded_db_path)
    second = decide_confirmation(request, db_path=seeded_db_path)

    assert first == second


def test_modified_payload_hash_is_rejected(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-payload")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-payload",
            customer_id="cust-pa-payload",
            action_type="cancel_order",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )

    with pytest.raises(ProtectedActionError) as exc_info:
        decide_confirmation(
            ProtectedActionDecisionRequest(
                confirmation_id=proposal.confirmation_id,
                session_id="pa-payload",
                customer_id="cust-pa-payload",
                decision="approve",
                payload_hash="0" * 64,
            ),
            db_path=seeded_db_path,
        )

    assert exc_info.value.error_type == "payload_hash_mismatch"


def test_eligibility_change_before_execution_stops_safely(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-eligibility-change")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-eligibility-change",
            customer_id="cust-pa-eligibility-change",
            action_type="cancel_order",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )
    with sqlite3.connect(seeded_db_path) as connection:
        connection.execute(
            "UPDATE order_fulfillments SET fulfillment_status = 'picked_up', picked_up_at = ? WHERE order_id = ?",
            (datetime.now(timezone.utc).isoformat(), created.order_id),
        )

    result = decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-eligibility-change",
            customer_id="cust-pa-eligibility-change",
            decision="approve",
        ),
        db_path=seeded_db_path,
    )

    assert result.execution_status == "failed"
    assert result.result_state == "eligibility_changed"


def test_expired_confirmation_does_not_execute(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-expired")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-expired",
            customer_id="cust-pa-expired",
            action_type="cancel_order",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )
    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(seeded_db_path) as connection:
        connection.execute(
            "UPDATE protected_action_confirmations SET expires_at = ? WHERE confirmation_id = ?",
            (expired_at, proposal.confirmation_id),
        )

    result = decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-expired",
            customer_id="cust-pa-expired",
            decision="approve",
        ),
        db_path=seeded_db_path,
    )

    assert result.execution_status == "expired"
    with sqlite3.connect(seeded_db_path) as connection:
        assert connection.execute("SELECT status FROM orders WHERE order_id = ?", (created.order_id,)).fetchone()[0] == "confirmed"


def test_return_request_submission_is_not_refund_execution(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-return")
    with sqlite3.connect(seeded_db_path) as connection:
        connection.execute(
            """
            UPDATE order_fulfillments
            SET fulfillment_status = 'picked_up', picked_up_at = ?
            WHERE order_id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), created.order_id),
        )
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-return",
            customer_id="cust-pa-return",
            action_type="create_return_request",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )

    result = decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-return",
            customer_id="cust-pa-return",
            decision="approve",
        ),
        db_path=seeded_db_path,
    )

    assert result.result_state == "request_submitted"
    assert result.request_id is not None
    assert "submitted for review" in result.message


def test_exchange_request_submission_is_review_only(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-exchange")
    with sqlite3.connect(seeded_db_path) as connection:
        connection.execute(
            "UPDATE order_fulfillments SET fulfillment_status = 'picked_up', picked_up_at = ? WHERE order_id = ?",
            (datetime.now(timezone.utc).isoformat(), created.order_id),
        )
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-exchange",
            customer_id="cust-pa-exchange",
            action_type="create_exchange_request",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )

    result = decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-exchange",
            customer_id="cust-pa-exchange",
            decision="approve",
        ),
        db_path=seeded_db_path,
    )

    assert result.result_state == "request_submitted"
    assert "Exchange request" in result.message


def test_address_change_request_requires_delivery_processing(seeded_db_path):
    created = create_delivery_order(seeded_db_path, "pa-address")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-address",
            customer_id="cust-pa-address",
            action_type="change_order_address",
            order_id=created.order_id,
            shipping_address=ShippingAddress(
                full_name="Scout Customer",
                line1="456 New Street",
                city="Maple Grove",
                state="MN",
                postal_code="55311",
            ),
        ),
        db_path=seeded_db_path,
    )

    result = decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-address",
            customer_id="cust-pa-address",
            decision="approve",
        ),
        db_path=seeded_db_path,
    )

    assert result.result_state == "request_submitted"
    assert "Address change request" in result.message


def test_refund_request_submission_does_not_issue_refund(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-refund")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-refund",
            customer_id="cust-pa-refund",
            action_type="create_refund_request",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )

    result = decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-refund",
            customer_id="cust-pa-refund",
            decision="approve",
        ),
        db_path=seeded_db_path,
    )

    assert result.result_state == "request_submitted"
    assert "does not mean the refund has been approved or issued" in result.message


class _FakeStripeProvider:
    def create_payment_intent(self, *, checkout_id, session_id, amount, currency, idempotency_key):
        return PaymentIntentResult(
            provider="stripe_test",
            provider_reference=f"pi_{idempotency_key[:16]}",
            status="payment_processing",
            amount=amount,
            currency=currency,
            client_secret="pi_secret_test",
            publishable_key="pk_test_fake",
        )


def test_stripe_payment_handoff_uses_existing_protected_checkout_endpoint(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("PAYMENT_PROVIDER", "stripe_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_fake")
    get_settings.cache_clear()
    monkeypatch.setattr(checkout_service, "get_payment_provider", lambda: _FakeStripeProvider())
    cart_service.add_item("pa-payment", PRODUCT, 1, db_path=seeded_db_path)
    cart_service.set_fulfillment("pa-payment", "pickup", "STR-002", db_path=seeded_db_path)
    review = checkout_service.create_checkout_review("pa-payment", db_path=seeded_db_path)
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-payment",
            customer_id="cust-pa-payment",
            action_type="start_protected_payment_handoff",
            checkout_id=review.checkout_id,
        ),
        db_path=seeded_db_path,
    )

    result = decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-payment",
            customer_id="cust-pa-payment",
            decision="approve",
        ),
        db_path=seeded_db_path,
    )

    assert result.execution_status == "verified"
    assert result.payment_handoff is not None
    assert result.payment_handoff["provider"] == "stripe_test"
    get_settings.cache_clear()


def test_confirmation_records_exclude_sensitive_data(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-sensitive")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-sensitive",
            customer_id="cust-pa-sensitive",
            action_type="create_refund_request",
            order_id=created.order_id,
            reason="Please refund. Card 4242 4242 4242 4242 should not be stored.",
        ),
        db_path=seeded_db_path,
    )
    record = ProtectedActionRepository(seeded_db_path).get_confirmation(proposal.confirmation_id)

    assert record is not None
    serialized = record.model_dump_json()
    assert "4242" not in serialized
    assert "card" not in serialized.lower()


def test_audit_events_are_recorded(seeded_db_path):
    created = create_pickup_order(seeded_db_path, "pa-audit")
    proposal = propose_action(
        ProtectedActionProposalRequest(
            session_id="pa-audit",
            customer_id="cust-pa-audit",
            action_type="cancel_order",
            order_id=created.order_id,
        ),
        db_path=seeded_db_path,
    )
    decide_confirmation(
        ProtectedActionDecisionRequest(
            confirmation_id=proposal.confirmation_id,
            session_id="pa-audit",
            customer_id="cust-pa-audit",
            decision="approve",
        ),
        db_path=seeded_db_path,
    )

    event_types = {event["event_type"] for event in ProtectedActionRepository(seeded_db_path).list_audit_events(proposal.confirmation_id)}
    assert {"proposal_created", "confirmation_approved", "execution_completed", "verification_result"} <= event_types
