from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from scout.orchestration.state import RetailGraphState
from scout.repositories.memory_repository import MemoryRepository
from scout.services import cart_service, memory_service, saved_product_service
from scout.services.memory_service import MemoryServiceError, PreferenceWrite


def test_working_memory_lifecycle_expires_after_completion(seeded_db_path):
    state = RetailGraphState(
        workflow_id="wf-memory-1",
        session_id="session-memory-1",
        customer_query="Work shoes under $100",
        workflow_status="completed",
        final_response="Done",
        retry_count=1,
        step_count=2,
        verification_result={"verified": True},
    )

    record = memory_service.save_working_memory_from_state(state, db_path=seeded_db_path)

    assert record is not None
    assert record.status == "completed"
    assert record.current_query == "Work shoes under $100"
    assert record.retry_state["retry_count"] == 1
    assert record.expires_at is not None


def test_session_memory_is_isolated_by_session(seeded_db_path):
    memory_service.record_viewed_product("session-a", "FTW-004", db_path=seeded_db_path)
    memory_service.record_viewed_product("session-b", "BAG-001", db_path=seeded_db_path)

    repo = MemoryRepository(seeded_db_path)
    assert repo.get_session_memory("session-a").viewed_products == ["FTW-004"]
    assert repo.get_session_memory("session-b").viewed_products == ["BAG-001"]


def test_viewed_and_rejected_products_are_references_only(seeded_db_path):
    memory_service.record_viewed_product("session-products", "FTW-004", db_path=seeded_db_path)
    record = memory_service.record_rejected_product("session-products", "BAG-001", db_path=seeded_db_path)

    assert record.viewed_products == ["FTW-004"]
    assert record.rejected_products == ["BAG-001"]


def test_budget_and_selected_store_context_from_state(seeded_db_path):
    state = RetailGraphState(
        workflow_id="wf-session-context",
        session_id="session-context",
        user_id="customer-context",
        customer_query="Shoes under $80 at Maple Grove",
        intent={"max_price": 80, "selected_store_id": "STR-002", "fulfillment_preference": "pickup"},
    )

    record = memory_service.update_session_from_state(state, db_path=seeded_db_path)

    assert record.current_budget == 80
    assert record.selected_store_id == "STR-002"
    assert record.fulfillment_preference == "pickup"


def test_durable_preference_create_update_delete_and_clear(seeded_db_path):
    first = memory_service.create_or_update_preference(
        PreferenceWrite(customer_id="cust-pref", type="preferred_brand", value="ComfortPro", confidence=1.0, source="explicit"),
        db_path=seeded_db_path,
    )
    updated = memory_service.create_or_update_preference(
        PreferenceWrite(customer_id="cust-pref", type="preferred_brand", value="ComfortPro", confidence=0.8, source="customer_confirmed"),
        db_path=seeded_db_path,
    )

    assert first.preference_id == updated.preference_id
    assert updated.confidence == 0.8
    assert updated.source == "customer_confirmed"
    memory_service.delete_preference("cust-pref", updated.preference_id, db_path=seeded_db_path)
    assert memory_service.list_preferences("cust-pref", db_path=seeded_db_path) == []

    memory_service.create_or_update_preference(
        PreferenceWrite(customer_id="cust-pref", type="width", value="wide", confidence=1.0),
        db_path=seeded_db_path,
    )
    assert memory_service.clear_preferences("cust-pref", db_path=seeded_db_path) == 1
    assert memory_service.list_preferences("cust-pref", db_path=seeded_db_path) == []


def test_memory_disabled_blocks_preferences_and_session_update(seeded_db_path):
    memory_service.set_memory_enabled("cust-disabled", False, db_path=seeded_db_path)

    with pytest.raises(MemoryServiceError):
        memory_service.create_or_update_preference(
            PreferenceWrite(customer_id="cust-disabled", type="preferred_brand", value="ComfortPro"),
            db_path=seeded_db_path,
        )
    state = RetailGraphState(session_id="session-disabled", user_id="cust-disabled", customer_query="shoes")
    assert memory_service.update_session_from_state(state, db_path=seeded_db_path) is None


def test_confidence_source_and_expired_preferences_ignored(seeded_db_path):
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    memory_service.create_or_update_preference(
        PreferenceWrite(
            customer_id="cust-expired",
            type="preferred_brand",
            value="ComfortPro",
            confidence=0.4,
            source="inferred",
            expires_at=expired,
        ),
        db_path=seeded_db_path,
    )

    assert memory_service.list_preferences("cust-expired", db_path=seeded_db_path) == []
    stored = MemoryRepository(seeded_db_path).list_preferences("cust-expired", include_expired=True)[0]
    assert stored.confidence == 0.4
    assert stored.source == "inferred"


def test_current_request_overrides_memory_budget_and_store(seeded_db_path):
    memory_service.record_viewed_product("session-override", "FTW-004", db_path=seeded_db_path)
    state = RetailGraphState(
        session_id="session-override",
        customer_query="Shoes under $50",
        intent={"max_price": 50, "selected_store_id": "STR-003"},
    )

    record = memory_service.update_session_from_state(state, db_path=seeded_db_path)

    assert record.current_budget == 50
    assert record.selected_store_id == "STR-003"


def test_memory_cannot_override_cart_or_saved_authority(seeded_db_path):
    cart_service.add_item("memory-cart", "FTW-004", 1, db_path=seeded_db_path)
    saved_product_service.save_product("memory-cart", "BAG-001", db_path=seeded_db_path)
    memory_service.clear_session_context("memory-cart", db_path=seeded_db_path)
    memory_service.clear_preferences("memory-cart", db_path=seeded_db_path)

    assert cart_service.get_cart_view("memory-cart", db_path=seeded_db_path).items[0].product_id == "FTW-004"
    assert saved_product_service.list_saved_product_ids("memory-cart", db_path=seeded_db_path) == ["BAG-001"]


def test_cross_customer_isolation_and_sensitive_values_rejected(seeded_db_path):
    pref = memory_service.create_or_update_preference(
        PreferenceWrite(customer_id="cust-a", type="preferred_brand", value="ComfortPro"),
        db_path=seeded_db_path,
    )

    assert memory_service.list_preferences("cust-b", db_path=seeded_db_path) == []
    with pytest.raises(MemoryServiceError):
        memory_service.delete_preference("cust-b", pref.preference_id, db_path=seeded_db_path)
    with pytest.raises(ValidationError):
        PreferenceWrite(customer_id="cust-a", type="preferred_brand", value="card 4242 4242 4242 4242")


def test_ranking_uses_preference_as_bounded_signal_only(seeded_db_path):
    memory_service.create_or_update_preference(
        PreferenceWrite(customer_id="cust-rank", type="preferred_brand", value="ComfortPro", confidence=1.0),
        db_path=seeded_db_path,
    )

    assert memory_service.bounded_preference_score("FTW-004", "cust-rank", db_path=seeded_db_path) <= 0.1
    assert memory_service.bounded_preference_score("DOES-NOT-EXIST", "cust-rank", db_path=seeded_db_path) == 0.0


def test_memory_failure_does_not_break_request(monkeypatch):
    state = RetailGraphState(session_id="session-failure", customer_query="shoes")
    monkeypatch.setattr(memory_service.MemoryRepository, "save_workflow_memory", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    assert memory_service.save_working_memory_from_state(state) is None
