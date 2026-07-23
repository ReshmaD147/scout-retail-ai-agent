"""Tests for route_from_supervisor.

route_from_supervisor contains no planning logic of its own - these
tests only check that it faithfully translates state.next_agent /
state.workflow_status (already-made decisions) into a destination,
never that it makes any decision itself.
"""

import pytest
from langgraph.graph import END

from scout.orchestration.routing import route_from_supervisor
from scout.orchestration.state import RetailGraphState


def _state(**overrides):
    defaults = {"session_id": "S1", "customer_query": "find shoes"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


@pytest.mark.parametrize(
    "next_agent,expected_node",
    [
        ("recommendation", "recommendation_agent"),
        ("inventory", "inventory_agent"),
        ("order", "order_agent"),
        ("support", "external_offer_agent"),
        ("verification", "verification_agent"),
    ],
)
def test_routes_specialist_decisions_to_the_matching_agent_node(next_agent, expected_node):
    state = _state(next_agent=next_agent, workflow_status="in_progress")
    assert route_from_supervisor(state) == expected_node


@pytest.mark.parametrize(
    "workflow_status",
    ["completed", "failed", "stopped_at_limit", "awaiting_confirmation", "awaiting_clarification"],
)
def test_paused_or_terminal_statuses_always_route_to_end(workflow_status):
    # Even if next_agent still names a specialist from the decision
    # that produced this status, a paused/terminal workflow must stop.
    state = _state(next_agent="recommendation", workflow_status=workflow_status)
    assert route_from_supervisor(state) == END


def test_missing_next_agent_falls_back_to_end():
    state = _state(next_agent=None, workflow_status="in_progress")
    assert route_from_supervisor(state) == END


def test_unrecognized_next_agent_falls_back_to_end():
    state = _state(next_agent="something_unexpected", workflow_status="in_progress")
    assert route_from_supervisor(state) == END
