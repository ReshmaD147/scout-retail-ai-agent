"""Tests for scout.services.embedding_service."""

import pytest

from scout.services.embedding_service import (
    EmbeddingUnavailableError,
    HashingEmbeddingProvider,
    OllamaEmbeddingProvider,
    cosine_similarity,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.last_request = None

    def post(self, url, json):
        self.last_request = (url, json)
        return _FakeResponse(self._payload)


def test_hashing_provider_is_deterministic():
    provider = HashingEmbeddingProvider(dimensions=64)

    first = provider.embed("comfortable shoes for standing all day")
    second = provider.embed("comfortable shoes for standing all day")

    assert first == second
    assert len(first) == 64


def test_hashing_provider_differs_for_unrelated_text():
    provider = HashingEmbeddingProvider(dimensions=64)

    shoes = provider.embed("comfortable shoes for standing all day")
    earbuds = provider.embed("wireless noise cancelling earbuds")

    assert shoes != earbuds


def test_hashing_provider_model_name_includes_dimensions():
    provider = HashingEmbeddingProvider(dimensions=128)
    assert provider.model_name == "hashing-v1:128"


def test_cosine_similarity_of_identical_vectors_is_one():
    vector = [1.0, 2.0, 3.0]
    assert cosine_similarity(vector, vector) == pytest.approx(1.0)


def test_cosine_similarity_handles_zero_vectors():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_similarity_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 2.0], [1.0])


def test_ollama_provider_embeds_using_the_injected_client():
    client = _FakeClient({"embedding": [0.1, 0.2, 0.3]})
    provider = OllamaEmbeddingProvider(base_url="http://localhost:11434", model="nomic-embed-text", client=client)

    result = provider.embed("running shoes")

    assert result == [0.1, 0.2, 0.3]
    assert client.last_request[0] == "http://localhost:11434/api/embeddings"
    assert client.last_request[1] == {"model": "nomic-embed-text", "prompt": "running shoes"}
    assert provider.model_name == "ollama:nomic-embed-text"


def test_ollama_provider_raises_a_clear_error_when_no_embedding_is_returned():
    client = _FakeClient({"embedding": []})
    provider = OllamaEmbeddingProvider(base_url="http://localhost:11434", model="nomic-embed-text", client=client)

    with pytest.raises(EmbeddingUnavailableError):
        provider.embed("running shoes")