"""Deterministic external-offer matching and click-tracking tests."""

from scout.repositories.affiliate_repository import AffiliateRepository
import pytest

from scout.services.external_offer_service import (
    ExternalOfferServiceError,
    ReferenceIdentifiers,
    search_external_offers,
    track_affiliate_click,
)


def test_semantic_like_token_matching_finds_work_shoe_alternatives(seeded_db_path):
    offers = search_external_offers(
        query_text="comfortable shoes for standing all day at work",
        category="Footwear",
        max_price=100,
        db_path=seeded_db_path,
    )

    assert offers
    assert offers[0].offer_id == "EXT-OFF-001"
    assert all(offer.category == "Footwear" for offer in offers)
    assert all(offer.price <= 100 for offer in offers)
    assert all(offer.match_type == "similar" for offer in offers)
    assert all("Similar external alternative" == offer.match_label for offer in offers)


def test_external_budget_is_a_hard_filter(seeded_db_path):
    offers = search_external_offers(
        query_text="comfortable work shoes",
        category="Footwear",
        max_price=50,
        db_path=seeded_db_path,
    )

    assert all(offer.price <= 50 for offer in offers)
    assert "EXT-OFF-001" not in {offer.offer_id for offer in offers}


def test_exact_label_requires_matching_identifier(seeded_db_path):
    without_identifier = search_external_offers(
        query_text="all day work shoe",
        category="Footwear",
        reference_product_id="FTW-004",
        db_path=seeded_db_path,
    )
    with_identifier = search_external_offers(
        query_text="all day work shoe",
        category="Footwear",
        reference_product_id="FTW-004",
        reference_identifiers=ReferenceIdentifiers(model_number="SE-AS101"),
        db_path=seeded_db_path,
    )

    assert next(offer for offer in without_identifier if offer.offer_id == "EXT-OFF-001").match_type == "similar"
    exact = next(offer for offer in with_identifier if offer.offer_id == "EXT-OFF-001")
    assert exact.match_type == "exact"
    assert exact.matched_identifier_type == "model number"
    assert "same verified model number" in exact.match_reason


def test_tracking_click_persists_analytics_but_not_purchase(seeded_db_path):
    click_id, redirect_url = track_affiliate_click(
        offer_id="EXT-OFF-001",
        session_id="session-click",
        workflow_id="workflow-click",
        source_product_id=None,
        match_type="similar",
        db_path=seeded_db_path,
    )

    assert click_id
    assert redirect_url.startswith("https://example.com/")
    clicks = AffiliateRepository(seeded_db_path).list_clicks_for_session("session-click")
    assert len(clicks) == 1
    assert clicks[0].offer_id == "EXT-OFF-001"


def test_click_rejects_unknown_source_product(seeded_db_path):
    with pytest.raises(ExternalOfferServiceError) as error:
        track_affiliate_click(
            offer_id="EXT-OFF-001",
            session_id="session-click",
            source_product_id="EXT-OFF-001",
            match_type="similar",
            db_path=seeded_db_path,
        )
    assert error.value.error_type == "not_found"


def test_click_rejects_unsafe_merchant_url(seeded_db_path):
    from scout.database.connection import connection_scope

    with connection_scope(seeded_db_path) as connection:
        connection.execute(
            "UPDATE external_offers SET merchant_url = ? WHERE offer_id = ?",
            ("javascript:alert(1)", "EXT-OFF-001"),
        )

    with pytest.raises(ExternalOfferServiceError) as error:
        track_affiliate_click(
            offer_id="EXT-OFF-001",
            session_id="session-click",
            match_type="similar",
            db_path=seeded_db_path,
        )
    assert error.value.error_type == "invalid_merchant_url"
