"""Scout's approved MCP product tools.

Why agents get tools instead of direct database access
--------------------------------------------------------
An agent (Step 9+) never imports a repository or a service, and never
sees SQL. It only ever calls one of the five functions below. That
boundary buys three things a direct database connection cannot:

1. Validated, structured input. Every tool checks its own arguments
   (ranges, non-empty strings, date formats) and returns a structured
   ToolError instead of letting a bad argument reach the database or
   raise an unhandled exception into the agent.
2. Validated, structured output. Every tool returns one of the
   *Result Pydantic models in schemas.py - never a raw row, a raw SQL
   result, or free text a model could embellish. There is no code path
   here that invents a product, price, or promotion: every field in
   every response was read from a repository or computed by a
   deterministic service (scout.services.*), never guessed.
3. A fixed, auditable capability list. A tool can only do exactly what
   its implementation does - "search products," not "run any query."
   An agent with database access could run arbitrary SQL; an agent with
   these five tools cannot exceed what search_products,
   get_product_details, get_promotions, rank_products, and
   find_similar_products are each explicitly written to do.

Each tool is registered on a FastMCP server (the official `mcp` Python
SDK) so it has a real MCP tool name, description, and JSON Schema
derived directly from its Python signature and return type - not a
hand-written spec that could drift from the implementation. Decorated
functions remain plain, directly callable Python functions, which is
how tests in this phase call them (no running MCP server, no
LangGraph).
"""

from datetime import date
from typing import List, Optional

from scout.mcp.errors import ToolValidationError
from scout.mcp.schemas import (
    FindSimilarProductsResult,
    GetProductDetailsResult,
    GetPromotionsResult,
    ProductDetail,
    PromotionSummary,
    RankedProductSummary,
    RankProductsResult,
    SearchProductsResult,
    ToolError,
)
from scout.mcp.server import mcp_server
from scout.mcp.summaries import product_to_summary
from scout.repositories.models import Product
from scout.repositories.product_repository import ProductRepository
from scout.repositories.promotion_repository import PromotionRepository
from scout.services import budget_service, promotion_service, ranking_service, similarity_service

_MAX_LIMIT = 100
_MAX_RANK_PRODUCT_IDS = 50
_MAX_SIMILAR_LIMIT = 50


