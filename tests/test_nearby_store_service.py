"""Tests for nearby_store_service."""

import pytest

from scout.config import get_settings
from scout.repositories.models import StoreDistance
from scout.services.nearby_store_service import filter_within_radius, resolve_search_radius
from tests.factories import make_store


def test_resolve_search_radius_defaults_to_configured_default():
    get_settings.cache_clear()
    assert resolve_search_radius(None) == get_settings().nearby_store_radius_miles
    get_settings.cache_clear()


def test_resolve_search_radius_is_capped_at_configured_maximum(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("MAX_SEARCH_RADIUS_MILES", "50")
    get_settings.cache_clear()

    resolved = resolve_search_radius(requested_radius_miles=5000)

    assert resolved == 50.0
    get_settings.cache_clear()


def test_resolve_search_radius_rejects_zero_or_negative():
    with pytest.raises(ValueError):
        resolve_search_radius(0)
    with pytest.raises(ValueError):
        resolve_search_radius(-10)


def test_filter_within_radius_keeps_only_close_candidates():
    near = StoreDistance(store=make_store(store_id="A"), distance_miles=3.0)
    far = StoreDistance(store=make_store(store_id="B"), distance_miles=40.0)

    result = filter_within_radius([near, far], radius_miles=10.0)

    assert [entry.store.store_id for entry in result] == ["A"]
