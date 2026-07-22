"""Tests for the Response Verification Agent (Step 11).

Uses the real seeded database throughout - every catalog check
(product ID, name, price, budget) re-reads it fresh via
get_product_details, so a hand-crafted candidate that does not match a
real seeded row is exactly what should fail those checks. Real seed
facts relied on here (scout/database/seed.py):

- FTW-004 "ComfortPro Shift Support", Footwear/Work, $89.99.
- FTW-002 "TrailMax Ridge Hiker", Footwear/Hiking, $109.99.
- FTW-004 has one currently-active promotion, PRM-002 ("Workwear
  Comfort Event", 2026-07-10 to 2026-07-31).
- STR-001 Maple Grove, STR-002 Plymouth, STR-003 Brooklyn Park.
"""

import pytest

from scout.config import get_settings
from scout.agents.response_verification import (
    _NO_RESULTS_MESSAGE,
    _final_response_unsupported_claim,
    _verify_against_catalog,
    _verify_inventory_and_store_claim,
    _verify_promotion_claims,
    response_verification_node,
)
from scout.mcp.schemas import ProductSummary
from scout.orchestration.limits import SAFE_FAILURE_MESSAGE
from scout.orchestration.state import EvidenceEntry, RetailGraphState


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _product(product_id="FTW-004", name="ComfortPro Shift Support", price=89.99, subcategory="Work"):
    return ProductSummary(
        product_id=product_id,
        name=name,
        brand="ComfortPro",
        category="Footwear",
        subcategory=subcategory,
        price=price,
        rating=4.7,
        review_count=401,
        active=True,
    )


def _state(**overrides):
    defaults = {"session_id": "S1", "customer_query": "find work shoes"}
    defaults.update(overrides)
    return RetailGraphState(**defaults)


def _selected_store_evidence(product_id="FTW-004", name="ComfortPro Shift Support", quantity=7):
    return EvidenceEntry(
        source="check_store_inventory",
        claim=f"{name} ({product_id}) has {quantity} unit(s) available for pickup today at Scout Demo Store - Maple Grove",
        data={"store_id": "STR-001", "store_name": "Scout Demo Store - Maple Grove", "sellable_quantity": quantity},
    )


def _nearby_store_evidence(product_id="FTW-004", name="ComfortPro Shift Support", quantity=7):
    return EvidenceEntry(
        source="find_nearby_inventory",
        claim=(
            f"{name} ({product_id}) has {quantity} unit(s) available for pickup today at "
            "Scout Demo Store - Plymouth, 4.28 miles away"
        ),
        data={"store_id": "STR-002", "store_name": "Scout Demo Store - Plymouth", "sellable_quantity": quantity},
    )


def _substitute_evidence(product_id="FTW-002", quantity=9, reference="FTW-010"):
    return EvidenceEntry(
        source="find_available_substitutes",
        claim=(
            f"TrailMax Ridge Hiker ({product_id}) is offered as a substitute for {reference}, "
            f"with {quantity} unit(s) available for pickup today"
        ),
        data={"sellable_quantity": quantity},
    )


# ---------------------------------------------------------------------------
# _verify_against_catalog - checks 1-4
# ---------------------------------------------------------------------------


def test_catalog_check_passes_for_a_real_matching_product():
    catalog_product, issues = _verify_against_catalog(_product(), max_price=100.0)

    assert issues == []
    assert catalog_product.name == "ComfortPro Shift Support"


def test_catalog_check_fails_when_the_product_id_does_not_exist():
    fake = _product(product_id="FTW-999", name="Ghost Shoe", price=1.0)

    catalog_product, issues = _verify_against_catalog(fake, max_price=100.0)

    assert catalog_product is None
    assert issues[0].error_type == "not_found"
    assert issues[0].step == "verify_product_id"


def test_catalog_check_fails_when_the_claimed_name_does_not_match():
    mismatched = _product(name="Definitely Not The Real Name")

    _, issues = _verify_against_catalog(mismatched, max_price=100.0)

    assert any(issue.step == "verify_product_name" for issue in issues)


