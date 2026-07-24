from __future__ import annotations

from datetime import date

import pytest

from scout.services.embedding_service import HashingEmbeddingProvider
from scout.services.policy_retrieval_service import (
    build_policy_vector_index,
    chunk_policy_documents,
    load_policy_documents,
)


def _index():
    return build_policy_vector_index(provider=HashingEmbeddingProvider(dimensions=256))


def test_policy_ingestion_creates_meaningful_heading_chunks_with_metadata():
    documents = load_policy_documents()
    chunks = chunk_policy_documents(documents)

    assert len(documents) == 12
    assert len(chunks) >= 48
    assert all(chunk.text for chunk in chunks)
    assert all(chunk.section_title for chunk in chunks)
    assert all(chunk.status == "active" for chunk in chunks)
    assert all(chunk.version == "1.0.0" for chunk in chunks)
    assert all(chunk.effective_date == date(2026, 7, 1) for chunk in chunks)
    assert any(chunk.policy_file == "returns.md" and chunk.section_title == "Standard Policy" for chunk in chunks)


def test_policy_vector_index_embeds_every_chunk_and_exposes_model_name():
    index = _index()

    assert index.model_name == "hashing-v1:256"
    assert len(index.chunks) >= 48
    assert len({chunk.chunk_id for chunk in index.chunks}) == len(index.chunks)


def test_metadata_filtering_limits_results_to_active_category_and_effective_date():
    index = _index()

    refund_results = index.search("How long do refunds normally take?", category="refunds", effective_on=date(2026, 7, 24))
    assert refund_results
    assert all(result.chunk.category == "refunds" or "refunds" in result.chunk.categories for result in refund_results)
    assert refund_results[0].chunk.policy_file == "refunds.md"

    future_blocked = index.search("What is the return window?", effective_on=date(2026, 6, 30))
    assert future_blocked == []


def test_retrieves_return_window_standard_policy_section():
    result = _index().search("What is the return window?", limit=3, effective_on=date(2026, 7, 24))[0]

    assert result.chunk.policy_file == "returns.md"
    assert result.chunk.section_title == "Standard Policy"
    assert "30 days" in result.chunk.text


def test_retrieves_opened_moisturizer_return_exception():
    result = _index().search("Can I return opened moisturizer?", limit=3, effective_on=date(2026, 7, 24))[0]

    assert result.chunk.policy_file == "returns.md"
    assert result.chunk.section_title == "Exceptions"
    assert "opened moisturizer" in result.chunk.text
    assert "not returnable" in result.chunk.text


def test_retrieves_online_purchase_in_store_return_section():
    result = _index().search("Can online purchases be returned in store?", limit=3, effective_on=date(2026, 7, 24))[0]

    assert result.chunk.policy_file == "returns.md"
    assert result.chunk.section_title == "Standard Policy"
    assert "online purchases may be returned in store" in result.chunk.text


def test_retrieves_refund_timing_section():
    result = _index().search("How long do refunds normally take?", limit=3, effective_on=date(2026, 7, 24))[0]

    assert result.chunk.policy_file == "refunds.md"
    assert result.chunk.section_title == "Timing"
    assert "3 business days" in result.chunk.text


def test_retrieves_missing_delivered_package_investigation_section():
    result = _index().search(
        "What happens when a package is marked delivered but is missing?",
        limit=3,
        effective_on=date(2026, 7, 24),
    )[0]

    assert result.chunk.policy_file == "missing_packages.md"
    assert result.chunk.section_title in {"Standard Policy", "Investigation Steps"}
    assert "tracking status" in result.chunk.text or "delivery address" in result.chunk.text


def test_search_rejects_invalid_limits():
    with pytest.raises(ValueError):
        _index().search("returns", limit=0)
