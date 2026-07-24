"""SQLite boundary for support cases, conversation logs, and audit records."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scout.database.connection import connection_scope


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupportRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path

    def create_case(
        self,
        *,
        session_id: str,
        workflow_id: Optional[str],
        order_id: Optional[str],
        category: str,
        sentiment: str,
        risk_level: str,
        summary: str,
    ) -> Dict[str, Any]:
        case_id = str(uuid.uuid4())
        case_reference = f"SC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{case_id[:8].upper()}"
        now = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO support_cases (
                    case_id, case_reference, session_id, workflow_id, order_id,
                    category, sentiment, risk_level, status, summary, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (case_id, case_reference, session_id, workflow_id, order_id, category, sentiment, risk_level, summary, now, now),
            )
        return {
            "case_id": case_id,
            "case_reference": case_reference,
            "session_id": session_id,
            "workflow_id": workflow_id,
            "order_id": order_id,
            "category": category,
            "sentiment": sentiment,
            "risk_level": risk_level,
            "status": "open",
            "summary": summary,
            "created_at": now,
            "updated_at": now,
        }

    def get_case(self, case_reference: str) -> Optional[Dict[str, Any]]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute("SELECT * FROM support_cases WHERE case_reference = ?", (case_reference,)).fetchone()
        return dict(row) if row is not None else None

    def list_cases_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM support_cases WHERE session_id = ? ORDER BY created_at, case_reference",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_conversation_log(
        self,
        *,
        workflow_id: str,
        session_id: str,
        user_message: str,
        assistant_response: Optional[str],
        status: str,
        message_type: Optional[str],
        case_reference: Optional[str],
        sentiment: str,
        risk_level: str,
    ) -> Dict[str, Any]:
        log_id = str(uuid.uuid4())
        created_at = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO conversation_logs (
                    log_id, workflow_id, session_id, user_message, assistant_response,
                    status, message_type, case_reference, sentiment, risk_level, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (log_id, workflow_id, session_id, user_message, assistant_response, status, message_type, case_reference, sentiment, risk_level, created_at),
            )
        return {"log_id": log_id, "workflow_id": workflow_id, "session_id": session_id, "created_at": created_at}

    def list_conversation_logs_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_logs WHERE session_id = ? ORDER BY created_at, log_id",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_audit(
        self,
        *,
        workflow_id: str,
        session_id: str,
        case_reference: Optional[str],
        evidence: List[Dict[str, Any]],
        verification: Dict[str, Any],
    ) -> Dict[str, Any]:
        audit_id = str(uuid.uuid4())
        created_at = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO support_audit_records (
                    audit_id, workflow_id, session_id, case_reference,
                    evidence_json, verification_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    workflow_id,
                    session_id,
                    case_reference,
                    json.dumps(evidence, sort_keys=True),
                    json.dumps(verification, sort_keys=True),
                    created_at,
                ),
            )
        return {"audit_id": audit_id, "workflow_id": workflow_id, "session_id": session_id, "created_at": created_at}

    def list_audits_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM support_audit_records WHERE session_id = ? ORDER BY created_at, audit_id",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]
