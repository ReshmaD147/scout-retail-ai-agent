"""Tests for PromotionRepository."""

from scout.repositories.promotion_repository import PromotionRepository


def test_list_active_returns_only_active_flagged_promotions(seeded_db_path):
    repo = PromotionRepository(seeded_db_path)
    promotions = repo.list_active()
    assert promotions
    assert all(p.active for p in promotions)


def test_list_active_filters_by_product(seeded_db_path):
    repo = PromotionRepository(seeded_db_path)
    promotions = repo.list_active(product_id="FTW-004")
    assert len(promotions) == 1
    assert promotions[0].promotion_id == "PRM-002"


def test_list_active_excludes_manually_disabled_promotions(seeded_db_path):
    # PRM-006 (for FTW-008) is seeded with active = 0.
    repo = PromotionRepository(seeded_db_path)
    promotions = repo.list_active(product_id="FTW-008")
    assert promotions == []


def test_list_active_does_not_filter_by_date_range(seeded_db_path):
    # PRM-004 (for ELE-001) is active = 1 but its date range is in the
    # future; PRM-007 (for ELE-005) is active = 1 but already expired.
    # list_active() must return both - date-range validity is a
    # service-layer decision, not this repository's job.
    repo = PromotionRepository(seeded_db_path)
    future_promo = repo.list_active(product_id="ELE-001")
    expired_promo = repo.list_active(product_id="ELE-005")
    assert any(p.promotion_id == "PRM-004" for p in future_promo)
    assert any(p.promotion_id == "PRM-007" for p in expired_promo)
