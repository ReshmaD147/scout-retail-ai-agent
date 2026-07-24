"""Policy-document ingestion and retrieval.

This module intentionally stops at retrieval. It does not answer users,
call an LLM, or join the agent graph. It turns the Markdown corpus in
``data/policies`` into meaningful heading-based chunks, embeds those
chunks with Scout's existing embedding provider, stores them in an
in-memory vector index, and returns active policy sections with metadata
filters applied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from scout.services.embedding_service import EmbeddingProvider, cosine_similarity, get_embedding_provider

POLICY_DIR = Path(__file__).resolve().parents[2] / "data" / "policies"
_FRONTMATTER_DELIMITER = "---"
_HEADING_PATTERN = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

_QUERY_EXPANSIONS = {
    "return": {"returns", "returnable", "returned", "opened", "in-store", "store", "window"},
    "returns": {"return", "returnable", "returned", "opened", "in-store", "store", "window"},
    "refund": {"refunds", "refunded", "payment", "timing", "business", "days"},
    "refunds": {"refund", "refunded", "payment", "timing", "business", "days"},
    "package": {"packages", "missing", "delivered", "tracking", "carrier", "address"},
    "packages": {"package", "missing", "delivered", "tracking", "carrier", "address"},
    "missing": {"package", "packages", "delivered", "tracking", "carrier", "address"},
    "delivered": {"missing", "package", "packages", "tracking", "carrier", "address"},
    "moisturizer": {"opened", "hygiene", "non-returnable", "returns", "return"},
    "opened": {"hygiene", "moisturizer", "non-returnable", "returns", "return"},
    "online": {"purchase", "purchases", "store", "in-store", "returns", "return"},
    "store": {"in-store", "pickup", "online", "returns", "return"},
}


@dataclass(frozen=True)
class PolicyDocument:
    filename: str
    metadata: dict[str, object]
    body: str


@dataclass(frozen=True)
class PolicyChunk:
    chunk_id: str
    policy_id: str
    policy_file: str
    title: str
    section_title: str
    heading_level: int
    text: str
    searchable_text: str
    category: str
    categories: tuple[str, ...]
    related_policies: tuple[str, ...]
    version: str
    effective_date: date
    status: str


@dataclass(frozen=True)
class IndexedPolicyChunk:
    chunk: PolicyChunk
    embedding: List[float]


@dataclass(frozen=True)
class PolicyRetrievalResult:
    chunk: PolicyChunk
    score: float


class PolicyDocumentError(ValueError):
    """Raised when a policy document cannot be parsed into valid retrieval data."""


def _parse_metadata_value(raw: str) -> str | list[str]:
    value = raw.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [item.strip() for item in inner.split(",") if item.strip()]
    return value


def load_policy_documents(policy_dir: Path = POLICY_DIR) -> list[PolicyDocument]:
    documents: list[PolicyDocument] = []
    for path in sorted(policy_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith(f"{_FRONTMATTER_DELIMITER}\n"):
            raise PolicyDocumentError(f"{path.name} is missing frontmatter")
        parts = text.split(_FRONTMATTER_DELIMITER, 2)
        if len(parts) != 3:
            raise PolicyDocumentError(f"{path.name} has malformed frontmatter")
        metadata_text, body = parts[1].strip(), parts[2].strip()
        metadata: dict[str, object] = {}
        for line in metadata_text.splitlines():
            if ":" not in line:
                raise PolicyDocumentError(f"{path.name} has malformed metadata line: {line}")
            key, value = line.split(":", 1)
            metadata[key.strip()] = _parse_metadata_value(value)
        documents.append(PolicyDocument(filename=path.name, metadata=metadata, body=body))
    return documents


def _metadata_list(metadata: dict[str, object], key: str) -> tuple[str, ...]:
    value = metadata.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PolicyDocumentError(f"metadata {key!r} must be a list of strings")
    return tuple(value)


def _metadata_string(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PolicyDocumentError(f"metadata {key!r} must be a non-empty string")
    return value.strip()


def _split_sections(body: str) -> list[tuple[int, str, str]]:
    matches = list(_HEADING_PATTERN.finditer(body))
    sections: list[tuple[int, str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section_text = body[start:end].strip()
        if not section_text:
            continue
        sections.append((len(match.group(1)), match.group(2).strip(), section_text))
    return sections


def chunk_policy_documents(documents: Iterable[PolicyDocument]) -> list[PolicyChunk]:
    chunks: list[PolicyChunk] = []
    for document in documents:
        metadata = document.metadata
        policy_id = _metadata_string(metadata, "policy_id")
        title = _metadata_string(metadata, "title")
        category = _metadata_string(metadata, "category")
        version = _metadata_string(metadata, "version")
        status = _metadata_string(metadata, "status")
        effective_date = date.fromisoformat(_metadata_string(metadata, "effective_date"))
        categories = _metadata_list(metadata, "categories")
        related_policies = _metadata_list(metadata, "related_policies")
        for index, (heading_level, section_title, section_text) in enumerate(_split_sections(document.body), start=1):
            text = section_text.replace("\n", " ").strip()
            searchable_text = " ".join([
                title,
                category,
                " ".join(categories),
                section_title,
                text,
                "related policies",
                " ".join(related_policies),
            ])
            chunks.append(
                PolicyChunk(
                    chunk_id=f"{document.filename}#section-{index}",
                    policy_id=policy_id,
                    policy_file=document.filename,
                    title=title,
                    section_title=section_title,
                    heading_level=heading_level,
                    text=text,
                    searchable_text=searchable_text,
                    category=category,
                    categories=categories,
                    related_policies=related_policies,
                    version=version,
                    effective_date=effective_date,
                    status=status,
                )
            )
    return chunks


def _tokens(text: str) -> set[str]:
    found = set(_TOKEN_PATTERN.findall(text.lower()))
    expanded = set(found)
    for token in found:
        expanded.update(_QUERY_EXPANSIONS.get(token, set()))
    return expanded


def _category_intent_bonus(query_tokens: set[str], chunk: PolicyChunk) -> float:
    if {"return", "returns", "returnable", "returned"} & query_tokens and chunk.category == "returns":
        return 0.35
    if {"refund", "refunds", "refunded"} & query_tokens and chunk.category == "refunds":
        return 0.35
    if {"missing", "package", "packages", "delivered"} & query_tokens and chunk.category == "missing_packages":
        return 0.35
    return 0.0


def _section_intent_bonus(query_tokens: set[str], chunk: PolicyChunk) -> float:
    section = chunk.section_title.lower()
    if {"opened", "moisturizer", "hygiene", "non", "returnable"} & query_tokens and section == "exceptions":
        return 0.2
    if {"time", "timing", "long", "normally", "days"} & query_tokens and section == "timing":
        return 0.2
    if {"window", "online", "store", "in-store"} & query_tokens and section == "standard policy":
        return 0.15
    if {"investigation", "missing", "delivered", "tracking"} & query_tokens and section in {"standard policy", "investigation steps"}:
        return 0.15
    return 0.0


class PolicyVectorIndex:
    """Small in-memory vector index for the Markdown policy corpus."""

    def __init__(self, chunks: Sequence[PolicyChunk], provider: Optional[EmbeddingProvider] = None) -> None:
        self._provider = provider or get_embedding_provider()
        self._indexed = [
            IndexedPolicyChunk(chunk=chunk, embedding=self._provider.embed(chunk.searchable_text))
            for chunk in chunks
        ]

    @property
    def chunks(self) -> tuple[PolicyChunk, ...]:
        return tuple(indexed.chunk for indexed in self._indexed)

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        category: Optional[str] = None,
        status: str = "active",
        effective_on: Optional[date] = None,
    ) -> list[PolicyRetrievalResult]:
        if not query.strip():
            return []
        if limit < 1:
            raise ValueError("limit must be at least 1")
        effective = effective_on or date.today()
        query_embedding = self._provider.embed(query)
        query_tokens = _tokens(query)
        scored: list[PolicyRetrievalResult] = []
        for indexed in self._indexed:
            chunk = indexed.chunk
            if status and chunk.status != status:
                continue
            if chunk.effective_date > effective:
                continue
            if category and category not in {chunk.category, *chunk.categories}:
                continue
            vector_score = cosine_similarity(query_embedding, indexed.embedding)
            overlap = len(query_tokens & _tokens(chunk.searchable_text))
            exact_phrase_bonus = 0.2 if query.lower() in chunk.searchable_text.lower() else 0.0
            category_bonus = _category_intent_bonus(query_tokens, chunk)
            section_bonus = _section_intent_bonus(query_tokens, chunk)
            score = vector_score + (overlap * 0.04) + exact_phrase_bonus + category_bonus + section_bonus
            scored.append(PolicyRetrievalResult(chunk=chunk, score=score))
        scored.sort(key=lambda result: (result.score, result.chunk.policy_file, result.chunk.section_title), reverse=True)
        return scored[:limit]


def build_policy_vector_index(
    policy_dir: Path = POLICY_DIR,
    provider: Optional[EmbeddingProvider] = None,
) -> PolicyVectorIndex:
    documents = load_policy_documents(policy_dir)
    chunks = chunk_policy_documents(documents)
    return PolicyVectorIndex(chunks, provider=provider)