def test_catalog_check_fails_when_the_claimed_price_does_not_match():
    mismatched = _product(price=9.99)

    _, issues = _verify_against_catalog(mismatched, max_price=100.0)

    assert any(issue.step == "verify_product_price" for issue in issues)


def test_catalog_check_fails_when_the_catalog_price_exceeds_the_budget():
    _, issues = _verify_against_catalog(_product(), max_price=50.0)

    assert any(issue.step == "verify_budget" for issue in issues)


def test_catalog_check_ignores_budget_when_none_was_stated():
    _, issues = _verify_against_catalog(_product(), max_price=None)

    assert issues == []


# ---------------------------------------------------------------------------
# _verify_inventory_and_store_claim - checks 5-6
# ---------------------------------------------------------------------------


def test_inventory_claim_passes_when_it_matches_its_evidence():
    claim = {
        "product_id": "FTW-004",
        "channel": "selected_store",
        "store_id": "STR-001",
        "store_name": "Scout Demo Store - Maple Grove",
        "sellable_quantity": 7,
    }
    issues = _verify_inventory_and_store_claim("FTW-004", claim, [_selected_store_evidence()], intent={})

    assert issues == []


def test_inventory_claim_fails_with_no_supporting_evidence_at_all():
    claim = {"product_id": "FTW-004", "channel": "selected_store", "store_id": "STR-001", "sellable_quantity": 7}

    issues = _verify_inventory_and_store_claim("FTW-004", claim, evidence=[], intent={})

    assert issues[0].step == "verify_inventory_claim"
    assert "no supporting tool evidence" in issues[0].message


def test_inventory_claim_fails_when_it_does_not_match_its_own_channels_evidence():
    """A nearby_store claim must be checked against find_nearby_inventory
    evidence - not a stale check_store_inventory entry for the same
    product from an earlier, different channel."""
    claim = {
        "product_id": "FTW-004",
        "channel": "nearby_store",
        "store_id": "STR-002",
        "store_name": "Scout Demo Store - Plymouth",
        "sellable_quantity": 7,
    }
    # Only the selected_store evidence exists - no find_nearby_inventory evidence.
    issues = _verify_inventory_and_store_claim("FTW-004", claim, [_selected_store_evidence()], intent={})

    assert issues[0].step == "verify_inventory_claim"


def test_inventory_claim_fails_when_the_quantity_does_not_match_the_evidence():
    claim = {
        "product_id": "FTW-004",
        "channel": "selected_store",
        "store_id": "STR-001",
        "store_name": "Scout Demo Store - Maple Grove",
        "sellable_quantity": 99,
    }
    issues = _verify_inventory_and_store_claim(
        "FTW-004", claim, [_selected_store_evidence(quantity=7)], intent={}
    )

    assert any(issue.step == "verify_inventory_claim" and "quantity" in issue.message for issue in issues)


def test_store_claim_fails_when_the_store_does_not_match_the_evidence():
    claim = {
        "product_id": "FTW-004",
        "channel": "selected_store",
        "store_id": "STR-999",
        "store_name": "A Store That Isn't The Evidence's Store",
        "sellable_quantity": 7,
    }
    issues = _verify_inventory_and_store_claim(
        "FTW-004", claim, [_selected_store_evidence(quantity=7)], intent={}
    )

    steps = {issue.step for issue in issues}
    assert "verify_store_claim" in steps


def test_substitute_store_claim_is_checked_against_the_selected_store_in_intent():
    claim = {
        "product_id": "FTW-002",
        "channel": "substitute",
        "store_id": "STR-003",
        "store_name": "Scout Demo Store - Brooklyn Park",
        "sellable_quantity": 9,
        "substitute_for": "FTW-010",
    }
    intent = {"selected_store_id": "STR-003", "selected_store_name": "Scout Demo Store - Brooklyn Park"}

    issues = _verify_inventory_and_store_claim("FTW-002", claim, [_substitute_evidence()], intent)

    assert issues == []


