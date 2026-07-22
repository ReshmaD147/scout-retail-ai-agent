"""Tests for scout/services/product_reference_service.py (Step 15).

Scenario -> test name (matching the Step 15 prompt's numbered list):
    19. test_resolve_first_product_correctly
    20. test_return_clarification_for_ambiguous_product_reference
"""

from scout.services.product_reference_service import (
    NamedCandidate,
    parse_ordinal,
    resolve_reference,
)

_CANDIDATES = [
    NamedCandidate(reference_id="FTW-004", name="ComfortPro Shift Support"),
    NamedCandidate(reference_id="BAG-001", name="CarryNest DailyPack 20L"),
    NamedCandidate(reference_id="BAG-002", name="TerraPack Summit 35L"),
]


def test_parse_ordinal_recognizes_words_and_digits():
    assert parse_ordinal("first") == 1
    assert parse_ordinal("2nd") == 2
    assert parse_ordinal("third") == 3
    assert parse_ordinal("not-a-number") is None


def test_resolve_first_product_correctly():
    resolution = resolve_reference("first product", _CANDIDATES)
    assert resolution.reference_id == "FTW-004"
    assert resolution.clarification is None


def test_resolve_second_product_correctly():
    resolution = resolve_reference("the second item", _CANDIDATES)
    assert resolution.reference_id == "BAG-001"


def test_resolve_by_name_when_unambiguous():
    resolution = resolve_reference("the ComfortPro Shift Support", _CANDIDATES)
    assert resolution.reference_id == "FTW-004"


def test_return_clarification_for_ambiguous_product_reference():
    # "bag" substring-matches both BAG-001 and BAG-002's names.
    resolution = resolve_reference("the bag", _CANDIDATES)
    assert resolution.reference_id is None
    assert resolution.clarification is not None
    assert "CarryNest" in resolution.clarification and "TerraPack" in resolution.clarification


def test_return_clarification_for_out_of_range_ordinal():
    resolution = resolve_reference("the fifth product", _CANDIDATES)
    assert resolution.reference_id is None
    assert resolution.clarification is not None


def test_return_clarification_when_no_candidates_exist():
    resolution = resolve_reference("first product", [])
    assert resolution.reference_id is None
    assert resolution.clarification is not None


def test_return_clarification_when_nothing_matches_a_name():
    resolution = resolve_reference("a completely unrelated product", _CANDIDATES)
    assert resolution.reference_id is None
    assert resolution.clarification is not None
