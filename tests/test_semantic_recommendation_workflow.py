"""End-to-end tests proving Step 15.5's semantic retrieval integrates
through the real LangGraph workflow (scout/orchestration/graph.py),
not just at the product_search_service unit level.

Both queries below deliberately avoid every word in
scout.agents.understand_request._DESCRIPTOR_KEYWORDS, so
understand_request_node extracts keyword=None and
recommendation_agent_node's semantic_search_products call takes the
new semantic path (see scout/services/product_search_service.py's
module docstring for the full retrieval order) - proving this phase's
new code, not the unchanged literal-keyword path every test in
tests/test_retail_graph.py already exercises.
"""

import pytest

from scout.config import get_settings
from scout.orchestration.graph import run_graph


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_a_semantic_only_query_resolves_the_comfort_work_shoe():
    result = run_graph(
        session_id="SEM1",
        customer_query="I need comfortable shoes for standing all day at the register, "
        "under $100, pickup today near Maple Grove.",
    )

    assert result.workflow_status == "completed"
    assert "ComfortPro Shift Support" in result.final_response  # UNVERIFIED - run and confirm
    assert len(result.product_candidates) <= 3


def test_a_semantically_matched_but_fully_unavailable_product_is_never_recommended():
    result = run_graph(
        session_id="SEM2",
        customer_query="Find an insulated cold-weather boot for freezing travel, under $150, "
        "pickup today near Brooklyn Park.",
    )

    assert result.workflow_status == "completed"
    assert "FTW-010" not in [c.product_id for c in result.product_candidates]
    assert len(result.product_candidates) <= 3