"""Deterministic product search orchestration (Step 15.5).

The single entry point every caller uses - scout/mcp/semantic_search_tools.py's
`semantic_search_products` tool, and nothing else - to turn one natural-
language query into a ranked, valid candidate set. This module owns the
retrieval *strategy*; it performs no SQL itself (ProductRepository does
that) and no embedding math itself (scout/services/embedding_service.py
does that) - see scout/repositories/__init__.py and this codebase's
existing service-layer convention for why that separation matters.

Retrieval strategy, in order (a "hybrid" search - CLAUDE.md's Step 15.5)
--------------------------------------------------------------------------
1. Exact match (_exact_match): a literal product_id, brand, product
   name, or color mentioned in the query always wins outright and
   skips every other strategy below - Step 15.5's "preserve exact
   matching for product IDs, brands, models, and colors." A customer
   asking for "the FTW-004" or "Aria earbuds" or "the blue speaker"
   must get exactly that, never a semantically-similar substitute
   instead.
2. Literal keyword (unchanged since Step 5): if
   scout.agents.understand_request.understand_request_node already
   extracted a narrow descriptor keyword (e.g. "running", "work"), the
   original ProductRepository.search(keyword=...) LIKE-based path runs
   exactly as it always has - preserves every existing test and
   behavior built on that narrow, literal matching.
3. Semantic (new): only reached when neither of the above found
   anything to go on. The query text is embedded
   (scout.services.embedding_service) and compared by cosine similarity
   against every active (optionally category-filtered) product's own
   embedding, retrieving the configured number of most-relevant
   candidates by meaning (scout.config.Settings.semantic_search_candidate_limit,
   10-20) rather than zero results or an unfiltered category dump.

Every path funnels through the same deterministic filters afterward -
scout.services.budget_service.filter_within_budget and
scout.services.product_filter_service.filter_products(active_only=True)
- and the same scout.services.ranking_service.rank_products() ordering,
so "how a candidate was found" never changes the rules for "is this
candidate valid" or "how are valid candidates ordered." Inventory
validity is deliberately NOT checked here - that is
scout.agents.inventory_agent's job, run later in the graph
(scout/orchestration/graph.py); duplicating it here would be exactly
the kind of duplicate service CLAUDE.md and this phase's own
instructions warn against.
"""

import re
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from scout.config import get_settings
from scout.repositories.embedding_repository import EmbeddingRepository
from scout.repositories.models import Product
from scout.repositories.product_repository import ProductRepository
from scout.services import budget_service, product_filter_service, ranking_service
from scout.services.embedding_service import EmbeddingProvider, cosine_similarity, get_embedding_provider
from scout.services.product_search_text_service import build_search_text, hash_search_text

RetrievalMethod = Literal[
    "exact_product_id", "exact_brand", "exact_name", "exact_color", "literal_keyword", "semantic"
]

_PRODUCT_ID_PATTERN = re.compile(r"\b[A-Za-z]{2,5}-\d{2,5}\b")
_LARGE_CATALOG_LIMIT = 1000
"""Large enough to fetch this catalog's entire active product set in one
call - scout/repositories/product_repository.py's list_active() always
requires a limit, and this demo catalog (scout/database/seed.py) is far
smaller than this number."""


class ProductSearchOutcome(BaseModel):
    """The result of one search_products_by_meaning() call."""

    products: List[Product]
    retrieval_method: RetrievalMethod
    candidates_considered: int
    """How many candidates the winning strategy actually evaluated
    before deterministic filtering/ranking - for "semantic", this is
    the size of the embedding comparison pool (Step 15.5's "initial
    retrieval considers more than three candidates"); for the other
    methods, the size of the matched row set before ranking."""


def _finalize(
    candidates: List[Product], category: Optional[str], max_price: Optional[float]
) -> List[Product]:
    """Apply the same deterministic filters and ranking every retrieval
    strategy must go through, regardless of how candidates were found."""
    filtered = product_filter_service.filter_products(candidates, category=category, active_only=True)
    if max_price is not None:
        filtered = budget_service.filter_within_budget(filtered, max_budget=max_price)
    return [entry.product for entry in ranking_service.rank_products(filtered)]


def _exact_match(query_text: str, pool: List[Product]) -> Optional[Tuple[List[Product], RetrievalMethod]]:
    """Check every exact-match rule, in priority order.

    Args:
        query_text: The raw customer query.
        pool: The active (optionally category-prefiltered) candidate
            pool already fetched by the caller, reused here so this
            function never issues its own database query.

    Returns:
        (matches, retrieval_method), or None if nothing matched
        exactly - never a partial/fuzzy result; every branch here
        requires an exact (case-insensitive) equality or a real
        product_id lookup.
    """
    id_match = _PRODUCT_ID_PATTERN.search(query_text)
    if id_match:
        product = ProductRepository().get_by_id(id_match.group(0).upper())
        if product is not None and product.active:
            return [product], "exact_product_id"

    query_lower = query_text.lower()

    brands = {product.brand.lower(): product.brand for product in pool}
    for brand_lower, brand in brands.items():
        if re.search(rf"\b{re.escape(brand_lower)}\b", query_lower):
            matches = [product for product in pool if product.brand == brand]
            if matches:
                return matches, "exact_brand"

    for product in pool:
        if product.name.lower() in query_lower:
            return [product], "exact_name"

    colors: Dict[str, str] = {}
    for product in pool:
        color = product.attributes.get("color")
        if color:
            colors[str(color).lower()] = str(color)
    for color_lower, color in colors.items():
        if re.search(rf"\b{re.escape(color_lower)}\b", query_lower):
            matches = [
                product for product in pool if str(product.attributes.get("color", "")).lower() == color_lower
            ]
            if matches:
                return matches, "exact_color"

    return None


