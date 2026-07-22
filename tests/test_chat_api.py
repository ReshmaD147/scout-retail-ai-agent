"""Tests for POST /chat (Step 12).

Two kinds of test live here, matching the prompt's own split:

- Focused, isolated API-layer tests use `override_graph` to replace the
  compiled LangGraph dependency (`scout.api.dependencies.get_compiled_graph`)
  with a tiny stub whose `.invoke(...)` is scripted for one scenario -
  a slow call, a raised `sqlite3.Error`, a raised generic exception. No
  real database, no real graph execution: these only exercise
  `scout/api/routes/chat.py`'s own validation, timeout, error-mapping,
  and response-building logic.
- Integration tests call the real, compiled graph against a real
  seeded temporary database (the `client`/`seeded_db_path` fixtures
  from tests/conftest.py, the same pattern tests/test_retail_graph.py
  uses) - these confirm the whole Client -> ChatRequest ->
  RetailGraphState -> graph -> ChatResponse path produces the exact,
  correct, grounded answer, not just a plausible-looking shape.

Scenario -> test name, matching the 20 scenarios the Step 12 prompt
lists explicitly:
    1.  test_valid_request_returns_200
    2.  test_response_contains_a_workflow_id
    3.  test_session_id_is_preserved
    4.  test_verified_products_are_returned
    5.  test_strict_budget_remains_enforced
    6.  test_pickup_request_returns_grounded_fulfillment_info
    7.  test_vague_request_returns_clarification_required
    8.  test_no_match_request_returns_no_results
    9.  test_empty_message_returns_422
    10. test_whitespace_only_message_returns_422
    11. test_missing_session_id_returns_422
    12. test_excessively_long_message_is_rejected
    13. test_unexpected_fields_are_rejected
    14. test_client_cannot_control_internal_graph_state
    15. test_workflow_timeout_returns_a_safe_error
    16. test_known_tool_failure_returns_a_structured_safe_response
    17. test_unexpected_graph_errors_hide_internal_details
    18. test_response_contains_no_chain_of_thought_prompts_sql_or_secrets
    19. test_health_still_passes
    20. "all existing Steps 1-11 tests still pass" is not a fact this
        file can assert about itself - it is confirmed by running the
        *whole* suite (`pytest`) after adding this file, since nothing
        here modifies any existing test or source file's behavior.
"""

import sqlite3
import time
import uuid

import pytest

from scout.api.dependencies import get_compiled_graph
from scout.config import get_settings
from scout.database.connection import connection_scope

