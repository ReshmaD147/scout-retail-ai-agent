"""Tests for the Supervisor's prompt and state-summary rendering."""

from scout.orchestration.state import EvidenceEntry, PlanStep, RetailGraphState, WorkflowError
from scout.orchestration.supervisor_prompt import (
    SUPERVISOR_SYSTEM_PROMPT,
    build_supervisor_prompt,
    format_state_summary,
)

ALL_DECISIONS = [
    "recommendation",
    "inventory",
    "order",
    "support",
    "verification",
    "clarification",
    "confirmation",
    "finish",
    "safe_failure",
]


def test_system_prompt_documents_every_decision():
    for decision in ALL_DECISIONS:
        assert f'"{decision}"' in SUPERVISOR_SYSTEM_PROMPT


def test_system_prompt_has_no_unfilled_template_placeholders():
    # The system message is static (no per-turn substitution) - it
    # must not contain stray "{...}" that ChatPromptTemplate would try
    # to fill in.
    assert "{" not in SUPERVISOR_SYSTEM_PROMPT
    assert "}" not in SUPERVISOR_SYSTEM_PROMPT


def test_format_state_summary_includes_the_customer_query():
    state = RetailGraphState(session_id="S1", customer_query="find comfortable work shoes under $100")
    summary = format_state_summary(state)
    assert "find comfortable work shoes under $100" in summary


def test_format_state_summary_handles_a_minimal_state_without_crashing():
    state = RetailGraphState(session_id="S1", customer_query="find shoes")
    summary = format_state_summary(state)
    assert "(not yet set)" in summary  # goal
    assert "(none yet)" in summary  # plan
    assert "(none)" in summary  # evidence/errors/completed/pending


def test_format_state_summary_includes_plan_evidence_and_errors():
    state = RetailGraphState(
        session_id="S1",
        customer_query="find shoes",
        goal="find work shoes",
        plan=[PlanStep(step_id="1", description="check selected store", agent="inventory")],
        evidence=[EvidenceEntry(source="check_store_inventory", claim="out of stock at STR-001")],
        errors=[WorkflowError(error_type="not_found", message="No store found")],
    )
    summary = format_state_summary(state)

    assert "check selected store" in summary
    assert "out of stock at STR-001" in summary
    assert "No store found" in summary


def test_build_supervisor_prompt_formats_into_system_and_human_messages():
    state = RetailGraphState(session_id="S1", customer_query="find shoes")
    prompt = build_supervisor_prompt(state)

    messages = prompt.format_messages(state_summary=format_state_summary(state))

    assert len(messages) == 2
    assert messages[0].type == "system"
    assert messages[1].type == "human"
    assert "find shoes" in messages[1].content
