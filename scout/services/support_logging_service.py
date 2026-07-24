"""Deterministic support escalation and logging service.

No LLM is given mutation tools. This service performs controlled support-case
creation and audit logging from already-built workflow state/response data.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from scout.repositories.support_repository import SupportRepository

_NEGATIVE_TERMS = {"angry", "upset", "frustrated", "terrible", "awful", "complaint", "missing", "lost", "damaged", "refund", "late", "not delivered"}
_HIGH_RISK_TERMS = {"complaint", "missing", "lost", "marked delivered", "damaged", "fraud", "chargeback", "legal", "unsafe"}
_MEDIUM_RISK_TERMS = {"refund", "return request", "cancel", "late", "not delivered", "wrong item"}
_CASE_ACTIONS = {"missing_package", "complaint_investigation"}


def classify_support_risk(text: str) -> Dict[str, str]:
    lowered = text.lower()
    sentiment = "negative" if any(term in lowered for term in _NEGATIVE_TERMS) else "neutral"
    if any(term in lowered for term in _HIGH_RISK_TERMS):
        risk = "high"
    elif any(term in lowered for term in _MEDIUM_RISK_TERMS):
        risk = "medium"
    else:
        risk = "low"
    return {"sentiment": sentiment, "risk_level": risk}


def should_create_support_case(*, query: str, order_action: Optional[str], risk_level: str) -> bool:
    if order_action in _CASE_ACTIONS:
        return True
    return risk_level == "high" and any(term in query.lower() for term in _HIGH_RISK_TERMS)


def create_support_case_if_needed(
    *,
    session_id: str,
    workflow_id: Optional[str],
    query: str,
    order_id: Optional[str],
    order_action: Optional[str],
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    classification = classify_support_risk(query)
    if not should_create_support_case(query=query, order_action=order_action, risk_level=classification["risk_level"]):
        return None
    category = order_action or "support"
    summary = f"Controlled support case for {category}: {query[:240]}"
    return SupportRepository(db_path).create_case(
        session_id=session_id,
        workflow_id=workflow_id,
        order_id=order_id,
        category=category,
        sentiment=classification["sentiment"],
        risk_level=classification["risk_level"],
        summary=summary,
    )


def record_chat_observability(*, request, response, final_state, db_path: Optional[str] = None) -> None:
    classification = classify_support_risk(request.message)
    case_reference = None
    for entry in final_state.evidence:
        if entry.source == "create_support_case":
            case_reference = entry.data.get("case_reference")
            break
    repo = SupportRepository(db_path)
    repo.record_conversation_log(
        workflow_id=response.workflow_id,
        session_id=response.session_id,
        user_message=request.message,
        assistant_response=response.answer,
        status=response.status,
        message_type=response.message_type,
        case_reference=case_reference,
        sentiment=classification["sentiment"],
        risk_level=classification["risk_level"],
    )
    repo.record_audit(
        workflow_id=response.workflow_id,
        session_id=response.session_id,
        case_reference=case_reference,
        evidence=[entry.model_dump(mode="json") for entry in final_state.evidence],
        verification=final_state.verification_result or {},
    )
