# Retail AI Assistant (Scout) — Backend

Step 1 foundation: a FastAPI application with centralized configuration,
structured logging, centralized exception handling, and a `/health`
endpoint.

Step 2 adds a small SQLite retail database (products, stores, inventory,
promotions) that later steps will build on. No repositories, services,
LLM, agent, or frontend logic yet.

> **Synthetic data notice:** every product, brand, price, store,
> inventory quantity, and promotion in this database is fictional
> demonstration data created for development and testing. None of it
> represents a real retailer, real product, real store, or real price.

## Setup

Requires **Python 3.10 or newer** (the official MCP SDK used in Step 6
requires 3.10+; earlier steps worked on 3.9, this one does not).

Create and activate a virtual environment, then install dependencies.
If your existing `.venv` was created with an older Python, delete it
and recreate it with `python3.10` (or newer) first.

```bash
python3.10 -m venv .venv          # use 3.10+ specifically
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Copy the example environment file and adjust if needed:

```bash
cp .env.example .env
```

## Run the API

```bash
uvicorn scout.main:app --reload
```

Visit `http://localhost:8000/health` — expect a JSON body like:

```json
{
  "status": "ok",
  "timestamp": "2026-07-21T12:00:00+00:00",
  "app_name": "Retail AI Assistant (Scout)",
  "version": "0.1.0"
}
```

Interactive API docs: `http://localhost:8000/docs`

## Database (SQLite)

The database path comes from centralized configuration (`DATABASE_PATH`
in `.env`, default `data/scout.db`). Run these from the repo root, with
the virtual environment active.

Initialize the schema (creates catalog, inventory, cart, semantic-search,
checkout, payment, order, reservation, fulfillment-tracking, and affiliate
tables — safe to run repeatedly):

```bash
python -m scout.database.initialize
```

Seed synthetic demo data (30 products, 5 stores, inventory, promotions —
safe to run repeatedly; it will not create duplicates):

```bash
python -m scout.database.seed
```

Inspect the data with the SQLite CLI:

```bash
sqlite3 data/scout.db
.tables
SELECT product_id, name, category, price FROM products LIMIT 5;
SELECT store_name, city FROM stores;
SELECT * FROM inventory WHERE store_id = 'STR-001' LIMIT 5;
SELECT * FROM promotions WHERE active = 1;
.quit
```

Or with Python:

```bash
python -c "
from scout.database.connection import connection_scope
with connection_scope() as conn:
    for row in conn.execute('SELECT product_id, name, price FROM products LIMIT 5'):
        print(dict(row))
"
```

## MCP product tools

Five approved, structured tools live in `scout/mcp/product_tools.py`,
registered on a FastMCP server instance (`mcp_server`) from the
official `mcp` SDK: `search_products`, `get_product_details`,
`get_promotions`, `rank_products`, `find_similar_products`. Each is a
plain Python function under the hood - call it directly, no running
MCP server or LangGraph required:

```bash
python -c "
from scout.mcp.product_tools import search_products
result = search_products(category='Footwear', max_price=100)
print(result.count, 'products found')
for p in result.products:
    print(' ', p.product_id, p.name, p.price)
"
```

Every tool returns a structured Pydantic result (never free text) and
never invents a product, price, or promotion - a missing record comes
back as a structured `not_found` error, never a guess.

## LangGraph shared state

`scout/orchestration/state.py` defines `RetailGraphState` - the single
typed Pydantic object every future graph node (Supervisor, Step 9;
specialist agents, Step 10+) will read from and write to. No graph is
built yet - this step only defines and validates the state shape:

```bash
python -c "
from scout.orchestration.state import RetailGraphState
state = RetailGraphState(session_id='S1', customer_query='find comfortable work shoes under \$100')
print(state.workflow_status, state.retry_count, state.product_candidates)
"
```

See the module docstring for what graph state is, how nodes read and
update it, which fields use a reducer (`messages`, `completed_steps`,
`tool_results`, `evidence`, `errors`) and why, and what must never be
placed in state (chain-of-thought, secrets, full private customer
data, anything the database already owns as source of truth).

## LangGraph Supervisor

