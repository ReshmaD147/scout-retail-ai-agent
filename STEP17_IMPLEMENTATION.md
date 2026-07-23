# Step 17 — Read-only Order Agent

## Scope completed

Step 17 reuses Step 16's `orders`, `order_items`, `payments`, and
`inventory_reservations` records. It adds a read-only specialist path for:

- Order lookup by explicit order ID
- Latest-order lookup for the current shopping session
- Order and payment status
- Pickup or delivery details
- Persisted carrier tracking when available
- Estimated pickup readiness or delivery arrival
- Cancellation, return, and exchange eligibility checks

No cancellation, return, exchange, refund, or other protected write is
implemented.

## Architecture

```text
React chat UI
→ POST /chat or /chat/stream
→ understand_request
→ Supervisor
→ Order Agent
→ approved MCP order tool
→ deterministic Order Service
→ Order Repository
→ SQLite
```

Only `OrderRepository` executes SQL. The Order Agent calls approved MCP tools
and never queries SQLite directly.

## Database change

`order_fulfillments` stores mutable fulfillment facts separately from the
immutable Step 16 order snapshot:

- processing / ready_for_pickup / shipped / delivered / picked_up
- carrier and tracking number/URL
- estimated pickup/delivery times
- shipped, delivered, and picked-up timestamps

Newly confirmed Step 17 orders automatically receive a processing fulfillment
record and a configured estimate. Older orders without that row receive a safe
configured fallback; Scout does not invent carrier tracking.

## API

```text
GET /orders/latest?session_id=...
GET /orders/{order_id}?session_id=...
GET /orders/{order_id}/status?session_id=...
GET /orders/{order_id}/payment?session_id=...
GET /orders/{order_id}/fulfillment?session_id=...
GET /orders/{order_id}/eligibility?session_id=...
```

Order lookup is session-isolated. A valid order ID from another session returns
a safe not-found response.

## MCP tools

- `lookup_order`
- `lookup_latest_order`
- `get_order_status`
- `get_payment_status`
- `get_fulfillment_details`
- `check_order_eligibility`

## React UI

`OrderStatusCard` displays:

- order and payment status
- item snapshots and total
- pickup store or delivery address
- estimated readiness/arrival
- available tracking facts
- read-only eligibility results

It intentionally renders no cancellation, return, or exchange action button.

## Configuration

```text
ORDER_PICKUP_READY_MINUTES=120
ORDER_CANCELLATION_WINDOW_MINUTES=60
ORDER_RETURN_WINDOW_DAYS=30
ORDER_EXCHANGE_WINDOW_DAYS=30
```

## Main files

### New

- `scout/repositories/order_repository.py`
- `scout/services/order_service.py`
- `scout/mcp/order_tools.py`
- `scout/agents/order_agent.py`
- `scout/api/routes/orders.py`
- `scout/api/schemas/orders.py`
- `web/src/components/OrderStatusCard.tsx`
- `web/src/components/OrderStatusCard.test.tsx`
- Step 17 backend test modules under `tests/test_order_*.py`

### Updated

- database schema, configuration, checkout commit, repository models
- request understanding, Supervisor policy, graph, state, safe events
- chat API schemas/mapping and FastAPI router registration
- React chat types, `App.tsx`, tests, styles, README

## Validation performed in the artifact environment

- Python compilation: passed
- Backend suite: **484 passed**
- TS/TSX syntax parse: passed
- Strict type check for the new order types and `OrderStatusCard`: passed

The container did not have the project's exact MCP/LangGraph packages, so the
backend suite used temporary compatibility shims outside the project folder.
Those shims are not included in this archive. The npm package gateway returned
HTTP 503, so the complete Vitest suite and Vite build could not be executed in
this environment.

Run the final checks in your real project environment:

```bash
python -m pytest -q

cd web
npm install
npm test
npm run build
```

The frontend now contains 51 test cases; confirm all 51 pass locally.

## Browser demo

1. Initialize/upgrade the database:

   ```bash
   python -m scout.database.initialize
   python -m scout.database.seed
   ```

2. Start FastAPI from the project root:

   ```bash
   uvicorn scout.main:app --reload
   ```

3. Start React from `web/`:

   ```bash
   npm run dev
   ```

4. Complete one mock checkout, keep the same browser session open, then search:

   ```text
   Where is my order?
   ```

   You can also ask:

   ```text
   What is the payment status of my order?
   Can I cancel my order?
   Can I return my order?
   Can I exchange my order?
   ```

Scout reports eligibility only and explicitly confirms that no protected action
was performed.
