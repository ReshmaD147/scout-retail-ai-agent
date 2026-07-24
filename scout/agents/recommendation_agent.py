"""The Product Recommendation Agent's two pipeline steps.

`recommendation_agent_node` runs first: it turns the extracted intent
(scout/agents/understand_request.py) into an initial, budget-enforced,
ranked candidate set, using the approved MCP semantic-search tool
(scout/mcp/semantic_search_tools.py, Step 15.5) - never SQL, never an
invented product. Step 15.5 replaced the literal-only
scout.mcp.product_tools.search_products call this node used through
Step 15 with scout.mcp.semantic_search_tools.semantic_search_products,
which still runs that exact same literal path whenever
intent["keyword"] is set (see that tool's module docstring for the
full exact/literal/semantic retrieval order) and only falls back to
meaning-based retrieval when it is not - so every scenario this node
already handled continues to resolve identically, and queries with no
literal keyword match (e.g. "comfortable shoes for standing all day")
now retrieve relevant candidates instead of an unfiltered category
dump.

`rerank_node` runs last, after every fulfillment channel has been
checked (scout/agents/inventory_agent.py): it removes any candidate
with no confirmed sellable stock from any channel, then re-ranks
whatever remains, then caps the result at
`settings.max_recommended_products` (Step 15.5's "return up to 3
verified results" - never padded when fewer valid candidates survive).
This is "Rerank valid products" and "Remove invalid or unavailable
options" from CLAUDE.md's primary example workflow, done together in
one place since both need the same computation (which candidates are
still valid).
"""

from typing import Any, Dict, List

from scout.config import get_settings
from scout.mcp.product_tools import get_promotions, rank_products, search_products
from scout.mcp.semantic_search_tools import semantic_search_products
from scout.orchestration.limits import check_step_budget
from scout.orchestration.state import EvidenceEntry, RetailGraphState, ToolCallTrace, WorkflowError
from scout.services.memory_service import bounded_preference_score
from scout.services.product_relevance_service import filter_relevant_products


def recommendation_agent_node(state: RetailGraphState) -> Dict[str, Any]:
    """Search the catalog for candidates matching the extracted intent."""
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    intent = state.intent or {}
    product_targets = intent.get("product_targets") or []
    if len(product_targets) > 1:
        return _multi_target_recommendation(state, product_targets)

    result = semantic_search_products(
        query_text=state.customer_query,
        keyword=intent.get("keyword"),
        category=intent.get("category"),
        subcategory=intent.get("subcategory"),
        max_price=intent.get("max_price"),
        attributes=intent.get("attribute_filters") or None,
        deals_only=bool(intent.get("deals_only")),
        limit=20,
    )
    search_arguments = {
        "query_text": state.customer_query,
        "keyword": intent.get("keyword"),
        "category": intent.get("category"),
        "subcategory": intent.get("subcategory"),
        "max_price": intent.get("max_price"),
        "attributes": intent.get("attribute_filters") or None,
        "deals_only": bool(intent.get("deals_only")),
        "limit": 20,
    }

    update: Dict[str, Any] = {"step_count": state.step_count + 1}

    if result.error is not None:
        update["errors"] = [
            WorkflowError(
                error_type=result.error.error_type,
                message=result.error.message,
                agent="recommendation",
                step="semantic_search_products",
            )
        ]
        update["product_candidates"] = []
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="semantic_search_products",
                status="error",
                summary=result.error.message,
                validated_arguments=search_arguments,
            )
        ]
        return update

    relevant_products, relevance_results = filter_relevant_products(result.products, intent, state.customer_query)
    relevance_evidence = [
        EvidenceEntry(
            source="product_relevance_service",
            claim=(
                f"{item.product_id} {'passed' if item.passed else 'failed'} deterministic relevance validation"
            ),
            data=item.model_dump(),
        )
        for item in relevance_results
    ]

    if not relevant_products:
        update["product_candidates"] = []
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="semantic_search_products",
                status="success",
                summary=(
                    f"no products matched via {result.retrieval_method} "
                    f"({result.candidates_considered} candidate(s) considered)"
                ),
                validated_arguments=search_arguments,
            )
        ]
        update["evidence"] = relevance_evidence
        return update

    rank_arguments = {"product_ids": [product.product_id for product in relevant_products]}
    ranked = rank_products(rank_arguments["product_ids"])
    candidates = [entry.product for entry in ranked.ranked_products]

    update["product_candidates"] = candidates
    tool_results = [
        ToolCallTrace(
            tool_name="semantic_search_products",
            status="success",
            summary=(
                f"found {len(result.products)} candidate(s) within budget via "
                f"{result.retrieval_method} ({result.candidates_considered} candidate(s) considered)"
            ),
            validated_arguments=search_arguments,
        ),
        ToolCallTrace(
            tool_name="rank_products",
            status="success",
            summary=f"ranked {len(candidates)} candidate(s)",
            validated_arguments=rank_arguments,
        ),
    ]
    evidence = [
        EvidenceEntry(
            source="semantic_search_products",
            claim=f"{product.name} ({product.product_id}) is priced at ${product.price:.2f}",
            data=product.model_dump(),
        )
        for product in candidates
    ] + relevance_evidence
    if intent.get("deals_only"):
        for product in candidates:
            promotions = get_promotions(product_id=product.product_id)
            if promotions.error is not None:
                continue
            valid_promotions = [promotion for promotion in promotions.promotions if promotion.is_currently_valid]
            for promotion in valid_promotions:
                evidence.append(
                    EvidenceEntry(
                        source="get_promotions",
                        claim=(
                            f"{product.name} ({product.product_id}) has verified active promotion "
                            f"{promotion.label} ({promotion.promotion_id})"
                        ),
                        data=promotion.model_dump(),
                    )
                )
            tool_results.append(
                ToolCallTrace(
                    tool_name="get_promotions",
                    status="success",
                    summary=f"verified {len(valid_promotions)} active promotion(s) for {product.product_id}",
                )
            )

    update["tool_results"] = tool_results
    update["evidence"] = evidence
    return update


