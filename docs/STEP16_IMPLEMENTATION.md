# Scout Step 16 — Checkout and Order Creation

## Added

- Server-calculated checkout review
- Pickup and delivery validation
- Delivery-address validation
- Current product, promotion, price, and inventory revalidation
- Deterministic discount, tax, shipping, and total calculations
- Explicit payment confirmation
- Local mock payment adapter (`mock_success` / `mock_decline`)
- Idempotent order confirmation
- Atomic SQLite persistence for payment result, order, order items, inventory reservations, cart conversion, and checkout completion
- Pickup-store and multi-store delivery inventory reservation
- REST checkout routes
- MCP checkout tools
- React address, review, confirmation, error, and success UI
- Backend and frontend tests

## API flow

```text
POST /checkout/sessions
→ GET /checkout/sessions/{checkout_id}?session_id=...
→ POST /checkout/sessions/{checkout_id}/confirm
```

The client never submits prices, discounts, tax, shipping, currency, or totals.

## Safety boundaries

- SQLite remains the source of truth.
- Only repositories execute SQL.
- Checkout and totals are deterministic service logic.
- No LLM calculates money, charges payment, creates orders, or edits inventory.
- A changed cart, price, promotion, fulfillment choice, or inventory state requires a new review.
- Reusing the same idempotency key returns the same order without a second reservation.
- No card data is accepted or stored.
- The payment adapter is mock/test mode only and charges no real money.

## Validation performed in the build environment

- Python compilation: passed
- Step 16 schema/service/config smoke scenarios: passed
- Checkout API smoke scenario including duplicate idempotent confirmation: passed
- New backend checkout tests in an isolated compatible test harness: **15 passed**
- Updated configuration/database tests in the isolated harness: **20 passed**
- TypeScript/TSX syntax transpilation: passed

The complete original Python suite was not rerun in the build environment because the exact `mcp`, `langgraph`, and `langchain-core` packages from the uploaded project were unavailable there. The uploaded project had **420 passed** before these Step 16 changes. Run the complete commands below in the project's own `.venv` and `web/node_modules` environment.

```bash
python -m pytest -q
cd web
npm install
npm test
npm run build
```

## Main new files

```text
scout/repositories/checkout_repository.py
scout/services/checkout_service.py
scout/services/payment_service.py
scout/api/schemas/checkout.py
scout/api/routes/checkout.py
scout/mcp/checkout_tools.py
web/src/types/checkout.ts
web/src/api/checkoutClient.ts
web/src/hooks/useCheckout.ts
web/src/components/CheckoutPanel.tsx
tests/test_checkout_service.py
tests/test_checkout_api.py
tests/test_checkout_tools.py
web/src/components/CheckoutPanel.test.tsx
```