def test_substitute_store_claim_fails_when_it_does_not_match_the_selected_store():
    claim = {
        "product_id": "FTW-002",
        "channel": "substitute",
        "store_id": "STR-999",
        "store_name": "Somewhere Else",
        "sellable_quantity": 9,
        "substitute_for": "FTW-010",
    }
    intent = {"selected_store_id": "STR-003", "selected_store_name": "Scout Demo Store - Brooklyn Park"}

    issues = _verify_inventory_and_store_claim("FTW-002", claim, [_substitute_evidence()], intent)

    assert any(issue.step == "verify_store_claim" for issue in issues)


# ---------------------------------------------------------------------------
# _verify_promotion_claims - check 7
# ---------------------------------------------------------------------------


def test_promotion_check_passes_with_no_promotion_claims():
    assert _verify_promotion_claims("FTW-004", evidence=[]) == []


def test_promotion_check_passes_for_a_real_currently_active_promotion():
    evidence = [
        EvidenceEntry(
            source="get_promotions",
            claim="FTW-004 has an active promotion PRM-002",
            data={"product_id": "FTW-004", "promotion_id": "PRM-002"},
        )
    ]

    assert _verify_promotion_claims("FTW-004", evidence) == []


def test_promotion_check_fails_for_a_promotion_that_does_not_exist():
    evidence = [
        EvidenceEntry(
            source="get_promotions",
            claim="FTW-004 has an active promotion PRM-BOGUS",
            data={"product_id": "FTW-004", "promotion_id": "PRM-BOGUS"},
        )
    ]

    issues = _verify_promotion_claims("FTW-004", evidence)

    assert issues[0].step == "verify_promotion"
    assert "not currently active" in issues[0].message


# ---------------------------------------------------------------------------
# _final_response_unsupported_claim - check 8
# ---------------------------------------------------------------------------


def test_final_response_check_passes_when_every_claim_is_verified():
    text = "ComfortPro Shift Support ($89.99) has 7 unit(s) available for pickup today at Store."
    assert _final_response_unsupported_claim(text, [_product()]) is None


def test_final_response_check_fails_on_a_fabricated_price():
    text = "ComfortPro Shift Support ($1.00) has 7 unit(s) available for pickup today at Store."
    issue = _final_response_unsupported_claim(text, [_product()])

    assert issue is not None
    assert issue.step == "verify_final_response"


def test_final_response_check_fails_when_a_verified_candidate_is_missing():
    text = "Some other product is available."
    issue = _final_response_unsupported_claim(text, [_product()])

    assert issue is not None
    assert issue.step == "verify_final_response"


# ---------------------------------------------------------------------------
# response_verification_node - end-to-end over the node itself
# ---------------------------------------------------------------------------


def test_no_candidates_returns_the_fixed_no_results_message():
    state = _state(product_candidates=[])

    update = response_verification_node(state)

    assert update["final_response"] == _NO_RESULTS_MESSAGE
    assert update["workflow_status"] == "completed"


def test_a_fully_grounded_candidate_produces_a_grounded_sentence():
    state = _state(
        product_candidates=[_product()],
        intent={"max_price": 100.0},
        inventory_results=[
            {
                "product_id": "FTW-004",
                "channel": "nearby_store",
                "store_id": "STR-002",
                "store_name": "Scout Demo Store - Plymouth",
                "sellable_quantity": 7,
            }
        ],
        evidence=[_nearby_store_evidence()],
    )

    update = response_verification_node(state)

    assert update["workflow_status"] == "completed"
    assert "ComfortPro Shift Support ($89.99)" in update["final_response"]
    assert "7 unit(s)" in update["final_response"]
    assert "Scout Demo Store - Plymouth" in update["final_response"]
    assert "errors" not in update