def _multi_target_recommendation(state: RetailGraphState, product_targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    intent = state.intent or {}
    update: Dict[str, Any] = {"step_count": state.step_count + 1}
    all_candidates = []
    tool_results = []
    evidence = []
    product_groups = []
    missing_targets = []
    seen_product_ids: set[str] = set()

    for index, target in enumerate(product_targets, start=1):
        label = str(target.get("label") or target.get("query_text") or f"item {index}")
        search_arguments = {
            "query_text": target.get("query_text") or label,
            "keyword": target.get("keyword"),
            "category": target.get("category"),
            "subcategory": target.get("subcategory"),
            "max_price": intent.get("max_price"),
            "attributes": intent.get("attribute_filters") or None,
            "deals_only": bool(intent.get("deals_only")),
            "limit": 10,
        }
        result = semantic_search_products(**search_arguments)
        if result.error is not None:
            missing_targets.append({"label": label, "reason": result.error.message})
            tool_results.append(
                ToolCallTrace(
                    tool_name="semantic_search_products",
                    status="error",
                    summary=result.error.message,
                    validated_arguments=search_arguments,
                )
            )
            continue
        relevant_products, relevance_results = filter_relevant_products(result.products, {**intent, **target}, str(target.get("query_text") or label))
        evidence.extend(
            EvidenceEntry(
                source="product_relevance_service",
                claim=f"{item.product_id} {'passed' if item.passed else 'failed'} deterministic relevance validation for target {label!r}",
                data={**item.model_dump(), "target_label": label},
            )
            for item in relevance_results
        )

        if not relevant_products and search_arguments.get("category"):
            fallback = search_products(
                category=search_arguments.get("category"),
                max_price=search_arguments.get("max_price"),
                limit=20,
            )
            if fallback.error is None and fallback.products:
                relevant_products, fallback_relevance = filter_relevant_products(
                    fallback.products,
                    {**intent, **target},
                    str(target.get("query_text") or label),
                )
                evidence.extend(
                    EvidenceEntry(
                        source="product_relevance_service",
                        claim=f"{item.product_id} {'passed' if item.passed else 'failed'} fallback relevance validation for target {label!r}",
                        data={**item.model_dump(), "target_label": label, "fallback": True},
                    )
                    for item in fallback_relevance
                )
                tool_results.append(
                    ToolCallTrace(
                        tool_name="search_products",
                        status="success",
                        summary=f"fallback category search considered {len(fallback.products)} product(s) for target {label!r}",
                        validated_arguments={
                            "category": search_arguments.get("category"),
                            "max_price": search_arguments.get("max_price"),
                            "limit": 20,
                        },
                    )
                )

        if not relevant_products:
            missing_targets.append({"label": label, "reason": "No verified catalog product matched this part of the request."})
            tool_results.append(
                ToolCallTrace(
                    tool_name="semantic_search_products",
                    status="success",
                    summary=f"no products matched target {label!r}",
                    validated_arguments=search_arguments,
                )
            )
            continue

        ranked = rank_products([product.product_id for product in relevant_products])
        target_products = []
        for entry in ranked.ranked_products:
            if entry.product.product_id in seen_product_ids:
                continue
            seen_product_ids.add(entry.product.product_id)
            target_products.append(entry.product)
            all_candidates.append(entry.product)
            break

        if target_products:
            product_groups.append(
                {
                    "target_label": label,
                    "products": [product.model_dump() for product in target_products],
                    "missing": False,
                    "message": None,
                }
            )
            for product in target_products:
                evidence.append(
                    EvidenceEntry(
                        source="semantic_search_products",
                        claim=f"{product.name} ({product.product_id}) matched requested item {label!r} and is priced at ${product.price:.2f}",
                        data={**product.model_dump(), "target_label": label},
                    )
                )
        else:
            missing_targets.append({"label": label, "reason": "Only duplicate products matched this part of the request."})

        tool_results.append(
            ToolCallTrace(
                tool_name="semantic_search_products",
                status="success",
                summary=f"found {len(result.products)} candidate(s) for target {label!r}",
                validated_arguments=search_arguments,
            )
        )

    for missing in missing_targets:
        product_groups.append(
            {
                "target_label": missing["label"],
                "products": [],
                "missing": True,
                "message": missing["reason"],
            }
        )

    update["product_candidates"] = all_candidates
    update["product_groups"] = product_groups
    update["missing_product_targets"] = missing_targets
    update["tool_results"] = tool_results
    update["evidence"] = evidence
    return update


def rerank_node(state: RetailGraphState) -> Dict[str, Any]:
    """Drop candidates with no confirmed stock anywhere, rerank the
    rest, then cap at the configured maximum recommended products."""
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    update: Dict[str, Any] = {"step_count": state.step_count + 1}

    fulfilled_ids = {
        entry["product_id"] for entry in state.inventory_results if entry.get("sellable_quantity", 0) > 0
    }
    survivors = [candidate for candidate in state.product_candidates if candidate.product_id in fulfilled_ids]

    if not survivors:
        update["product_candidates"] = []
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="rank_products",
                status="success",
                summary="no candidate had confirmed fulfillment; nothing to rerank",
            )
        ]
        return update

    max_recommended = get_settings().max_recommended_products
    ranked = rank_products([candidate.product_id for candidate in survivors])
    rank_arguments = {"product_ids": [candidate.product_id for candidate in survivors], "phase": "fulfillment_rerank"}
    ranked_candidates = [entry.product for entry in ranked.ranked_products]
    if state.user_id:
        base_position = {product.product_id: index for index, product in enumerate(ranked_candidates)}
        preference_scores = {
            product.product_id: bounded_preference_score(product.product_id, state.user_id)
            for product in ranked_candidates
        }
        ranked_candidates = sorted(
            ranked_candidates,
            key=lambda product: (
                base_position[product.product_id] - preference_scores[product.product_id],
                product.product_id,
            ),
        )
        ranked_candidates = [
            product.model_copy(update={"memory_influence": "Ranked slightly higher because it matches a saved preference."})
            if preference_scores.get(product.product_id, 0) > 0
            else product
            for product in ranked_candidates
        ]
    final_candidates = ranked_candidates[:max_recommended]
    update["product_candidates"] = final_candidates
    if state.product_groups:
        final_ids = {candidate.product_id for candidate in final_candidates}
        updated_groups = []
        for group in state.product_groups:
            products = [product for product in group.get("products", []) if product.get("product_id") in final_ids]
            if products:
                updated_groups.append({**group, "products": products, "missing": False, "message": None})
            else:
                updated_groups.append(
                    {
                        **group,
                        "products": [],
                        "missing": True,
                        "message": group.get("message") or "No fulfillable verified product remained for this part of the request.",
                    }
                )
        update["product_groups"] = updated_groups
    update["tool_results"] = [
        ToolCallTrace(
            tool_name="rank_products",
            status="success",
            summary=(
                f"reranked {len(survivors)} fulfillable candidate(s), "
                f"returning the top {len(final_candidates)}"
            ),
            validated_arguments=rank_arguments,
        )
    ]
    return update