ACCEPTANCE_QUERY = "Find comfortable work shoes under $100 that I can pick up today near Maple Grove."


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    """Every test in this file runs against a real, freshly seeded
    temporary database - never the development database - even the
    tests that never touch it because their graph is stubbed out."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _StubGraph:
    """A minimal stand-in for the compiled LangGraph app.

    Lets a test control exactly what one `/chat` request's
    `compiled_graph.invoke(...)` call does - return instantly, sleep
    past the timeout, or raise - without running any real node, tool,
    or database call.
    """

    def __init__(self, invoke_fn):
        self._invoke_fn = invoke_fn

    def invoke(self, state, config=None):
        return self._invoke_fn(state)


@pytest.fixture()
def override_graph(client):
    """Replace the `get_compiled_graph` dependency for one test.

    This is the seam scout/api/dependencies.py's docstring describes:
    `app.dependency_overrides[get_compiled_graph] = ...` swaps the
    route's graph out entirely, with no risk of leaking into another
    test, since it is always cleared afterward.
    """

    def _apply(invoke_fn) -> None:
        client.app.dependency_overrides[get_compiled_graph] = lambda: _StubGraph(invoke_fn)

    yield _apply
    client.app.dependency_overrides.pop(get_compiled_graph, None)


# ---------------------------------------------------------------------------
# 1-6: a completed workflow, against the real graph and a real database
# ---------------------------------------------------------------------------


def test_valid_request_returns_200(client):
    response = client.post("/chat", json={"session_id": "s-200", "message": ACCEPTANCE_QUERY})
    assert response.status_code == 200


def test_response_contains_a_workflow_id(client):
    response = client.post("/chat", json={"session_id": "s-wfid", "message": ACCEPTANCE_QUERY})
    workflow_id = response.json()["workflow_id"]
    assert workflow_id
    # Must be a real, server-generated UUID - not an echo of anything
    # the client sent (ChatRequest has no field the client could use
    # to influence it).
    uuid.UUID(workflow_id)


def test_session_id_is_preserved(client):
    response = client.post(
        "/chat", json={"session_id": "demo-session-001", "message": ACCEPTANCE_QUERY}
    )
    assert response.json()["session_id"] == "demo-session-001"


def test_verified_products_are_returned(client):
    response = client.post("/chat", json={"session_id": "s-products", "message": ACCEPTANCE_QUERY})
    body = response.json()
    assert body["status"] == "completed"
    assert [p["product_id"] for p in body["products"]] == ["FTW-004"]
    assert body["products"][0]["name"] == "ComfortPro Shift Support"


def test_strict_budget_remains_enforced(client):
    response = client.post("/chat", json={"session_id": "s-budget", "message": ACCEPTANCE_QUERY})
    body = response.json()
    assert body["products"], "expected at least one verified product"
    assert all(product["price"] <= 100 for product in body["products"])


def test_pickup_request_returns_grounded_fulfillment_info(client):
    response = client.post(
        "/chat", json={"session_id": "s-fulfillment", "message": ACCEPTANCE_QUERY}
    )
    body = response.json()
    channels = {option["channel"] for option in body["fulfillment_options"]}
    assert "nearby_store" in channels

    nearby = next(option for option in body["fulfillment_options"] if option["channel"] == "nearby_store")
    assert "Plymouth" in nearby["store_name"]
    assert nearby["sellable_quantity"] > 0
    assert nearby["distance_miles"] is not None




def test_internal_inventory_exhaustion_returns_external_offers(client):
    with connection_scope() as connection:
        connection.execute(
            "UPDATE inventory SET quantity_available = 0, quantity_reserved = 0"
        )

    response = client.post(
        "/chat",
        json={"session_id": "s-external", "message": ACCEPTANCE_QUERY},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "completed"
    assert body["products"] == []
    assert body["fulfillment_options"] == []
    assert body["external_offers"]
    assert all(offer["match_type"] == "similar" for offer in body["external_offers"])
    assert all("merchant_url" not in offer for offer in body["external_offers"])

# ---------------------------------------------------------------------------
# 7-8: normal business outcomes that are not a completed recommendation
# ---------------------------------------------------------------------------


def test_vague_request_returns_clarification_required(client):
    response = client.post("/chat", json={"session_id": "s-vague", "message": "hi there"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "clarification_required"
    assert body["answer"]
    assert body["products"] == []


def test_no_match_request_returns_no_results(client):
    response = client.post(
        "/chat",
        json={
            "session_id": "s-nomatch",
            "message": "Find work shoes under $1 that I can pick up today near Maple Grove.",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "no_results"
    assert body["products"] == []


# ---------------------------------------------------------------------------
# 9-14: request validation
# ---------------------------------------------------------------------------


def test_empty_message_returns_422(client):
    response = client.post("/chat", json={"session_id": "s1", "message": ""})
    assert response.status_code == 422


def test_whitespace_only_message_returns_422(client):
    response = client.post("/chat", json={"session_id": "s1", "message": "   "})
    assert response.status_code == 422


def test_missing_session_id_returns_422(client):
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 422


def test_excessively_long_message_is_rejected(client):
    response = client.post("/chat", json={"session_id": "s1", "message": "x" * 2001})
    assert response.status_code == 422


def test_unexpected_fields_are_rejected(client):
    response = client.post(
        "/chat", json={"session_id": "s1", "message": "hello", "coupon_code": "FREE100"}
    )
    assert response.status_code == 422


def test_client_cannot_control_internal_graph_state(client):
    """None of these field names exist on ChatRequest - extra="forbid"
    turns "the client cannot control internal graph fields" into an
    enforced 422, not merely a convention nobody violates by accident.
    """
    response = client.post(
        "/chat",
        json={
            "session_id": "s1",
            "message": "hello",
            "plan": ["fake-step"],
            "next_agent": "order",
            "evidence": [{"source": "fake", "claim": "fake", "data": {}}],
            "retry_count": 999,
            "step_count": 999,
            "workflow_status": "completed",
        },
    )
    assert response.status_code == 422
    rejected_fields = {tuple(error["loc"][-1:])[0] for error in response.json()["details"]}
    for forbidden_field in ("plan", "next_agent", "evidence", "retry_count", "step_count", "workflow_status"):
        assert forbidden_field in rejected_fields


# ---------------------------------------------------------------------------
# 15-17: service failures and unexpected errors, via a stubbed graph
# ---------------------------------------------------------------------------


def test_workflow_timeout_returns_a_safe_error(client, override_graph, monkeypatch):
    monkeypatch.setenv("SCOUT_WORKFLOW_TIMEOUT_SECONDS", "0.05")
    get_settings.cache_clear()

    def _slow_invoke(state):
        time.sleep(0.5)
        return state

    override_graph(_slow_invoke)

    response = client.post("/chat", json={"session_id": "s-timeout", "message": "hello"})

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "WORKFLOW_TIMEOUT"
    assert "try again" in body["message"].lower()

    get_settings.cache_clear()


def test_known_tool_failure_returns_a_structured_safe_response(client, override_graph):
    def _raise_tool_failure(state):
        raise sqlite3.Error("database is locked")

    override_graph(_raise_tool_failure)

    response = client.post("/chat", json={"session_id": "s-toolfail", "message": "hello"})

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "TOOL_UNAVAILABLE"
    assert "database is locked" not in body["message"]
    assert "sqlite3" not in str(body)


def test_unexpected_graph_errors_hide_internal_details(client, override_graph):
    def _raise_unexpected(state):
        raise RuntimeError("supervisor internal trace: /etc/passwd secret-key=abc123")

    override_graph(_raise_unexpected)

    response = client.post("/chat", json={"session_id": "s-crash", "message": "hello"})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    rendered = str(body)
    assert "secret-key" not in rendered
    assert "/etc/passwd" not in rendered
    assert "RuntimeError" not in rendered
    assert "Traceback" not in rendered


# ---------------------------------------------------------------------------
# 18-19: no leaked internals, and /health still works
# ---------------------------------------------------------------------------


def test_response_contains_no_chain_of_thought_prompts_sql_or_secrets(client):
    response = client.post("/chat", json={"session_id": "s-safe", "message": ACCEPTANCE_QUERY})
    rendered = response.text.lower()

    forbidden_substrings = [
        "select ",
        "insert into",
        "password",
        "secret",
        "api_key",
        "chain of thought",
        "you are a helpful assistant",
        "system prompt",
        "/users/",
        "/scout/agents/",
        "traceback",
    ]
    for forbidden in forbidden_substrings:
        assert forbidden not in rendered

    known_activities = {
        "Understanding your request",
        "Searching the product catalog",
        "Ranking matching products",
        "Checking your selected store's inventory",
        "Comparing fulfillment options",
        "Searching nearby stores",
        "Finding available substitutes",
        "Verifying product details",
    }
    assert set(response.json()["activity_events"]) <= known_activities


def test_health_still_passes(client):
    response = client.get("/health")
    assert response.status_code == 200