def test_a_substitute_candidate_is_phrased_as_a_substitute():
    state = _state(
        product_candidates=[_product(product_id="FTW-002", name="TrailMax Ridge Hiker", price=109.99, subcategory="Hiking")],
        intent={
            "max_price": 150.0,
            "selected_store_id": "STR-003",
            "selected_store_name": "Scout Demo Store - Brooklyn Park",
        },
        inventory_results=[
            {
                "product_id": "FTW-002",
                "channel": "substitute",
                "store_id": "STR-003",
                "store_name": "Scout Demo Store - Brooklyn Park",
                "sellable_quantity": 9,
                "substitute_for": "FTW-010",
            }
        ],
        evidence=[_substitute_evidence()],
    )

    update = response_verification_node(state)

    assert update["workflow_status"] == "completed"
    assert "offered as a substitute for FTW-010" in update["final_response"]


def test_an_ungrounded_candidate_among_others_is_dropped_and_flagged():
    state = _state(
        product_candidates=[
            _product(),
            _product(product_id="FTW-999", name="Ghost Shoe", price=1.0),
        ],
        intent={"max_price": 100.0},
        inventory_results=[
            {
                "product_id": "FTW-004",
                "channel": "selected_store",
                "store_id": "STR-001",
                "store_name": "Scout Demo Store - Maple Grove",
                "sellable_quantity": 3,
            },
            # A claim exists for the fake product too, so this test
            # exercises the catalog "not_found" check specifically -
            # not the earlier "no claim at all" check.
            {
                "product_id": "FTW-999",
                "channel": "selected_store",
                "store_id": "STR-001",
                "store_name": "Scout Demo Store - Maple Grove",
                "sellable_quantity": 5,
            },
        ],
        evidence=[
            _selected_store_evidence(quantity=3),
            EvidenceEntry(
                source="check_store_inventory",
                claim="Ghost Shoe (FTW-999) has 5 unit(s) available for pickup today at Scout Demo Store - Maple Grove",
                data={"store_id": "STR-001", "store_name": "Scout Demo Store - Maple Grove", "sellable_quantity": 5},
            ),
        ],
    )

    update = response_verification_node(state)

    assert update["workflow_status"] == "completed"
    assert [c.product_id for c in update["product_candidates"]] == ["FTW-004"]
    assert any(issue.error_type == "not_found" for issue in update["errors"])


def test_every_candidate_failing_requests_a_safe_correction_first():
    state = _state(
        product_candidates=[_product(name="Wrong Name")],
        intent={"max_price": 100.0},
        inventory_results=[
            {
                "product_id": "FTW-004",
                "channel": "selected_store",
                "store_id": "STR-001",
                "store_name": "Scout Demo Store - Maple Grove",
                "sellable_quantity": 3,
            }
        ],
        evidence=[_selected_store_evidence(name="Wrong Name", quantity=3)],
        correction_count=0,
    )

    update = response_verification_node(state)

    assert update["workflow_status"] == "in_progress"
    assert update["correction_count"] == 1
    assert update["inventory_results"] == []
    assert "final_response" not in update
    assert any(issue.step == "verify_product_name" for issue in update["errors"])


def test_every_candidate_failing_returns_the_safe_fallback_once_the_limit_is_reached(monkeypatch):
    monkeypatch.setenv("MAX_CORRECTION_ATTEMPTS", "2")
    get_settings.cache_clear()
    state = _state(
        product_candidates=[_product(name="Wrong Name")],
        intent={"max_price": 100.0},
        inventory_results=[
            {
                "product_id": "FTW-004",
                "channel": "selected_store",
                "store_id": "STR-001",
                "store_name": "Scout Demo Store - Maple Grove",
                "sellable_quantity": 3,
            }
        ],
        evidence=[_selected_store_evidence(name="Wrong Name", quantity=3)],
        correction_count=2,
    )

    update = response_verification_node(state)

    assert update["workflow_status"] == "failed"
    assert update["final_response"] == SAFE_FAILURE_MESSAGE
    assert update["product_candidates"] == []


def test_stops_at_the_step_budget(monkeypatch):
    monkeypatch.setenv("MAX_WORKFLOW_STEPS", "1")
    get_settings.cache_clear()
    state = _state(step_count=1)

    update = response_verification_node(state)

    assert update["workflow_status"] == "stopped_at_limit"
