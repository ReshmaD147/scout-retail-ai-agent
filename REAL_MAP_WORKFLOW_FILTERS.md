# Real Map, Live Workflow, Filters, and Recommendation Fixes

## Scope

This change preserves Scout Steps 1–17 and implements only:

1. A real interactive fulfillment map backed by stored store coordinates.
2. A seven-stage workflow timeline driven by real `/chat/stream` events.
3. Structured filters that rerun the backend recommendation workflow.
4. Exact product-type and active-deal recommendation fixes.
5. Removal of the false selected-store warning for general searches.

Checkout, affiliate fallback, Order Agent, MCP boundaries, LangGraph orchestration, cart behavior, and protected-action restrictions remain intact.

## Customer-visible behavior

### Fulfillment map

- Uses React Leaflet and Leaflet.
- Plots the requested area when the backend resolves one.
- Plots selected and nearby Scout stores using the latitude and longitude already stored in SQLite.
- Uses green markers for verified stock and red markers for out-of-stock stores.
- Marker popups show store name, city/state, stock, and distance when available.
- Fits the viewport to the visible requested location and store markers.
- Draws a dashed visual connection to the nearest available store.
- Explicitly states that the dashed line is not a driving route.

### Workflow timeline

The UI now displays only these canonical stages:

1. Understanding request
2. Creating shopping plan
3. Searching catalog
4. Checking selected store
5. Checking nearby stores
6. Comparing options
7. Preparing response

The stages are updated from actual SSE event types, tool names, and node names. Repeated backend events replace the existing stage entry instead of creating duplicate customer-visible lines. Completed workflows collapse the progress card while retaining a Show progress control.

### Working filters

The right panel loads filter metadata from `GET /catalog/filter-options` and can apply:

- Maximum price
- Category
- Product type/subcategory
- Verified product attributes
- Verified in-stock results
- Pickup or delivery preference

Applying a filter sends a structured `filters` object back to `/chat/stream`, causing the real backend graph to run again. React does not decide which products are eligible.

### Recommendation corrections

- `Wireless earbuds` is hard-filtered to the `Earbuds` subcategory.
- Chargers and power banks cannot be inserted merely to reach three products.
- Scout returns one or two products when only one or two valid products survive.
- `Coffee maker deals` requires both the `Coffee Makers` subcategory and a currently valid promotion.
- Unrelated promoted products such as lamps are rejected.
- When a deal request has no valid promoted product, Scout returns an honest deal-specific no-results message.
- A general search without pickup, location, or selected store no longer creates the customer-facing error `No store was resolved to check pickup inventory against`.
- “Why these?” content is generated only from verified product, price, promotion, and inventory evidence.

## Backend changes

### Added

- `scout/api/routes/catalog.py`
- `scout/api/schemas/catalog.py`
- `scout/services/catalog_filter_service.py`
- `tests/test_catalog_filters_api.py`
- `tests/test_recommendation_regressions.py`

### Updated

- `scout/agents/inventory_agent.py`
- `scout/agents/recommendation_agent.py`
- `scout/agents/response_verification.py`
- `scout/agents/understand_request.py`
- `scout/api/app.py`
- `scout/api/routes/chat.py`
- `scout/api/routes/chat_stream.py`
- `scout/api/routes/stores.py`
- `scout/api/schemas/chat.py`
- `scout/api/schemas/stores.py`
- `scout/mcp/product_tools.py`
- `scout/mcp/schemas.py`
- `scout/mcp/semantic_search_tools.py`
- `scout/mcp/summaries.py`
- `scout/orchestration/events.py`
- `scout/orchestration/rule_based_policy.py`
- `scout/orchestration/state.py`
- `scout/services/product_filter_service.py`
- `scout/services/product_search_service.py`
- Related existing backend tests

## Frontend changes

### Added

- `web/src/api/catalogClient.ts`
- `web/src/hooks/useCatalogFilters.ts`
- `web/src/types/catalog.ts`
- `web/src/components/FulfillmentMap.tsx`
- `web/src/components/FulfillmentMap.test.tsx`
- `web/src/components/ProductFilters.test.tsx`

### Updated

- `web/package.json`
- `web/package-lock.json`
- `web/src/App.tsx`
- `web/src/App.test.tsx`
- `web/src/App.cart.test.tsx`
- `web/src/PremiumLayout.test.tsx`
- `web/src/components/AgentActivity.tsx`
- `web/src/components/AgentActivity.test.tsx`
- `web/src/components/FulfillmentSummary.tsx`
- `web/src/components/FulfillmentSummary.test.tsx`
- `web/src/components/ProductCard.tsx`
- `web/src/components/ProductFilters.tsx`
- `web/src/hooks/useScoutChat.ts`
- `web/src/main.tsx`
- `web/src/styles.css`
- `web/src/types/cart.ts`
- `web/src/types/chat.ts`

## Architecture boundaries preserved

- React collects filter selections and renders verified data only.
- FastAPI validates structured requests and returns API schemas.
- LangGraph continues to coordinate the workflow.
- Agents call approved MCP tools/services rather than raw SQL.
- Repositories remain the only application layer executing SQL.
- Price, category, product type, promotions, attributes, stock, and fulfillment are enforced deterministically.
- No fake store, stock, product, attribute, promotion, or route data was added.

## Validation completed in the artifact environment

### Backend

```text
Python compilation: passed
Pytest: 494 passed, 0 failed
```

The complete backend suite was executed with temporary compatibility shims for MCP/LangGraph/LangChain packages that were unavailable in the artifact environment. The shims are not included in the project ZIP. Run the suite in Scout's real `.venv` before merging.

### Frontend

```text
TypeScript/TSX static source and test check: passed
CSS parse: 466 rules, 0 errors
Frontend tests present: 15 files, 69 tests
package-lock dependency entries and JSON structure: passed
```

The full Vitest and Vite build could not be executed in the artifact environment because the npm package gateway returned HTTP 503 while downloading transitive packages. Run these locally:

```bash
cd web
npm install
npm test
npm run build
npm run dev
```

## Local test queries

Use these browser queries after starting FastAPI and React:

```text
Wireless earbuds
Coffee maker deals
Find comfortable work shoes under $100 that I can pick up today near Maple Grove.
```

Expected checks:

- Earbud results contain only the Earbuds product type and may contain fewer than three products.
- Coffee maker deals contain only promoted coffee makers.
- The pickup query displays the requested area and resolved stores on the real map.
- The workflow progresses once per canonical stage with no repeated raw activity list.
- Applying filters sends a new backend request and changes only verified results.
