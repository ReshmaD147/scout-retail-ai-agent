"""SQLite boundary for Scout working, session, and preference memory."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scout.database.connection import connection_scope
from scout.database.initialize import apply_lightweight_migrations
from scout.repositories.models import DurablePreferenceRecord, SessionMemoryRecord, WorkflowMemoryRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path

    def _ensure_schema(self) -> None:
        with connection_scope(self._db_path) as connection:
            apply_lightweight_migrations(connection)

    def save_workflow_memory(
        self,
        *,
        workflow_id: str,
        session_id: str,
        customer_id: Optional[str],
        current_query: str,
        structured_intent: Optional[Dict[str, Any]],
        current_plan: List[Dict[str, Any]],
        completed_steps: List[str],
        remaining_steps: List[str],
        tool_result_refs: List[str],
        evidence_ids: List[str],
        selected_products: List[str],
        errors: List[Dict[str, Any]],
        retry_state: Dict[str, Any],
        verification_status: Optional[str],
        status: str,
        expires_at: Optional[str],
    ) -> WorkflowMemoryRecord:
        self._ensure_schema()
        now = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO workflow_memory (
                    workflow_id, session_id, customer_id, current_query,
                    structured_intent_json, current_plan_json, completed_steps_json,
                    remaining_steps_json, tool_result_refs_json, evidence_ids_json,
                    selected_products_json, errors_json, retry_state_json,
                    verification_status, status, created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (workflow_id) DO UPDATE SET
                    current_query = excluded.current_query,
                    structured_intent_json = excluded.structured_intent_json,
                    current_plan_json = excluded.current_plan_json,
                    completed_steps_json = excluded.completed_steps_json,
                    remaining_steps_json = excluded.remaining_steps_json,
                    tool_result_refs_json = excluded.tool_result_refs_json,
                    evidence_ids_json = excluded.evidence_ids_json,
                    selected_products_json = excluded.selected_products_json,
                    errors_json = excluded.errors_json,
                    retry_state_json = excluded.retry_state_json,
                    verification_status = excluded.verification_status,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (
                    workflow_id,
                    session_id,
                    customer_id,
                    current_query,
                    json.dumps(structured_intent, sort_keys=True) if structured_intent is not None else None,
                    json.dumps(current_plan, sort_keys=True),
                    json.dumps(completed_steps, sort_keys=True),
                    json.dumps(remaining_steps, sort_keys=True),
                    json.dumps(tool_result_refs, sort_keys=True),
                    json.dumps(evidence_ids, sort_keys=True),
                    json.dumps(selected_products, sort_keys=True),
                    json.dumps(errors, sort_keys=True),
                    json.dumps(retry_state, sort_keys=True),
                    verification_status,
                    status,
                    now,
                    now,
                    expires_at,
                ),
            )
        record = self.get_workflow_memory(workflow_id)
        if record is None:
            raise RuntimeError("workflow memory was not persisted")
        return record

    def get_workflow_memory(self, workflow_id: str) -> Optional[WorkflowMemoryRecord]:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            row = connection.execute("SELECT * FROM workflow_memory WHERE workflow_id = ?", (workflow_id,)).fetchone()
        return WorkflowMemoryRecord.from_row(row) if row else None

    def complete_workflow_memory(self, workflow_id: str, expires_at: Optional[str]) -> None:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                "UPDATE workflow_memory SET status = 'completed', updated_at = ?, expires_at = ? WHERE workflow_id = ?",
                (_now(), expires_at, workflow_id),
            )

    def upsert_session_memory(self, session_id: str, customer_id: Optional[str], updates: Dict[str, Any], expires_at: str) -> SessionMemoryRecord:
        self._ensure_schema()
        existing = self.get_session_memory(session_id, include_expired=True)
        base = {
            "viewed_products": [],
            "rejected_products": [],
            "recommended_products": [],
            "current_budget": None,
            "selected_store_id": None,
            "fulfillment_preference": None,
            "comparison_set": [],
            "current_policy_topic": None,
            "authorized_order_ref": None,
            "memory_disabled": False,
        }
        if existing is not None:
            base.update(existing.model_dump())
        base.update({key: value for key, value in updates.items() if value is not None})
        now = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO session_memory (
                    session_id, customer_id, viewed_products_json, rejected_products_json,
                    recommended_products_json, current_budget, selected_store_id,
                    fulfillment_preference, comparison_set_json, current_policy_topic,
                    authorized_order_ref, memory_disabled, created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (session_id) DO UPDATE SET
                    customer_id = excluded.customer_id,
                    viewed_products_json = excluded.viewed_products_json,
                    rejected_products_json = excluded.rejected_products_json,
                    recommended_products_json = excluded.recommended_products_json,
                    current_budget = excluded.current_budget,
                    selected_store_id = excluded.selected_store_id,
                    fulfillment_preference = excluded.fulfillment_preference,
                    comparison_set_json = excluded.comparison_set_json,
                    current_policy_topic = excluded.current_policy_topic,
                    authorized_order_ref = excluded.authorized_order_ref,
                    memory_disabled = excluded.memory_disabled,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (
                    session_id,
                    customer_id,
                    json.dumps(base["viewed_products"], sort_keys=True),
                    json.dumps(base["rejected_products"], sort_keys=True),
                    json.dumps(base["recommended_products"], sort_keys=True),
                    base["current_budget"],
                    base["selected_store_id"],
                    base["fulfillment_preference"],
                    json.dumps(base["comparison_set"], sort_keys=True),
                    base["current_policy_topic"],
                    base["authorized_order_ref"],
                    1 if base["memory_disabled"] else 0,
                    existing.created_at if existing else now,
                    now,
                    expires_at,
                ),
            )
        record = self.get_session_memory(session_id, include_expired=True)
        if record is None:
            raise RuntimeError("session memory was not persisted")
        return record

    def get_session_memory(self, session_id: str, include_expired: bool = False) -> Optional[SessionMemoryRecord]:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            row = connection.execute("SELECT * FROM session_memory WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        record = SessionMemoryRecord.from_row(row)
        if include_expired:
            return record
        if datetime.fromisoformat(record.expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            return None
        return None if record.memory_disabled else record

    def clear_session_memory(self, session_id: str) -> None:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            connection.execute("DELETE FROM session_memory WHERE session_id = ?", (session_id,))

    def set_memory_enabled(self, customer_id: str, enabled: bool) -> None:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO memory_controls (customer_id, memory_enabled, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT (customer_id) DO UPDATE SET
                    memory_enabled = excluded.memory_enabled,
                    updated_at = excluded.updated_at
                """,
                (customer_id, 1 if enabled else 0, _now()),
            )

    def memory_enabled(self, customer_id: Optional[str], default: bool) -> bool:
        if not customer_id:
            return default
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            row = connection.execute("SELECT memory_enabled FROM memory_controls WHERE customer_id = ?", (customer_id,)).fetchone()
        return default if row is None else bool(row["memory_enabled"])

    def upsert_preference(
        self,
        *,
        customer_id: str,
        preference_type: str,
        value: str,
        confidence: float,
        source: str,
        status: str,
        expires_at: Optional[str],
    ) -> DurablePreferenceRecord:
        self._ensure_schema()
        now = _now()
        preference_id = str(uuid.uuid4())
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO durable_preferences (
                    preference_id, customer_id, type, value, confidence, source,
                    status, created_at, updated_at, last_confirmed_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (customer_id, type, value) WHERE status = 'active' DO UPDATE SET
                    confidence = excluded.confidence,
                    source = excluded.source,
                    updated_at = excluded.updated_at,
                    last_confirmed_at = excluded.last_confirmed_at,
                    expires_at = excluded.expires_at
                """,
                (preference_id, customer_id, preference_type, value, confidence, source, status, now, now, now, expires_at),
            )
        return self.list_preferences(customer_id, include_expired=True)[0] if False else self._get_active_preference(customer_id, preference_type, value)

    def _get_active_preference(self, customer_id: str, preference_type: str, value: str) -> DurablePreferenceRecord:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM durable_preferences WHERE customer_id = ? AND type = ? AND value = ? AND status = 'active'",
                (customer_id, preference_type, value),
            ).fetchone()
        if row is None:
            raise RuntimeError("preference was not persisted")
        return DurablePreferenceRecord.from_row(row)

    def list_preferences(self, customer_id: str, include_expired: bool = False) -> List[DurablePreferenceRecord]:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM durable_preferences WHERE customer_id = ? AND status = 'active' ORDER BY updated_at DESC, preference_id",
                (customer_id,),
            ).fetchall()
        records = [DurablePreferenceRecord.from_row(row) for row in rows]
        if include_expired:
            return records
        now = datetime.now(timezone.utc)
        return [
            record for record in records
            if record.expires_at is None or datetime.fromisoformat(record.expires_at.replace("Z", "+00:00")) > now
        ]

    def delete_preference(self, customer_id: str, preference_id: str) -> bool:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            updated = connection.execute(
                "UPDATE durable_preferences SET status = 'deleted', updated_at = ? WHERE customer_id = ? AND preference_id = ?",
                (_now(), customer_id, preference_id),
            )
        return updated.rowcount == 1

    def clear_preferences(self, customer_id: str) -> int:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            updated = connection.execute(
                "UPDATE durable_preferences SET status = 'deleted', updated_at = ? WHERE customer_id = ? AND status = 'active'",
                (_now(), customer_id),
            )
        return updated.rowcount
