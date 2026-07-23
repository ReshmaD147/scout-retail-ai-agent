# Scout Step 17 Order Status UI Redesign

## What changed

The Step 17 order result was redesigned from a dense data report into a customer-facing order tracking page.

### Main order card

- Customer-friendly heading such as **Your order is confirmed**
- Short order reference with a copy-full-order-number control
- Visual pickup/delivery progress timeline
- Compact Status, Payment, Total, and Fulfillment summary row
- Product rows with image fallback, brand, quantity, unit price, and line total
- Highlighted pickup or delivery card with a minute-level estimate
- Pickup tracking note kept compact instead of using a large empty tracking panel
- Compact eligibility rows with green eligible and neutral unavailable states
- Continue shopping and order-help actions

### Right panel

When an order result is active, the product filters and product fulfillment card are replaced with:

- Pickup or delivery summary
- Order-specific location preview
- Estimated ready or arrival time
- Order help card
- Continue shopping action

The right panel uses only verified fields returned by the Step 17 order response. No store address, directions, carrier guarantee, or protected order action was invented.

## Preserved behavior

- FastAPI, LangGraph, MCP, SQLite, checkout, affiliate fallback, cart, and Order Agent behavior are unchanged.
- The Order Agent remains read-only.
- Cancellation, return, exchange, and refund actions are not executed.
- Product images use the existing product-ID path and existing placeholder fallback.
- Mobile users retain order-help and continue-shopping controls inside the main order card because the desktop right panel is hidden on mobile.

## Modified files

- `web/src/App.tsx`
- `web/src/App.test.tsx`
- `web/src/styles.css`
- `web/src/components/Icons.tsx`
- `web/src/components/OrderStatusCard.tsx`
- `web/src/components/OrderStatusCard.test.tsx`
- `web/src/components/FulfillmentSummary.test.tsx`

## New files

- `web/src/components/OrderSupportPanel.tsx`
- `web/src/components/OrderSupportPanel.test.tsx`

## Validation completed in the artifact environment

- All 39 non-test TypeScript/TSX source files passed a strict compatibility type check with local React declarations.
- The modified component test files passed a TypeScript compatibility check with local test declarations.
- All 53 TypeScript/TSX files parsed without syntax diagnostics.
- CSS parsed with 376 rules and 0 syntax errors.

The full Vitest and Vite commands could not be run in the artifact environment because the npm package gateway did not complete dependency installation. Run locally:

```bash
cd web
npm install
npm test
npm run build
npm run dev
```
