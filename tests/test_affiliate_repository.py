"""Repository tests for Step 16.5 external offers and click records."""

from scout.repositories.affiliate_repository import AffiliateRepository


def test_lists_only_active_in_stock_offers(seeded_db_path):
    repository = AffiliateRepository(seeded_db_path)

    offers = repository.list_active_offers()

    assert offers
    assert all(offer.active for offer in offers)
    assert all(offer.availability_status == "in_stock" for offer in offers)
    assert all(offer.offer_id != "EXT-OFF-009" for offer in offers)


def test_records_click_without_creating_an_order(seeded_db_path):
    repository = AffiliateRepository(seeded_db_path)

    click = repository.record_click(
        offer_id="EXT-OFF-001",
        session_id="affiliate-session",
        workflow_id="workflow-1",
        source_product_id=None,
        match_type="similar",
    )

    clicks = repository.list_clicks_for_session("affiliate-session")
    assert [entry.click_id for entry in clicks] == [click.click_id]
    assert clicks[0].offer_id == "EXT-OFF-001"
    assert clicks[0].match_type == "similar"
