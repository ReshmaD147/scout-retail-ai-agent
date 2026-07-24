from __future__ import annotations

import json

from scout.api.routes.chat import build_chat_response
from scout.api.schemas.chat import ChatRequest
from scout.orchestration.state import EvidenceEntry, RetailGraphState
from scout.repositories.support_repository import SupportRepository
from scout.services.support_logging_service import classify_support_risk, create_support_case_if_needed, record_chat_observability


def test_sentiment_and_risk_classification_is_deterministic():
    result = classify_support_risk("I am frustrated because my package is marked delivered but missing")
    assert result == {"sentiment": "negative", "risk_level": "high"}
    assert classify_support_risk("What is my order status?") == {"sentiment": "neutral", "risk_level": "low"}


def test_controlled_support_case_creation_returns_reference(seeded_db_path):
    case = create_support_case_if_needed(
        session_id="case-session",
        workflow_id="wf-case",
        query="My package is marked delivered but missing",
        order_id="ORD-1",
        order_action="missing_package",
        db_path=seeded_db_path,
    )
    assert case is not None
    assert case["case_reference"].startswith("SC-")
    assert case["risk_level"] == "high"
    stored = SupportRepository(seeded_db_path).get_case(case["case_reference"])
    assert stored is not None
    assert stored["order_id"] == "ORD-1"


def test_low_risk_question_does_not_create_case(seeded_db_path):
    case = create_support_case_if_needed(
        session_id="case-session",
        workflow_id="wf-case",
        query="Where is my order?",
        order_id="ORD-1",
        order_action="status",
        db_path=seeded_db_path,
    )
    assert case is None


def test_conversation_log_and_audit_records_are_written(seeded_db_path):
    state = RetailGraphState(
        workflow_id="wf-log",
        session_id="log-session",
        customer_query="My package is marked delivered but missing",
        workflow_status="completed",
        final_response="Case created.",
        evidence=[
            EvidenceEntry(
                source="create_support_case",
                claim="Support case SC-20260724-ABCDEF12 was created for controlled follow-up",
                data={"case_reference": "SC-20260724-ABCDEF12"},
            )
        ],
        verification_result={"verified": True, "approved_claims": [{"type": "order_status"}]},
    )
    response = build_chat_response(state, "wf-log")
    request = ChatRequest(session_id="log-session", message="My package is marked delivered but missing")

    record_chat_observability(request=request, response=response, final_state=state, db_path=seeded_db_path)

    repo = SupportRepository(seeded_db_path)
    logs = repo.list_conversation_logs_for_session("log-session")
    audits = repo.list_audits_for_session("log-session")
    assert len(logs) == 1
    assert logs[0]["case_reference"] == "SC-20260724-ABCDEF12"
    assert logs[0]["sentiment"] == "negative"
    assert logs[0]["risk_level"] == "high"
    assert len(audits) == 1
    assert audits[0]["case_reference"] == "SC-20260724-ABCDEF12"
    assert json.loads(audits[0]["verification_json"])["verified"] is True
