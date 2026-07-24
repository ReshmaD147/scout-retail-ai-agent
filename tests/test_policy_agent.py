from __future__ import annotations

from scout.agents.policy_agent import policy_agent_node
from scout.agents.response_verification import response_verification_node, verify_proposed_claims
from scout.api.routes.chat import build_initial_state
from scout.api.schemas.chat import ChatRequest
from scout.orchestration.graph import run_graph
from scout.orchestration.rule_based_policy import RuleBasedSupervisorPolicy
from scout.orchestration.state import RetailGraphState


def test_public_policy_question_routes_to_policy_agent_and_returns_verified_source(monkeypatch, seeded_db_path):
    monkeypatch.setenv("SUPERVISOR_POLICY", "rule_based")
    initial_state = build_initial_state(
        ChatRequest(session_id="policy-session", message="What is the return window?"),
        workflow_id="wf-policy-return-window",
    )

    state = run_graph(policy=RuleBasedSupervisorPolicy(), **initial_state)

    assert state.workflow_status == "completed"
    assert state.intent["request_type"] == "policy"
    assert state.policy_results
    top = state.policy_results[0]
    assert top["policy_file"] == "returns.md"
    assert top["policy_version"] == "1.0.0"
    assert top["section_title"] == "Standard Policy"
    assert "30 days" in top["text"]
    assert state.verification_result["verified"] is True
    assert any(claim["type"] == "policy_section" for claim in state.verification_result["approved_claims"])
    assert "Source: returns.md — Standard Policy" in state.final_response
    assert any(trace.tool_name == "retrieve_policy_sections" and trace.status == "success" for trace in state.tool_results)


def test_policy_agent_retrieves_opened_moisturizer_exception():
    update = policy_agent_node(
        RetailGraphState(
            workflow_id="wf-policy-moisturizer",
            session_id="policy-session",
            customer_query="Can I return opened moisturizer?",
            intent={"request_type": "policy", "policy_query": "Can I return opened moisturizer?"},
        )
    )

    assert update["policy_results"][0]["policy_file"] == "returns.md"
    assert update["policy_results"][0]["section_title"] == "Exceptions"
    assert "opened moisturizer" in update["policy_results"][0]["text"]
    assert update["proposed_claims"][0]["policy_version"] == "1.0.0"


def test_policy_agent_rejects_order_specific_support_scope():
    update = policy_agent_node(
        RetailGraphState(
            workflow_id="wf-policy-order-specific",
            session_id="policy-session",
            customer_query="Can you return my order?",
            intent={"request_type": "policy", "policy_query": "Can you return my order?"},
        )
    )

    assert update["workflow_status"] == "failed"
    assert "order-specific support" in update["final_response"]
    assert update["policy_results"] == [] if "policy_results" in update else True


def test_policy_verification_rejects_wrong_policy_version():
    state = RetailGraphState(
        workflow_id="wf-policy-bad-version",
        session_id="policy-session",
        customer_query="What is the return window?",
        policy_results=[
            {
                "evidence_id": "policy-result-1",
                "policy_id": "POL-RETURNS",
                "policy_file": "returns.md",
                "policy_category": "returns",
                "policy_version": "9.9.9",
                "section_title": "Standard Policy",
                "status": "active",
                "text": "fabricated text",
            }
        ],
        proposed_claims=[
            {
                "type": "policy_section",
                "policy_id": "POL-RETURNS",
                "policy_file": "returns.md",
                "policy_category": "returns",
                "policy_version": "9.9.9",
                "section_title": "Standard Policy",
                "evidence_ids": ["policy-result-1"],
            }
        ],
    )

    report, issues = verify_proposed_claims(state)

    assert report.verified is False
    assert report.rejected_claims
    assert issues
    assert "could not be reverified" in issues[0].message


def test_policy_missing_evidence_produces_safe_failure_at_verification_limit():
    state = RetailGraphState(
        workflow_id="wf-policy-missing-evidence",
        session_id="policy-session",
        customer_query="What is the return window?",
        correction_count=1,
        final_response="Unsupported answer should not survive.",
        proposed_claims=[
            {
                "type": "policy_section",
                "policy_id": "POL-RETURNS",
                "policy_file": "returns.md",
                "policy_category": "returns",
                "policy_version": "1.0.0",
                "section_title": "Standard Policy",
                "evidence_ids": ["missing-policy-result"],
            }
        ],
    )

    update = response_verification_node(state)

    assert update["workflow_status"] == "failed"
    assert update["final_response"] != "Unsupported answer should not survive."
    assert update["verification_result"]["missing_evidence"]