`scout/orchestration/supervisor.py` defines `supervisor_node` - still
not wired into a real graph (Step 10's job). It applies deterministic
safety rules first (max step/retry limits from `MAX_WORKFLOW_STEPS` /
`MAX_RETRIES`, idempotency once a workflow is terminal or paused), then
asks a pluggable `SupervisorPolicy` for a `SupervisorDecision` - one of
`recommendation`, `inventory`, `order`, `support`, `verification`,
`clarification`, `confirmation`, `finish`, or `safe_failure`
(`scout/orchestration/supervisor_decision.py`).

`LangChainSupervisorPolicy` (`scout/orchestration/supervisor_policy.py`)
is the real decision-maker: it binds the Supervisor's prompt
(`scout/orchestration/supervisor_prompt.py`) to any LangChain chat
model that supports `with_structured_output`. No model is wired in yet
- Ollama integration is Phase 5's job - so tests exercise it with a
fake chat model instead of a live server. `route_from_supervisor`
(`scout/orchestration/routing.py`) is the separate, dumb function that
turns `state.next_agent` into a graph destination; it holds no
planning logic of its own.

```bash
python -c "
from scout.orchestration.state import RetailGraphState
from scout.orchestration.supervisor import supervisor_node
from scout.orchestration.supervisor_decision import SupervisorDecision

class FixedPolicy:
    def decide(self, state):
        return SupervisorDecision(decision='clarification', goal='understand the request',
                                   decision_summary='request is too vague',
                                   clarification_question='Which store would you like me to check?')

state = RetailGraphState(session_id='S1', customer_query='find something nice')
print(supervisor_node(state, FixedPolicy()))
"
```

## LangGraph workflow (Step 10; Step 11 adds the correction loop)

`scout/orchestration/graph.py` wires the state (Step 8) and Supervisor
(Step 9) together with four specialist-agent node modules into Scout's
first complete, runnable LangGraph workflow - the exact pipeline
CLAUDE.md's primary example calls for:

> Find comfortable work shoes under $100 that I can pick up today near
> Maple Grove.

```
START
  |
  v
understand_request            (scout/agents/understand_request.py)
  |
  v
supervisor                    (scout/orchestration/supervisor.py)
  |
  |-- order request --> order_agent --> END              (Step 17 read-only status)
  |
  |-- route_from_supervisor --> END                      (vague request: awaiting_clarification)
  |
  v
recommendation_agent          (scout/agents/recommendation_agent.py)
  |
  v
inventory_agent               (scout/agents/inventory_agent.py)
  |
  v
availability_evaluation       (scout/agents/inventory_agent.py)
  |
  |-- route_after_availability --> reranking             (everything already fulfillable)
  |
  v
nearby_store_search            (scout/agents/inventory_agent.py)
  |
  |-- route_after_nearby --> reranking                   (nearby search resolved everything)
  |
  v
substitute_search               (scout/agents/inventory_agent.py)
  |
  v
reranking                       (scout/agents/recommendation_agent.py)
  |
  v
response_verification           (scout/agents/response_verification.py)
  |
  |-- route_after_verification --> recommendation_agent  (every candidate failed verification;
  |                                                        correction_count < max_correction_attempts)
  v
END
```

**Nodes**

- `understand_request` - deterministic, regex/keyword extraction of
  category, budget, pickup intent, and location from the raw
  `customer_query` (no LLM yet - Ollama integration is still Phase 5).
  A mentioned location is resolved to a real store via the new
  `find_store_by_location` MCP tool (`scout/mcp/store_tools.py`) -
  never a guessed `store_id`.
- `supervisor` - the same `supervisor_node` from Step 9, now driven by
  `RuleBasedSupervisorPolicy` (`scout/orchestration/rule_based_policy.py`),
  a fully deterministic policy suited to this graph's fixed shape: it
  asks for clarification if the request has no usable category,
  budget, or location at all, or if a mentioned location never
  resolved to a real store; otherwise it builds a plan and routes to
  `recommendation_agent`.
- `recommendation_agent` - calls the approved `search_products` and
  `rank_products` MCP tools to build an initial, budget-enforced,
  ranked candidate set.
- `order_agent` - for order-status requests, calls approved read-only
  MCP order tools and returns persisted order, payment, fulfillment,
  tracking, estimate, and eligibility facts. It never runs SQL or
  performs a cancellation, return, exchange, or refund.
- `inventory_agent` - checks every candidate's stock at the customer's
  selected store (`check_store_inventory`).
- `availability_evaluation` - calls no tool; it is the deterministic
  "what does this mean" step that summarizes how many candidates are
  already confirmed fulfillable, kept as its own visible node.
- `nearby_store_search` - for any candidate still unfulfilled, checks
  nearby stores (`find_nearby_inventory`) and records the nearest
  fulfillable one.
- `substitute_search` - for anything still unfulfilled after that,
  searches for a similar, in-budget substitute at the selected store
  (`find_available_substitutes`), re-enforcing the customer's original
  budget since that tool's own price band is relative to the
  out-of-stock reference product, not the customer's budget.
- `reranking` - drops any candidate with no confirmed sellable stock
  from any channel checked so far, then re-ranks whatever survives.
  This is CLAUDE.md's "remove invalid or unavailable options" and
  "rerank valid products," done together since both need the same
  computation.
- `response_verification` - the full Step 11 verifier: re-checks every
  candidate against the catalog, its own inventory evidence, and any
  promotion claim, drops anything unsupported, and builds the final,
  evidence-backed `final_response` - see "Response Verification Agent"
  below for the complete list of checks and the correction loop.

**Edges and conditional routes**

- `route_from_supervisor` (Step 9, reused unchanged) sends the graph
  to `recommendation_agent` when the Supervisor decided
  `"recommendation"`, or to `END` for every other decision - a request
  needing clarification stops here, before any specialist agent runs.
- `route_after_verification` (Step 11) sends the graph back to
  `recommendation_agent` for a fresh attempt when the verifier
  rejected every candidate and has not yet exhausted
  `max_correction_attempts`, or to `END` otherwise (completed, failed,
  or any paused status).
- `route_after_availability` and `route_after_nearby` both ask the
  same question - are there still candidates with no confirmed
  sellable stock anywhere, via `products_needing_fulfillment()`
  (`scout/agents/inventory_agent.py`) - and either continue the
  fallback chain (`nearby_store_search`, then `substitute_search`) or
  skip straight to `reranking`. Neither route decides *which* products
  need fallback; they only read the answer an agent node already
  computed and recorded in `state.inventory_results`.

**Safety**

`scout/orchestration/limits.py` gives every node in this pipeline
(beyond the Supervisor's own single check) the same step-budget guard:
if `state.step_count` has already reached `MAX_WORKFLOW_STEPS`, a node
stops immediately with `workflow_status="stopped_at_limit"` and the
fixed safe-failure message, instead of running any further tool calls.
Every MCP tool call in `scout/agents/inventory_agent.py` is wrapped so
a real database failure (`sqlite3.Error`) or a structured tool error
becomes a `WorkflowError` and the node moves on to the next candidate,
rather than crashing the whole workflow over one bad candidate.

```bash
python -c "
from scout.orchestration.graph import run_graph
result = run_graph(
    session_id='S1',
    customer_query='Find comfortable work shoes under \$100 that I can pick up today near Maple Grove.',
)
print(result.workflow_status)
print(result.final_response)
"
```

## Response Verification Agent (Step 11)

`scout/agents/response_verification.py` checks every bullet CLAUDE.md
section 4 lists before a customer ever sees `final_response`:

1. Product ID exists, 2. name matches SQLite, 3. price matches SQLite,
   4. product satisfies the budget - all four re-read the catalog
   fresh via `get_product_details`, never trusting a candidate's own
   (possibly stale) fields.
2. Inventory claim matches tool evidence, 6. store claim matches
   inventory evidence - both cross-check the claim already in
   `state.inventory_results` against a real, already-collected
   `EvidenceEntry`, catching a claim that was never actually backed by
   a tool call.
3. Promotion exists and is active - checked against a fresh
   `get_promotions` call whenever a candidate carries a promotion
   claim (no node attaches one yet, so this is real but currently
   inert - see the module docstring).
4. The composed `final_response` text itself is scanned for any
   dollar figure or product name that isn't one of the verified
   candidates' own - a safety net independent of how the text was
   built.

A candidate that fails any check is dropped and the specific issue is
recorded as a `WorkflowError` - other, still-valid candidates are
still shown. Only when *every* candidate fails (or the composed text
itself fails check 8) does this become a workflow-level decision:

```
response_verification
  |
  |-- every candidate failed, correction_count < max_correction_attempts
  |     -> workflow_status="in_progress", correction_count += 1,
  |        inventory_results cleared -> loop back to recommendation_agent
  |
  |-- every candidate failed, limit reached
  |     -> workflow_status="failed", final_response=SAFE_FAILURE_MESSAGE
  |
  |-- at least one candidate verified
        -> workflow_status="completed", final_response built from
           only the verified candidates
```

A correction pass is safe to run automatically because this pipeline
is entirely read-only until a customer confirms a protected action
(none exist yet) - a fresh pass through
`recommendation_agent -> ... -> response_verification` cannot repeat
any side effect. `correction_count` / `max_correction_attempts`
(`scout/config.py`, default 2) bound this independently of the
graph-wide `step_count` budget every node already checks, and
`run_graph()` now passes an explicit `recursion_limit` (sized off
`max_workflow_steps`) so a customer-configured step budget - not
LangGraph's own unrelated default - is always what actually stops the
workflow.

```bash
python -c "
from scout.orchestration.graph import run_graph
result = run_graph(
    session_id='S1',
    customer_query='Find comfortable work shoes under \$100 that I can pick up today near Maple Grove.',
)
print(result.workflow_status)
print(result.final_response)
print(result.correction_count)
"
```

## POST /chat (Step 12)

`scout/api/routes/chat.py` is the one HTTP entry point into the LangGraph
workflow above. It stays thin on purpose - it validates the request,
builds a trusted initial `RetailGraphState`, invokes the compiled graph
(injected via `scout/api/dependencies.py`'s `get_compiled_graph`, built
once and cached with `@lru_cache`, replaceable in tests via
`app.dependency_overrides`), and maps the verified final state into a
`ChatResponse`. No recommendation, inventory, or verification logic
lives in the route itself.

```
Client
  -> ChatRequest validation (Pydantic, extra="forbid" - the client has
     no field that could ever reach an internal graph field such as
     plan, next_agent, evidence, retry_count, step_count, or
     workflow_status)
  -> build_initial_state() - a trusted dict; only session_id, message,
     user_id, store_id, and location come from the client
  -> compiled_graph.invoke(...) under an asyncio.wait_for timeout
     (SCOUT_WORKFLOW_TIMEOUT_SECONDS, scout/config.py)
  -> RetailGraphState.model_validate(...) - the already-verified final
     state (Step 11 already ran)
  -> build_chat_response() - maps state -> ChatResponse
  -> Client
```

```bash
curl -X POST "http://127.0.0.1:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "demo-session-001",
    "message": "Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    "location": "Maple Grove, MN"
  }'
```

```json
{
  "workflow_id": "e86de15f-e14a-4c0b-9ec5-81e87418fe70",
  "session_id": "demo-session-001",
  "status": "completed",
  "answer": "ComfortPro Shift Support ($89.99) has 7 unit(s) available for pickup today at Scout Demo Store - Plymouth.",
  "products": [{"product_id": "FTW-004", "name": "ComfortPro Shift Support", "price": 89.99, "...": "..."}],
  "fulfillment_options": [{"product_id": "FTW-004", "channel": "nearby_store", "store_name": "Scout Demo Store - Plymouth", "sellable_quantity": 7, "distance_miles": 4.28}],
  "activity_events": ["Understanding your request", "Searching the product catalog", "Ranking matching products", "Checking your selected store's inventory", "Comparing fulfillment options", "Searching nearby stores", "Verifying product details"],
  "errors": []
}
```

`status` is one of `completed`, `clarification_required`, `no_results`,
`confirmation_required`, or `failed` - all five are HTTP 200, because
each is a business outcome the workflow reached on purpose (including
`failed`, which is Step 11's own correction-limit exhaustion, not a
server error). HTTP status codes:

| Code | Meaning |
| --- | --- |
| 200 | The request was handled - any of the five `status` values above |
| 422 | The request itself was malformed (Pydantic validation) |
| 503 | A workflow timeout or an unreachable required tool/database |
| 500 | A genuinely unexpected exception - no internal detail is ever returned |

Every error response has the shape `{"error": "...", "code": "...",
"message": "..."}` (e.g. `{"code": "WORKFLOW_TIMEOUT", "message":
"Scout could not complete the request in time. Please try again."}`) -
never a raw exception, stack trace, SQL, file path, or prompt.

New/changed files: `scout/api/schemas/chat.py` (`ChatRequest`,
`ChatResponse`, `FulfillmentOption`, `ChatError`),
`scout/api/dependencies.py` (`get_compiled_graph`),
`scout/api/routes/chat.py`, `scout/api/app.py` (router registered),
`scout/api/exceptions.py` (`ScoutAppError` gained a `code` field; the
validation-error handler now runs `exc.errors()` through
`jsonable_encoder` before serializing it), `scout/config.py` and
`.env.example` (`SCOUT_WORKFLOW_TIMEOUT_SECONDS`,
`MAX_CORRECTION_ATTEMPTS`), `scout/orchestration/state.py`
(`workflow_id`, `user_id`, `requested_store_id`, `location`),
`tests/test_chat_api.py`.

## POST /chat/stream (Step 13)

`scout/api/routes/chat_stream.py` streams the same workflow `/chat`
runs, as Server-Sent Events, so a client can show live activity
instead of waiting silently for one final answer. It reuses Step 12's
`build_initial_state` and `build_chat_response` directly - the initial
state and the final response are exactly what `/chat` would build and
return; only how progress reaches the client differs.

```bash
curl -N -X POST "http://127.0.0.1:8000/chat/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "session_id": "demo-session-001",
    "message": "Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
    "location": "Maple Grove, MN"
  }'
```

```text
event: workflow_started
id: 1
data: {"event_id":1,"event_type":"workflow_started","workflow_id":"...","session_id":"demo-session-001","label":"Understanding your request","data":{...},"timestamp":"..."}

event: agent_selected
id: 3
data: {...,"label":"Searching the product catalog",...}

event: tool_started
id: 8
data: {...,"label":"Checking Maple Grove inventory",...}

event: verification_completed
id: 19
data: {...,"label":"Verifying product details",...}

event: final_response
id: 20
data: {...,"data":{"status":"completed","answer":"ComfortPro Shift Support ($89.99) has 7 unit(s) available for pickup today at Scout Demo Store - Plymouth.","products":[...],"fulfillment_options":[...],"errors":[]}}

event: stream_closed
id: 21
data: {...,"data":{"status":"closed"}}
```

How events are produced: `scout/api/routes/chat_stream.py` drives the
already-compiled graph with `compiled_graph.astream(..., stream_mode="updates")`
(the supported LangGraph async streaming interface - no graph
rewrite), turning each node's partial state update into zero or more
customer-safe `StreamEvent`s via the shared label vocabulary in
`scout/orchestration/events.py` (the same vocabulary `/chat`'s
`activity_events` now uses too, via `activity_labels_for_tool_results`
- Step 13 removed the duplicate copy Step 12 had). Event IDs increase
monotonically; a `heartbeat` frame (no `id:` line) is sent instead if
`SCOUT_STREAM_HEARTBEAT_SECONDS` passes without a real event -
`scout/api/streaming.py`'s `with_heartbeat` and `render_sse`. The same
`SCOUT_WORKFLOW_TIMEOUT_SECONDS` from Step 12 bounds one stream's
total wall-clock time.

Business outcomes stream the same way `/chat` classifies them:
clarification and no-results are normal endings (a `clarification_required`
event, or just a `final_response` with `status="no_results"` - never a
failure). Anything that stops the workflow without a verified answer -
a stream-level timeout, a tool/database failure, an unexpected
exception, or the graph itself exhausting its correction/step limits -
emits `workflow_failed` with a safe `{"code", "message"}` payload
(never a raw exception, stack trace, SQL, or prompt), followed by
`stream_closed`. A client disconnect closes the underlying LangGraph
generator via `GeneratorExit` -> `.aclose()`; nothing is left running
in the background.

New/changed files: `scout/orchestration/events.py` (new; also now used
by `scout/api/routes/chat.py`), `scout/api/schemas/events.py`
(`StreamEvent`), `scout/api/streaming.py` (`render_sse`,
`with_heartbeat`), `scout/api/routes/chat_stream.py`, `scout/api/app.py`
(router registered), `scout/config.py` and `.env.example`
(`SCOUT_STREAM_HEARTBEAT_SECONDS`), `tests/test_chat_stream.py`.

## Checkout and order creation (Step 16)

Step 16 adds a deterministic checkout path on top of Step 15's session cart:

```text
Validate cart and fulfillment
→ create a server-calculated order review
→ require explicit payment confirmation
→ run the local mock payment adapter
→ atomically create the order and reserve inventory
→ convert the cart
```

The browser never supplies prices, discounts, tax, shipping, or totals. The
checkout service re-reads products, active promotions, inventory, and the cart
from SQLite. Only repositories execute SQL. Pickup reserves every item at the
selected store; delivery may allocate inventory across active stores.

This phase uses **mock payment only**. It accepts `mock_success` for a successful
test payment and `mock_decline` for a safe decline. It does not collect or store
card numbers and does not charge real money. A future production adapter can
replace this boundary without moving calculation or order rules into React or
an LLM.

### Checkout API

Create an immutable order review:

```bash
curl -X POST http://127.0.0.1:8000/checkout/sessions \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo-session-001","shipping_address":null}'
```

Confirm the reviewed checkout explicitly:

```bash
curl -X POST http://127.0.0.1:8000/checkout/sessions/CHECKOUT_ID/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "session_id":"demo-session-001",
    "idempotency_key":"demo-checkout-key-0001",
    "confirm_payment":true,
    "payment_method_token":"mock_success"
  }'
```

A repeated confirmation with the same session, checkout, and idempotency key
returns the same order and does not reserve inventory twice. Confirmation is
rejected when the cart, price, promotion, fulfillment, or available inventory
changed after review.

Configuration is centralized in `.env`:

```text
CHECKOUT_TAX_RATE=0.08
FLAT_SHIPPING_FEE=5.99
FREE_SHIPPING_THRESHOLD=50.00
CHECKOUT_CURRENCY=USD
MOCK_PAYMENT_PROVIDER=mock
```

The React cart drawer now includes delivery-address entry, order review,
explicit test-payment confirmation, safe error states, and order confirmation.

New Step 16 modules include:

- `scout/repositories/checkout_repository.py`
- `scout/services/checkout_service.py`
- `scout/services/payment_service.py`
- `scout/api/routes/checkout.py`
- `scout/mcp/checkout_tools.py`
- `web/src/components/CheckoutPanel.tsx`


## External merchant and affiliate fallback (Step 16.5)

Step 16.5 adds a bounded recovery path when Scout cannot fulfill a request
from its own catalog. It does not replace internal recommendations and does not
run while a verified internal product is still available.

```text
Selected store
→ nearby stores
→ store-network delivery
→ internal substitutes
→ external merchant fallback only when no internal candidate survives
```

The external feed is **synthetic demo data only**. Mock retailers and outbound
URLs are fictional and use `example.com`; no Amazon, Walmart, or other real
merchant integration is included. External records stay separate from Scout
products, carts, checkout, orders, payments, and inventory.

Customer-facing rules:

- External cards say **View at retailer**, never **Add to cart**.
- Similar offers are labelled **Similar external alternative**.
- **Exact external match** is allowed only inside the trusted matching service
  when authoritative UPC, GTIN, or model data matches. The current synthetic
  Scout catalog has no authoritative identifiers, so the live API/MCP/graph
  path returns similar alternatives only.
- The UI states that the item is not sold by Scout and displays an affiliate
  disclosure.
- Ranking uses request relevance, lower price, rating, and a stable ID
  tie-breaker. No commission field exists and commission is never a ranking
  signal.

The browser opens an audited Scout redirect rather than receiving a merchant
URL directly:

```text
GET /affiliate/click/{offer_id}?session_id=...&match_type=similar
→ validate current offer
→ record affiliate_clicks row
→ 307 redirect to the synthetic merchant URL
```

A click is analytics only. It does not prove a purchase and cannot create a
Scout cart item, payment, or order. `MAX_EXTERNAL_OFFERS=3` bounds the fallback
result count.

New Step 16.5 modules include:

- `scout/repositories/affiliate_repository.py`
- `scout/services/external_merchant_adapter.py`
- `scout/services/external_offer_service.py`
- `scout/mcp/affiliate_tools.py`
- `scout/agents/external_offer_agent.py`
- `scout/api/routes/affiliate.py`
- `web/src/components/ExternalOfferCard.tsx`
- `web/src/components/ExternalOfferGrid.tsx`

## Read-only Order Agent (Step 17)

Step 17 reuses the immutable orders, order items, payments, and inventory
reservations created by Step 16. It adds a separate `order_fulfillments` table
for status, pickup/delivery estimates, carrier tracking, and completion
timestamps. Existing Step 16 orders without a fulfillment row receive a safe
configured estimate instead of invented tracking data.

The Supervisor recognizes order requests and routes them through the bounded
LangGraph workflow:

```text
Customer asks about an order
→ understand_request extracts order ID/action
→ supervisor routes to order_agent
→ order_agent calls approved MCP tools
→ read-only order status is returned
```

Supported read-only capabilities:

- Lookup an explicit order ID or the latest order in the current session.
- Report order and mock-payment status.
- Report pickup store or delivery address and estimated readiness/arrival.
- Show carrier/tracking facts only when they are persisted.
- Evaluate cancellation, return, and exchange eligibility using configured,
  deterministic windows.

No protected action is executed in this phase. Eligibility output explicitly
states that no cancellation, return, exchange, or refund was performed. Orders
are session-isolated: an order ID alone is insufficient without the matching
shopping session.

### Order API

```text
GET /orders/latest?session_id=...
GET /orders/{order_id}?session_id=...
GET /orders/{order_id}/status?session_id=...
GET /orders/{order_id}/payment?session_id=...
GET /orders/{order_id}/fulfillment?session_id=...
GET /orders/{order_id}/eligibility?session_id=...
```

The same path is available through chat. After completing mock checkout in the
React app, ask **Where is my order?** in the same session to see the Step 17
order-status card.

Configuration:

```text
ORDER_PICKUP_READY_MINUTES=120
ORDER_CANCELLATION_WINDOW_MINUTES=60
ORDER_RETURN_WINDOW_DAYS=30
ORDER_EXCHANGE_WINDOW_DAYS=30
```

New Step 17 modules include:

- `scout/repositories/order_repository.py`
- `scout/services/order_service.py`
- `scout/mcp/order_tools.py`
- `scout/agents/order_agent.py`
- `scout/api/routes/orders.py`
- `web/src/components/OrderStatusCard.tsx`

## Run tests

```bash
pytest
```

Database and repository tests always run against a temporary SQLite
file (via pytest's `tmp_path`) and never touch `data/scout.db`.

## Project layout

```
Retail_AI_Agent/
├── requirements.txt      # Python dependencies
├── .env.example          # Template for local environment variables
├── .gitignore
├── data/                 # SQLite database file lives here (git-ignored)
├── scout/                # Backend application package
│   ├── config.py         # Centralized settings (env-driven)
│   ├── logging_config.py # Structured JSON logging setup
│   ├── main.py            # ASGI entrypoint (uvicorn target)
│   ├── api/
│   │   ├── app.py         # FastAPI app factory
│   │   ├── exceptions.py  # Centralized error handling
│   │   └── routes/
│   │       └── health.py  # GET /health
│   ├── database/
│   │   ├── connection.py  # SQLite connections, foreign keys enabled
│   │   ├── schema.sql     # Table definitions (products, stores, inventory, promotions)
│   │   ├── initialize.py  # Creates tables (repeatable)
│   │   └── seed.py        # Synthetic demo data (repeatable, no duplicates)
│   ├── repositories/       # The only layer that runs SQL (Step 3)
│   ├── services/           # Deterministic business rules, no SQL, no LLM (Step 4)
│   ├── mcp/
│   │   ├── product_tools.py    # search_products, get_product_details, get_promotions,
│   │   │                       # rank_products, find_similar_products
│   │   ├── inventory_tools.py  # selected, nearby, network, pickup/delivery, substitutes
│   │   ├── affiliate_tools.py  # external search, offer verification, click tracking
│   │   ├── order_tools.py      # read-only order/payment/fulfillment/eligibility tools
│   │   ├── summaries.py        # Shared Product -> ProductSummary mapping
│   │   ├── store_tools.py      # find_store_by_location - resolves free-text -> real store
│   │   ├── schemas.py          # Structured input/output models for every tool
│   │   └── errors.py           # ToolValidationError -> structured ToolError
│   ├── agents/                  # Specialist agent nodes (Step 10; verifier is Step 11)
│   │   ├── understand_request.py     # Extracts intent, resolves the pickup location
│   │   ├── recommendation_agent.py   # search/rank candidates; drop-unfulfillable + rerank
│   │   ├── inventory_agent.py        # selected / nearby / delivery / substitute fulfillment
│   │   ├── external_offer_agent.py   # bounded mock merchant fallback
│   │   ├── order_agent.py            # read-only order-status specialist
│   │   └── response_verification.py  # internal and external grounding verification
│   └── orchestration/
│       ├── state.py                 # RetailGraphState - shared LangGraph state (Step 8/11)
│       ├── supervisor_decision.py   # SupervisorDecision - structured output schema
│       ├── supervisor_prompt.py     # Supervisor system prompt + state summary rendering
│       ├── supervisor_policy.py     # Pluggable decision-maker (LangChainSupervisorPolicy)
│       ├── rule_based_policy.py     # Deterministic SupervisorPolicy used by this graph (Step 10)
│       ├── supervisor.py            # supervisor_node - deterministic limits + decision handling
│       ├── routing.py               # route_from_supervisor - decision -> graph destination
│       ├── limits.py                # check_step_budget - shared step-limit guard (Step 10)
│       └── graph.py                 # build_retail_graph / run_graph + correction loop (Step 10/11)
└── tests/                # Pytest suite
```

## Not included yet

A real payment provider, real retailer/affiliate APIs, Customer Support Agent,
protected cancellation/return/exchange/refund execution, durable memory, and
production authentication are still out of scope. Step 16 uses a local mock
payment adapter; Step 16.5 uses synthetic external offers and fictional demo
retailers; Step 17 reports order facts and eligibility only.

## Premium React UI redesign

The Step 17 frontend now uses a responsive premium three-column shopping layout inspired by the supplied Scout reference. It adds a quiet navigation sidebar, premium search and suggestion chips, a deduplicated workflow timeline, equal-height product cards, a verified fulfillment summary, real cart count/subtotal, responsive mobile navigation, and accessible loading/error states.

The redesign changes presentation only. FastAPI, LangGraph, MCP, SSE, inventory, affiliate fallback, checkout, and Order Agent business behavior remain in their existing backend layers. Saved-product persistence remains explicitly unavailable. Deals and Categories run verified Scout searches, and the filter panel now reruns the backend workflow with structured constraints.

See [`PREMIUM_UI_REDESIGN.md`](PREMIUM_UI_REDESIGN.md) for the component hierarchy, changed files, validation results, and known visual differences from the reference.

## Real map, live workflow, and backend filters

The Step 17 UI now uses stored Scout store coordinates in an interactive Leaflet map, maps real `/chat/stream` events into one deduplicated seven-stage workflow timeline, and reruns the backend graph with structured catalog filters. Recommendation filtering now enforces exact product type, supports fewer than three valid results, requires a current promotion for deal queries, and skips selected-store warnings for non-pickup searches.

See [`REAL_MAP_WORKFLOW_FILTERS.md`](REAL_MAP_WORKFLOW_FILTERS.md) for the API contracts, changed files, validation results, and local test cases.
