"""Public read-only Policy Q&A Agent.

This agent does not answer from model prose. It retrieves active Markdown
policy sections and proposes structured policy_section claims for the
verification gate. Account verification and order-specific support are
intentionally out of scope for this phase.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

from scout.orchestration.limits import check_step_budget
from scout.orchestration.state import EvidenceEntry, RetailGraphState, ToolCallTrace, ToolHistoryRecord, WorkflowError
from scout.services.policy_retrieval_service import build_policy_vector_index

_PUBLIC_ORDER_SPECIFIC_TERMS = ("my order", "order id", "tracking", "payment status", "cancel my", "return my", "exchange my")


def _is_order_specific(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in _PUBLIC_ORDER_SPECIFIC_TERMS)


def policy_agent_node(state: RetailGraphState) -> Dict[str, Any]:
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    query = (state.intent or {}).get("policy_query") or state.customer_query
    base: Dict[str, Any] = {
        "step_count": state.step_count + 1,
        "active_agent": "policy",
        "current_agent": "policy_agent",
        "next_agent": None,
        "pending_steps": [],
    }

    if _is_order_specific(query):
        message = "I can answer public policy questions here, but I can't handle account- or order-specific support in this policy flow."
        base.update(
            {
                "workflow_status": "failed",
                "final_response": message,
                "errors": [WorkflowError(error_type="validation_error", message=message, agent="policy", step="scope_check")],
                "tool_results": [ToolCallTrace(tool_name="retrieve_policy_sections", status="error", summary="order-specific policy support is out of scope")],
            }
        )
        return base

    results = build_policy_vector_index().search(query, limit=3, effective_on=date.today())
    if not results:
        message = "I couldn't find an active Scout policy section that supports an answer to that question."
        base.update(
            {
                "workflow_status": "failed",
                "final_response": message,
                "policy_results": [],
                "errors": [WorkflowError(error_type="not_found", message=message, agent="policy", step="retrieve_policy_sections")],
                "tool_results": [ToolCallTrace(tool_name="retrieve_policy_sections", status="error", summary="no active policy sections matched")],
            }
        )
        return base

    policy_results = []
    evidence = []
    proposed_claims = list(state.proposed_claims)
    for index, result in enumerate(results, start=1):
        chunk = result.chunk
        evidence_id = f"policy-result-{index}"
        payload = {
            "evidence_id": evidence_id,
            "score": round(result.score, 6),
            "policy_id": chunk.policy_id,
            "policy_file": chunk.policy_file,
            "policy_title": chunk.title,
            "policy_category": chunk.category,
            "policy_version": chunk.version,
            "section_title": chunk.section_title,
            "effective_date": chunk.effective_date.isoformat(),
            "status": chunk.status,
            "text": chunk.text,
        }
        policy_results.append(payload)
        evidence.append(
            EvidenceEntry(
                source="retrieve_policy_sections",
                claim=f"{chunk.policy_file} {chunk.section_title} supports the public policy answer.",
                data=payload,
            )
        )
        proposed_claims.append(
            {
                "type": "policy_section",
                "policy_id": chunk.policy_id,
                "policy_file": chunk.policy_file,
                "policy_category": chunk.category,
                "policy_version": chunk.version,
                "section_title": chunk.section_title,
                "evidence_ids": [evidence_id],
            }
        )

    top = policy_results[0]
    policy_answer = (
        f"According to Scout's {top['policy_title']} policy ({top['policy_version']}), "
        f"{top['text']} Source: {top['policy_file']} — {top['section_title']}."
    )
    answer = f"{state.final_response} {policy_answer}" if state.final_response else policy_answer
    base.update(
        {
            "workflow_status": "in_progress",
            "policy_results": policy_results,
            "evidence": evidence,
            "proposed_claims": proposed_claims,
            "final_response": answer,
            "tool_results": [
                ToolCallTrace(
                    tool_name="retrieve_policy_sections",
                    status="success",
                    summary=f"retrieved {len(policy_results)} active policy section(s)",
                    validated_arguments={"query": query, "limit": 3, "status": "active"},
                )
            ],
            "tool_history": [
                ToolHistoryRecord(
                    agent_name="policy_agent",
                    tool_name="retrieve_policy_sections",
                    validated_arguments={"query": query, "limit": 3, "status": "active"},
                    success=True,
                    evidence_id="policy-result-1",
                    sequence_number=state.tool_call_count + 1,
                )
            ],
        }
    )
    return base
