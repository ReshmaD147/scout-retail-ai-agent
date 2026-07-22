"""Validation tests for scout.orchestration.state.RetailGraphState.

No LangGraph graph is built or run here (Step 8 is state only) - these
tests only construct the Pydantic model directly and check: sensible
defaults, that invalid values are rejected, that the reducer metadata
each field needs is actually wired up, that the reducer functions
behave as claimed for the concrete types used here, and that a fully
populated state is JSON-serializable (a state full of hidden,
unserializable objects would be a real problem for logging/observability).
"""

import operator
import typing

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from scout.mcp.schemas import ProductSummary
from scout.orchestration.state import (
    EvidenceEntry,
    PendingConfirmation,
    PlanStep,
    RetailGraphState,
    ToolCallTrace,
    WorkflowError,
)


def _minimal_state(**overrides):
    defaults = {"session_id": "SESSION-1", "customer_query": "find comfortable work shoes under $100"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_minimal_construction_applies_sensible_defaults():
    state = _minimal_state()

    assert state.messages == []
    assert state.intent is None
    assert state.goal is None
    assert state.plan == []
    assert state.completed_steps == []
    assert state.pending_steps == []
    assert state.active_agent is None
    assert state.next_agent is None
    assert state.product_candidates == []
    assert state.inventory_results == []
    assert state.order_context is None
    assert state.policy_results == []
    assert state.tool_results == []
    assert state.evidence == []
    assert state.errors == []
    assert state.retry_count == 0
    assert state.step_count == 0
    assert state.pending_confirmation is None
    assert state.workflow_status == "in_progress"
    assert state.final_response is None


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


def test_session_id_is_required():
    with pytest.raises(ValidationError):
        RetailGraphState(customer_query="find shoes")


def test_session_id_rejects_empty_string():
    with pytest.raises(ValidationError):
        _minimal_state(session_id="")


def test_customer_query_is_required():
    with pytest.raises(ValidationError):
        RetailGraphState(session_id="SESSION-1")


def test_customer_query_rejects_empty_string():
    with pytest.raises(ValidationError):
        _minimal_state(customer_query="")


# ---------------------------------------------------------------------------
# Constrained scalar fields
# ---------------------------------------------------------------------------


def test_retry_count_rejects_negative():
    with pytest.raises(ValidationError):
        _minimal_state(retry_count=-1)


def test_step_count_rejects_negative():
    with pytest.raises(ValidationError):
        _minimal_state(step_count=-1)


def test_workflow_status_accepts_a_valid_value():
    state = _minimal_state(workflow_status="awaiting_confirmation")
    assert state.workflow_status == "awaiting_confirmation"


def test_workflow_status_rejects_an_unknown_value():
    with pytest.raises(ValidationError):
        _minimal_state(workflow_status="bogus_status")


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


def test_plan_step_accepts_valid_values():
    step = PlanStep(step_id="1", description="check selected store inventory", agent="inventory")
    assert step.status == "pending"


def test_plan_step_rejects_unknown_status():
    with pytest.raises(ValidationError):
        PlanStep(step_id="1", description="do something", agent="inventory", status="bogus")


def test_plan_step_rejects_empty_description():
    with pytest.raises(ValidationError):
        PlanStep(step_id="1", description="", agent="inventory")


def test_evidence_entry_defaults_data_to_empty_dict():
    entry = EvidenceEntry(source="check_store_inventory", claim="FTW-004 is in stock at STR-002")
    assert entry.data == {}


def test_evidence_entry_rejects_empty_claim():
    with pytest.raises(ValidationError):
        EvidenceEntry(source="check_store_inventory", claim="")


def test_tool_call_trace_accepts_success_and_error():
    ok = ToolCallTrace(tool_name="check_store_inventory", status="success", summary="in stock")
    failed = ToolCallTrace(tool_name="check_store_inventory", status="error", summary="store not found")
    assert ok.status == "success"
    assert failed.status == "error"


def test_tool_call_trace_rejects_unknown_status():
    with pytest.raises(ValidationError):
        ToolCallTrace(tool_name="check_store_inventory", status="pending", summary="...")


def test_workflow_error_accepts_a_known_category():
    error = WorkflowError(error_type="not_found", message="No product found")
    assert error.agent is None
    assert error.step is None


def test_workflow_error_rejects_an_unknown_category():
    with pytest.raises(ValidationError):
        WorkflowError(error_type="something_made_up", message="oops")


def test_pending_confirmation_accepts_a_known_action_type():
    confirmation = PendingConfirmation(action_type="refund", description="Refund order ORD-1 for $49.99")
    assert confirmation.target_id is None
    assert confirmation.requested_at is None


def test_pending_confirmation_rejects_an_unknown_action_type():
    with pytest.raises(ValidationError):
        PendingConfirmation(action_type="do_something_dangerous", description="...")


# ---------------------------------------------------------------------------
# product_candidates reuses the real ProductSummary schema
# ---------------------------------------------------------------------------


def _product_summary_kwargs(**overrides):
    defaults = {
        "product_id": "FTW-004",
        "name": "ComfortPro Shift Support",
        "brand": "ComfortPro",
        "category": "Footwear",
        "subcategory": "Work Shoes",
        "price": 79.99,
        "rating": 4.5,
        "review_count": 120,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def test_product_candidates_accepts_product_summary_instances():
    state = _minimal_state(product_candidates=[ProductSummary(**_product_summary_kwargs())])
    assert state.product_candidates[0].product_id == "FTW-004"


def test_product_candidates_coerces_matching_dicts():
    state = _minimal_state(product_candidates=[_product_summary_kwargs()])
    assert isinstance(state.product_candidates[0], ProductSummary)


def test_product_candidates_rejects_a_dict_missing_required_fields():
    incomplete = _product_summary_kwargs()
    del incomplete["price"]
    with pytest.raises(ValidationError):
        _minimal_state(product_candidates=[incomplete])


# ---------------------------------------------------------------------------
# Reducer wiring - which fields are Annotated with a reducer, and which
# are deliberately plain "replace" fields.
# ---------------------------------------------------------------------------


def _annotation_metadata(field_name: str):
    hints = typing.get_type_hints(RetailGraphState, include_extras=True)
    return typing.get_args(hints[field_name])[1:]


def test_messages_uses_the_add_messages_reducer():
    metadata = _annotation_metadata("messages")
    assert add_messages in metadata


def test_completed_steps_uses_operator_add():
    assert operator.add in _annotation_metadata("completed_steps")


def test_tool_results_uses_operator_add():
    assert operator.add in _annotation_metadata("tool_results")


def test_evidence_uses_operator_add():
    assert operator.add in _annotation_metadata("evidence")


def test_errors_uses_operator_add():
    assert operator.add in _annotation_metadata("errors")


@pytest.mark.parametrize(
    "field_name",
    [
        "pending_steps",
        "product_candidates",
        "inventory_results",
        "policy_results",
        "plan",
    ],
)
def test_replace_fields_have_no_reducer_metadata(field_name):
    # These fields must be overwritten wholesale by whichever node last
    # recomputed them (see module docstring) - if one of these ever
    # picked up Annotated reducer metadata, updates would silently
    # accumulate stale/invalidated entries instead of replacing them.
    assert _annotation_metadata(field_name) == ()


# ---------------------------------------------------------------------------
# The reducers actually behave the way the docstring claims, for the
# concrete types used in this state.
# ---------------------------------------------------------------------------


def test_add_messages_reducer_appends_new_messages_by_id():
    existing = [HumanMessage(content="find shoes", id="1")]
    incoming = [AIMessage(content="looking now", id="2")]

    merged = add_messages(existing, incoming)

    assert [m.id for m in merged] == ["1", "2"]


def test_add_messages_reducer_updates_a_message_with_a_repeated_id():
    existing = [HumanMessage(content="find shoes", id="1")]
    incoming = [HumanMessage(content="find shoes under $100", id="1")]

    merged = add_messages(existing, incoming)

    assert len(merged) == 1
    assert merged[0].content == "find shoes under $100"


def test_operator_add_concatenates_completed_steps():
    assert operator.add(["check_store"], ["check_nearby"]) == ["check_store", "check_nearby"]


# ---------------------------------------------------------------------------
# Serializability - nothing in a fully populated state should be opaque
# to logging/observability.
# ---------------------------------------------------------------------------


def test_a_fully_populated_state_is_json_serializable():
    state = RetailGraphState(
        session_id="SESSION-1",
        customer_query="find comfortable work shoes under $100",
        messages=[HumanMessage(content="find comfortable work shoes under $100", id="1")],
        intent={"category": "Footwear", "max_price": 100},
        goal="find and confirm fulfillment for work shoes under $100",
        plan=[PlanStep(step_id="1", description="check selected store", agent="inventory")],
        completed_steps=["1"],
        pending_steps=["2"],
        active_agent="inventory",
        next_agent="recommendation",
        product_candidates=[ProductSummary(**_product_summary_kwargs())],
        inventory_results=[{"store_id": "STR-001", "sellable_quantity": 0}],
        order_context={"order_id": "ORD-1"},
        policy_results=[{"policy": "returns", "window_days": 30}],
        tool_results=[ToolCallTrace(tool_name="check_store_inventory", status="success", summary="checked")],
        evidence=[EvidenceEntry(source="check_store_inventory", claim="out of stock at STR-001")],
        errors=[WorkflowError(error_type="not_found", message="No store found")],
        retry_count=1,
        step_count=2,
        pending_confirmation=PendingConfirmation(action_type="refund", description="Refund ORD-1"),
        workflow_status="awaiting_confirmation",
        final_response=None,
    )

    payload = state.model_dump_json()

    assert "SESSION-1" in payload
    assert "awaiting_confirmation" in payload