def ensure_current_embedding(
    product: Product,
    provider: EmbeddingProvider,
    embedding_repo: EmbeddingRepository,
    stored: Dict[str, object],
) -> List[float]:
    """Return a current embedding for `product`, computing and storing a
    fresh one only if none is stored yet or it is stale (Step 15.5's
    "precompute and reuse"). Shared by the semantic search path below
    and by scout/database/build_product_embeddings.py's batch
    precompute script, so there is exactly one staleness rule.

    Args:
        stored: A dict of already-fetched ProductEmbedding rows, keyed
            by product_id (scout.repositories.embedding_repository.
            EmbeddingRepository.get_for_product_ids) - passed in so a
            caller embedding many products only queries the database
            once, not once per product.
    """
    search_text = build_search_text(product)
    text_hash = hash_search_text(search_text)
    existing = stored.get(product.product_id)

    if (
        existing is not None
        and existing.model_name == provider.model_name  # type: ignore[union-attr]
        and existing.search_text_hash == text_hash  # type: ignore[union-attr]
    ):
        return existing.embedding  # type: ignore[union-attr]

    vector = provider.embed(search_text)
    embedding_repo.upsert(
        product_id=product.product_id,
        model_name=provider.model_name,
        embedding=vector,
        search_text_hash=text_hash,
    )
    return vector


def _semantic_candidates(
    query_text: str,
    pool: List[Product],
    provider: EmbeddingProvider,
    candidate_limit: int,
    min_similarity: float,
) -> List[Product]:
    """Retrieve the most relevant candidates from `pool` by meaning."""
    embedding_repo = EmbeddingRepository()
    stored = embedding_repo.get_for_product_ids([product.product_id for product in pool])

    query_vector = provider.embed(query_text)

    scored: List[Tuple[Product, float]] = []
    for product in pool:
        vector = ensure_current_embedding(product, provider, embedding_repo, stored)
        score = cosine_similarity(query_vector, vector)
        if score > min_similarity:
            scored.append((product, score))

    scored.sort(key=lambda pair: (-pair[1], pair[0].product_id))
    return [product for product, _score in scored[:candidate_limit]]


def search_products_by_meaning(
    query_text: str,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    max_price: Optional[float] = None,
    provider: Optional[EmbeddingProvider] = None,
) -> ProductSearchOutcome:
    """Search the catalog for candidates matching `query_text`.

    Args:
        query_text: The customer's raw natural-language request (Step
            15.5's semantic input) - e.g. state.customer_query.
        keyword: A narrow literal descriptor already extracted by
            scout.agents.understand_request (unchanged Step 5
            behavior) - when given, takes priority over semantic
            retrieval (see module docstring).
        category: Exact category to require, if the customer's intent
            already resolved one.
        max_price: The customer's budget ceiling, if stated.
        provider: Override the configured embedding provider - tests
            pass a HashingEmbeddingProvider or a fake directly instead
            of depending on scout.config settings.

    Returns:
        A ProductSearchOutcome. `products` is always already filtered
        (active, category, budget) and ranked - the caller never needs
        to re-apply any of those rules.
    """
    active_provider = provider or get_embedding_provider()

    pool = ProductRepository().list_active(category=category, limit=_LARGE_CATALOG_LIMIT)

    exact = _exact_match(query_text, pool)
    if exact is not None:
        matches, method = exact
        finalized = _finalize(matches, category=category, max_price=max_price)
        return ProductSearchOutcome(
            products=finalized, retrieval_method=method, candidates_considered=len(matches)
        )

    if keyword:
        literal_matches = ProductRepository().search(
            keyword=keyword, category=category, max_price=max_price, limit=_LARGE_CATALOG_LIMIT
        )
        finalized = _finalize(literal_matches, category=category, max_price=max_price)
        return ProductSearchOutcome(
            products=finalized,
            retrieval_method="literal_keyword",
            candidates_considered=len(literal_matches),
        )

    settings = get_settings()
    semantic_matches = _semantic_candidates(
        query_text,
        pool,
        active_provider,
        candidate_limit=settings.semantic_search_candidate_limit,
        min_similarity=settings.semantic_search_min_similarity,
    )
    finalized = _finalize(semantic_matches, category=category, max_price=max_price)
    return ProductSearchOutcome(
        products=finalized, retrieval_method="semantic", candidates_considered=len(pool)
    )