def _to_detail(product: Product) -> ProductDetail:
    return ProductDetail(
        **product_to_summary(product).model_dump(),
        description=product.description,
        attributes=product.attributes,
        image_url=product.image_url,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


@mcp_server.tool()
def search_products(
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    max_price: Optional[float] = None,
    min_rating: Optional[float] = None,
    limit: int = 20,
    offset: int = 0,
) -> SearchProductsResult:
    """Search the Scout product catalog using safe, parameterized filters.

    Input schema (all optional except none are required):
        keyword: Case-insensitive substring matched against a
            product's name or description.
        category: Exact category name (e.g. "Footwear").
        brand: Exact brand name.
        max_price: Maximum price, inclusive.
        min_rating: Minimum rating (0-5), inclusive.
        limit: Maximum rows to return (1-100, default 20).
        offset: Rows to skip, for pagination (>= 0, default 0).

    Output schema: SearchProductsResult(products, count, error).

    Validation: limit must be between 1 and 100; offset must not be
    negative; max_price, if given, must not be negative; min_rating,
    if given, must be between 0 and 5. Any violation returns
    error.error_type == "validation_error" with products == [].

    Repository/service called: ProductRepository.search() runs the
    parameterized SQL query. If max_price was supplied, the results
    are re-checked with budget_service.filter_within_budget() as a
    second, independent enforcement of the budget - a defensive layer
    that never trusts a single point of enforcement for a hard
    customer constraint.
    """
    try:
        if not (1 <= limit <= _MAX_LIMIT):
            raise ToolValidationError(f"limit must be between 1 and {_MAX_LIMIT}")
        if offset < 0:
            raise ToolValidationError("offset must not be negative")
        if max_price is not None and max_price < 0:
            raise ToolValidationError("max_price must not be negative")
        if min_rating is not None and not (0 <= min_rating <= 5):
            raise ToolValidationError("min_rating must be between 0 and 5")
    except ToolValidationError as exc:
        return SearchProductsResult(
            products=[], count=0, error=ToolError(error_type="validation_error", message=str(exc))
        )

    products = ProductRepository().search(
        keyword=keyword,
        category=category,
        brand=brand,
        max_price=max_price,
        min_rating=min_rating,
        limit=limit,
        offset=offset,
    )

    if max_price is not None:
        products = budget_service.filter_within_budget(products, max_budget=max_price)

    summaries = [product_to_summary(product) for product in products]
    return SearchProductsResult(products=summaries, count=len(summaries), error=None)


@mcp_server.tool()
def get_product_details(product_id: str) -> GetProductDetailsResult:
    """Retrieve the full catalog record for one product by its ID.

    Input schema:
        product_id: The product's primary key (e.g. "FTW-004").
            Required, must be a non-empty string.

    Output schema: GetProductDetailsResult(product, error). `product`
    is a ProductDetail (full catalog record) when found, otherwise
    None.

    Validation: product_id must be a non-empty string. Violation
    returns error.error_type == "validation_error".

    Error responses: if no product with that ID exists,
    error.error_type == "not_found" and product is None - this tool
    never fabricates a product to fill the gap.

    Repository called: ProductRepository.get_by_id().
    """
    if not product_id or not product_id.strip():
        return GetProductDetailsResult(
            product=None,
            error=ToolError(error_type="validation_error", message="product_id must not be empty"),
        )

    product = ProductRepository().get_by_id(product_id)

    if product is None:
        return GetProductDetailsResult(
            product=None,
            error=ToolError(
                error_type="not_found", message=f"No product found with product_id={product_id!r}"
            ),
        )

    return GetProductDetailsResult(product=_to_detail(product), error=None)


@mcp_server.tool()
def get_promotions(
    product_id: Optional[str] = None,
    as_of_date: Optional[str] = None,
) -> GetPromotionsResult:
    """List promotions and whether each is actually usable right now.

    Input schema:
        product_id: If given, restrict to this product's promotions.
            None returns active-flagged promotions for every product.
        as_of_date: ISO date string ("YYYY-MM-DD") to evaluate
            validity against. None defaults to today.

    Output schema: GetPromotionsResult(promotions, count, error).
    Each PromotionSummary includes both `active` (the raw stored flag)
    and `is_currently_valid` (the reconciled answer, computed by
    scout.services.promotion_service.is_promotion_valid - active AND
    within the promotion's date range as of as_of_date).

    Validation: as_of_date, if given, must parse as an ISO date
    ("YYYY-MM-DD"). An invalid format returns
    error.error_type == "validation_error".

    Repository/service called: PromotionRepository.list_active()
    fetches every promotion whose stored `active` column is 1;
    promotion_service.is_promotion_valid() then reconciles the date
    range for each one. This tool never computes a discounted price -
    that is calculate_price(), used for a specific product elsewhere.
    """
    try:
        resolved_date = date.fromisoformat(as_of_date) if as_of_date is not None else date.today()
    except ValueError:
        return GetPromotionsResult(
            promotions=[],
            count=0,
            error=ToolError(
                error_type="validation_error",
                message=f"as_of_date must be an ISO date (YYYY-MM-DD), got {as_of_date!r}",
            ),
        )

    promotions = PromotionRepository().list_active(product_id=product_id)

    summaries = [
        PromotionSummary(
            promotion_id=promotion.promotion_id,
            product_id=promotion.product_id,
            label=promotion.label,
            discount_percent=promotion.discount_percent,
            discount_amount=promotion.discount_amount,
            start_date=promotion.start_date,
            end_date=promotion.end_date,
            active=promotion.active,
            is_currently_valid=promotion_service.is_promotion_valid(promotion, resolved_date),
        )
        for promotion in promotions
    ]

    return GetPromotionsResult(promotions=summaries, count=len(summaries), error=None)


@mcp_server.tool()
def rank_products(product_ids: List[str]) -> RankProductsResult:
    """Rank a specific set of products deterministically.

    Input schema:
        product_ids: The product IDs to rank (e.g. from a prior
            search_products call). Required, 1-50 items, each a
            non-empty string.

    Output schema: RankProductsResult(ranked_products, count,
    missing_product_ids, error). missing_product_ids lists any
    requested ID that does not exist - those IDs are reported, never
    silently dropped or invented.

    Validation: product_ids must be a non-empty list of at most 50
    non-empty strings. Violation returns
    error.error_type == "validation_error".

    Repository/service called: ProductRepository.get_by_id() resolves
    each ID; scout.services.ranking_service.rank_products() produces
    the deterministic order (rating, then review_count, then price,
    then product_id - see that module for the full tiebreak rule).
    """
    if not product_ids:
        return RankProductsResult(
            ranked_products=[],
            count=0,
            missing_product_ids=[],
            error=ToolError(error_type="validation_error", message="product_ids must not be empty"),
        )
    if len(product_ids) > _MAX_RANK_PRODUCT_IDS:
        return RankProductsResult(
            ranked_products=[],
            count=0,
            missing_product_ids=[],
            error=ToolError(
                error_type="validation_error",
                message=f"product_ids must contain at most {_MAX_RANK_PRODUCT_IDS} items",
            ),
        )
    if any(not product_id or not product_id.strip() for product_id in product_ids):
        return RankProductsResult(
            ranked_products=[],
            count=0,
            missing_product_ids=[],
            error=ToolError(error_type="validation_error", message="product_ids must not contain empty values"),
        )

    repository = ProductRepository()
    found_products: List[Product] = []
    missing_product_ids: List[str] = []

    for product_id in product_ids:
        product = repository.get_by_id(product_id)
        if product is None:
            missing_product_ids.append(product_id)
        else:
            found_products.append(product)

    ranked = ranking_service.rank_products(found_products)

    ranked_summaries = [
        RankedProductSummary(
            rank=entry.rank,
            product=product_to_summary(entry.product),
            rating_component=entry.rating_component,
            review_component=entry.review_component,
            price_component=entry.price_component,
        )
        for entry in ranked
    ]

    return RankProductsResult(
        ranked_products=ranked_summaries,
        count=len(ranked_summaries),
        missing_product_ids=missing_product_ids,
        error=None,
    )


@mcp_server.tool()
def find_similar_products(
    product_id: str,
    limit: int = 5,
    max_price_difference_percent: Optional[float] = 30.0,
) -> FindSimilarProductsResult:
    """Find catalog products similar to a reference product.

    "Similar" is defined deterministically, with no vector search or
    model involved: same category as the reference product, within
    max_price_difference_percent of its price (when given), excluding
    the reference product itself, ordered by scout.services.
    ranking_service.rank_products(). This is a catalog-level
    similarity search meant to work before any vector retrieval exists
    - and per scout/database/schema.sql, even once vector search is
    added later it will only ever propose candidates, never override
    this repository/service layer as the source of truth.

    Input schema:
        product_id: The reference product's ID. Required.
        limit: Maximum number of similar products to return (1-50,
            default 5).
        max_price_difference_percent: Maximum allowed price difference
            from the reference product's price, as a percent (default
            30.0). None disables the price filter entirely.

    Output schema: FindSimilarProductsResult(reference_product_id,
    similar_products, count, error).

    Validation: product_id must be non-empty; limit must be between 1
    and 50; max_price_difference_percent, if given, must not be
    negative.

    Error responses: if the reference product_id does not exist,
    error.error_type == "not_found" and similar_products is empty.

    Repository/service called: ProductRepository.get_by_id() and
    ProductRepository.list_active() fetch candidates;
    similarity_service.filter_similar_candidates() applies the
    category/price-band filter (the same shared function
    find_available_substitutes in scout/mcp/inventory_tools.py calls
    directly, rather than calling this tool); ranking_service.
    rank_products() orders the result.
    """
    if not product_id or not product_id.strip():
        return FindSimilarProductsResult(
            reference_product_id=product_id,
            similar_products=[],
            count=0,
            error=ToolError(error_type="validation_error", message="product_id must not be empty"),
        )
    if not (1 <= limit <= _MAX_SIMILAR_LIMIT):
        return FindSimilarProductsResult(
            reference_product_id=product_id,
            similar_products=[],
            count=0,
            error=ToolError(
                error_type="validation_error",
                message=f"limit must be between 1 and {_MAX_SIMILAR_LIMIT}",
            ),
        )
    if max_price_difference_percent is not None and max_price_difference_percent < 0:
        return FindSimilarProductsResult(
            reference_product_id=product_id,
            similar_products=[],
            count=0,
            error=ToolError(
                error_type="validation_error",
                message="max_price_difference_percent must not be negative",
            ),
        )

    repository = ProductRepository()
    reference = repository.get_by_id(product_id)

    if reference is None:
        return FindSimilarProductsResult(
            reference_product_id=product_id,
            similar_products=[],
            count=0,
            error=ToolError(
                error_type="not_found", message=f"No product found with product_id={product_id!r}"
            ),
        )

    candidates = repository.list_active(category=reference.category)
    candidates = similarity_service.filter_similar_candidates(
        reference, candidates, max_price_difference_percent
    )

    ranked = ranking_service.rank_products(candidates)[:limit]
    summaries = [product_to_summary(entry.product) for entry in ranked]

    return FindSimilarProductsResult(
        reference_product_id=product_id,
        similar_products=summaries,
        count=len(summaries),
        error=None,
    )
