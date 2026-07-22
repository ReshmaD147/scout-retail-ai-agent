"""Local embedding providers for semantic product search (Step 15.5).

Why two providers, and why "hashing" is the default
------------------------------------------------------
This codebase has no live model dependency anywhere yet - every agent
that will eventually call a real LLM (scout/agents/understand_request.py,
scout/agents/cart_command_agent.py) currently uses a deterministic,
clearly-documented placeholder instead, and
scout/orchestration/supervisor_policy.py already established the
pattern this module follows: a `Protocol` interface, a deterministic
default anyone can run with zero setup, and a real, fully-implemented
alternative behind the exact same interface for when a live local model
is actually available.

`HashingEmbeddingProvider` is that deterministic default: a local,
dependency-free "hashing trick" bag-of-words embedding (no download, no
network call, no server to run), used everywhere in tests and by
default in development so this feature works and is fully testable with
nothing installed beyond this repository's existing requirements.txt.
Common English stopwords are stripped before hashing so shared filler
words ("a", "the", "for") don't dilute the real, content-bearing
overlap between a query and a product's search text.

`OllamaEmbeddingProvider` is the real local embedding model Step 15.5
asks for: it calls a running Ollama server's `/api/embeddings` endpoint
(CLAUDE.md section 2's already-approved local LLM runtime) using
`httpx`, already a dependency. Operators who have Ollama installed and
have pulled an embedding model (e.g. `ollama pull nomic-embed-text`) can
switch to it by setting `EMBEDDING_PROVIDER=ollama` - nothing else in
scout/services/product_search_service.py needs to change, since both
providers satisfy the same `EmbeddingProvider` protocol.

Neither provider is ever called directly by an agent or an MCP tool -
see scout/services/product_search_service.py, which is the only caller.
"""

import hashlib
import math
import re
from typing import List, Protocol

import httpx

from scout.config import get_settings

_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "of", "to", "in", "on", "at",
    "is", "are", "was", "were", "be", "this", "that", "these", "those", "it",
    "your", "you", "i", "my", "me", "as", "by", "from", "up", "no",
    "not", "so", "than", "too", "very", "can", "will", "do", "does",
}
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return [token for token in _TOKEN_PATTERN.findall(text.lower()) if token not in _STOPWORDS]


class EmbeddingProvider(Protocol):
    """Anything that can turn one piece of text into a fixed-length vector."""

    @property
    def model_name(self) -> str:
        """A stable identifier for this provider+model (e.g.
        "hashing-v1:256" or "ollama:nomic-embed-text"), stored alongside
        every embedding (scout/repositories/embedding_repository.py) so
        a later change of provider/model is detected as staleness
        rather than silently comparing incompatible vectors."""
        ...

    def embed(self, text: str) -> List[float]: ...


class EmbeddingUnavailableError(Exception):
    """Raised when a configured embedding provider cannot produce a
    vector (e.g. the Ollama server is unreachable). Never raised by
    HashingEmbeddingProvider, which has no external dependency to fail."""


class HashingEmbeddingProvider:
    """A deterministic, local, dependency-free bag-of-words embedding.

    Standard "hashing trick": each stopword-filtered token is hashed
    with sha256 (stable across processes and machines, unlike Python's
    salted built-in `hash()`) into one of `dimensions` buckets, with a
    second hash byte choosing +1/-1 so unrelated tokens partially
    cancel instead of only ever adding up. The result is L2-normalized
    so cosine similarity behaves the same regardless of a text's raw
    length.

    This is not a neural embedding model - it captures shared
    vocabulary, not synonymy or meaning a human would infer without
    shared words. It is used as this phase's default specifically
    because it requires nothing beyond the Python standard library, is
    perfectly reproducible for tests, and - as scout/database/seed.py's
    product attributes already spell out concrete comfort/use-case
    vocabulary (e.g. "arch support", "work shifts / standing all day")
    for exactly the kind of query Step 15.5 is meant to serve - is
    enough to satisfy real natural-language queries against this
    catalog. See OllamaEmbeddingProvider for a genuine neural
    alternative behind the same interface.
    """

    def __init__(self, dimensions: int = 256) -> None:
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        return f"hashing-v1:{self._dimensions}"

    def embed(self, text: str) -> List[float]:
        vector = [0.0] * self._dimensions
        for token in _tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0.0:
            return vector
        return [component / norm for component in vector]


class OllamaEmbeddingProvider:
    """A real local neural embedding model, served by Ollama.

    Requires Ollama running locally (default http://localhost:11434)
    with an embedding model already pulled (default "nomic-embed-text").
    Never used in this repository's own test suite (see
    HashingEmbeddingProvider) - tests that exercise this class instead
    supply a fake client, so nothing here needs a live server to be
    verified.
    """

    def __init__(self, base_url: str, model: str, client) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client

    @property
    def model_name(self) -> str:
        return f"ollama:{self._model}"

    def embed(self, text: str) -> List[float]:
        try:
            response = self._client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailableError(
                f"Ollama embedding model {self._model!r} is unavailable at {self._base_url}: {exc}"
            ) from exc

        payload = response.json()
        embedding = payload.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise EmbeddingUnavailableError(
                f"Ollama returned no embedding vector for model {self._model!r}."
            )
        return [float(value) for value in embedding]


def get_embedding_provider() -> EmbeddingProvider:
    """Build the embedding provider selected by centralized configuration.

    Returns:
        A HashingEmbeddingProvider (default, "hashing") or an
        OllamaEmbeddingProvider ("ollama") - see scout/config.py's
        `embedding_provider` setting. This is the only place either
        class is constructed for production use; tests construct
        HashingEmbeddingProvider or a fake directly instead of going
        through settings.
    """
    settings = get_settings()
    if settings.embedding_provider == "ollama":
        return OllamaEmbeddingProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embedding_model,
            client=httpx.Client(timeout=10.0),
        )
    return HashingEmbeddingProvider(dimensions=settings.embedding_dimensions)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Standard cosine similarity, safe against zero vectors.

    Returns:
        A value in [-1.0, 1.0], or 0.0 if either vector has zero
        magnitude (an empty/all-token-collision text) - never raises a
        ZeroDivisionError.

    Raises:
        ValueError: if `a` and `b` have different lengths.
    """
    if len(a) != len(b):
        raise ValueError(f"vectors must be the same length, got {len(a)} and {len(b)}")

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)