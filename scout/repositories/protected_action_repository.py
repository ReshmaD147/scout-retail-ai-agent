"""SQLite boundary for protected-action confirmation records."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scout.database.connection import connection_scope
from scout.database.initialize import apply_lightweight_migrations
from scout.repositories.models import ProtectedActionConfirmationRecord, ProtectedActionRequestRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProtectedActionRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path

    def _ensure_schema(self) -> None:
        with connection_scope(self._db_path) as connection:
            apply_lightweight_migrations(connection)

    def create_confirmation(
        self,
        *,
        confirmation_id: str,
        workflow_id: str,
        request_id: str,
        session_id: str,
        customer_id: str,
        action_type: str,
        resource_type: str,
        resource_id: str,
        proposal_summary: str,
        customer_effects: List[str],
        financial_effects: List[str],
        eligibility_status: str,
        eligibility_reason_code: str,
        policy_ids: List[str],
        evidence_ids: List[str],
        payload_hash: str,
        idempotency_key: str,
        status: str,
        expires_at: str,
    ) -> ProtectedActionConfirmationRecord:
        self._ensure_schema()
        now = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO protected_action_confirmations (
                    confirmation_id, workflow_id, request_id, session_id, customer_id,
                    action_type, resource_type, resource_id, proposal_summary,
                    customer_effects_json, financial_effects_json, eligibility_status,
                    eligibility_reason_code, policy_ids_json, evidence_ids_json,
                    payload_hash, idempotency_key, status, result_json,
                    created_at, expires_at, consumed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?)
                """,
                (
                    confirmation_id,
                    workflow_id,
                    request_id,
                    session_id,
                    customer_id,
                    action_type,
                    resource_type,
                    resource_id,
                    proposal_summary,
                    json.dumps(customer_effects, sort_keys=True),
                    json.dumps(financial_effects, sort_keys=True),
                    eligibility_status,
                    eligibility_reason_code,
                    json.dumps(policy_ids, sort_keys=True),
                    json.dumps(evidence_ids, sort_keys=True),
                    payload_hash,
                    idempotency_key,
                    status,
                    now,
                    expires_at,
                    now,
                ),
            )
        created = self.get_confirmation(confirmation_id)
        if created is None:
            raise RuntimeError("protected action confirmation was not persisted")
        return created

    def get_confirmation(self, confirmation_id: str) -> Optional[ProtectedActionConfirmationRecord]:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM protected_action_confirmations WHERE confirmation_id = ?",
                (confirmation_id,),
            ).fetchone()
        return ProtectedActionConfirmationRecord.from_row(row) if row else None

    def find_by_idempotency_key(self, idempotency_key: str) -> Optional[ProtectedActionConfirmationRecord]:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM protected_action_confirmations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return ProtectedActionConfirmationRecord.from_row(row) if row else None

    def update_status(
        self,
        confirmation_id: str,
        *,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        consume: bool = False,
    ) -> ProtectedActionConfirmationRecord:
        self._ensure_schema()
        now = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                UPDATE protected_action_confirmations
                SET status = ?,
                    result_json = COALESCE(?, result_json),
                    consumed_at = CASE WHEN ? THEN COALESCE(consumed_at, ?) ELSE consumed_at END,
                    updated_at = ?
                WHERE confirmation_id = ?
                """,
                (
                    status,
                    json.dumps(result, sort_keys=True) if result is not None else None,
                    1 if consume else 0,
                    now,
                    now,
                    confirmation_id,
                ),
            )
        updated = self.get_confirmation(confirmation_id)
        if updated is None:
            raise RuntimeError("protected action confirmation disappeared")
        return updated

    def create_action_request(
        self,
        *,
        request_id: str,
        confirmation_id: str,
        action_type: str,
        order_id: str,
        order_item_id: Optional[str],
        status: str,
        reason: Optional[str],
        payload: Dict[str, Any],
    ) -> ProtectedActionRequestRecord:
        self._ensure_schema()
        now = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO protected_action_requests (
                    request_id, confirmation_id, action_type, order_id, order_item_id,
                    status, reason, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    confirmation_id,
                    action_type,
                    order_id,
                    order_item_id,
                    status,
                    reason,
                    json.dumps(payload, sort_keys=True),
                    now,
                    now,
                ),
            )
        created = self.get_action_request(request_id)
        if created is None:
            raise RuntimeError("protected action request was not persisted")
        return created

    def get_action_request(self, request_id: str) -> Optional[ProtectedActionRequestRecord]:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM protected_action_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return ProtectedActionRequestRecord.from_row(row) if row else None

    def record_audit_event(
        self,
        *,
        confirmation_id: Optional[str],
        workflow_id: Optional[str],
        session_id: str,
        customer_id: Optional[str],
        event_type: str,
        detail: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._ensure_schema()
        event_id = str(uuid.uuid4())
        created_at = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO protected_action_audit_events (
                    event_id, confirmation_id, workflow_id, session_id,
                    customer_id, event_type, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    confirmation_id,
                    workflow_id,
                    session_id,
                    customer_id,
                    event_type,
                    json.dumps(detail, sort_keys=True),
                    created_at,
                ),
            )
        return {"event_id": event_id, "created_at": created_at}

    def list_audit_events(self, confirmation_id: str) -> List[Dict[str, Any]]:
        self._ensure_schema()
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM protected_action_audit_events
                WHERE confirmation_id = ?
                ORDER BY created_at, event_id
                """,
                (confirmation_id,),
            ).fetchall()
        return [dict(row) for row in rows]
