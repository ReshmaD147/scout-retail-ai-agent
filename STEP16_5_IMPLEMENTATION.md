# Scout Step 16.5 — External Merchant/Affiliate Fallback

## What was implemented

Step 16.5 adds a mock external-retailer recovery path after all internal
fulfillment paths fail. The active LangGraph order is:

```text
selected store → nearby stores → store-network delivery
→ internal substitutes → reranking
→ external fallback only if no internal candidate survives
→ response verification
```

## Safety boundaries

- External offers are stored separately in `external_offers`.
- External clicks are audit/analytics rows in `affiliate_clicks`.
- External items never enter Scout carts, checkout, payments, orders, or
  inventory reservations.
- React renders `View at retailer`, not `Add to cart`.
- Direct merchant URLs are not returned in chat or search responses. The
  browser uses `/affiliate/click/{offer_id}` so the backend validates the offer,
  records the click, and then redirects.
- Redirect destinations must use HTTPS.
- Fictional Scout products are labelled as similar alternatives. The trusted
  service has an exact-identifier guard for a future authoritative catalog, but
  the current API/MCP path cannot accept client- or model-supplied identifiers.
- Ranking does not use commission.
- All merchants and offers are synthetic; URLs use `example.com`.

## Main files

### Database and repositories
- `scout/database/schema.sql`
- `scout/database/seed.py`
- `scout/repositories/models.py`
- `scout/repositories/affiliate_repository.py`

### Services, MCP, graph, and verification
- `scout/services/external_merchant_adapter.py`
- `scout/services/external_offer_service.py`
- `scout/mcp/affiliate_tools.py`
- `scout/agents/external_offer_agent.py`
- `scout/agents/inventory_agent.py`
- `scout/agents/response_verification.py`
- `scout/orchestration/graph.py`
- `scout/orchestration/state.py`

### API and React
- `scout/api/routes/affiliate.py`
- `scout/api/schemas/affiliate.py`
- `scout/api/schemas/chat.py`
- `web/src/api/affiliateClient.ts`
- `web/src/components/ExternalOfferCard.tsx`
- `web/src/components/ExternalOfferGrid.tsx`

## Local verification commands

From the project root, using the same Python environment that passed Step 16:

```bash
python -m pytest -q
```

Then verify React:

```bash
cd web
npm install
npm test
npm run build
```

Expected test totals in this package are **460 backend tests** and **49 frontend
tests**. Exact totals should be confirmed locally with the real packages listed
in `requirements.txt` and `web/package.json`.

## Manual browser test for the fallback

The normal seed data usually finds an internal option, so external fallback
should not appear. To test it safely, use a temporary development database or
set internal inventory to zero, then run the same work-shoe query. Scout should
return external cards labelled `Similar external alternative`; each card must
show `View at retailer` and no Scout cart button. Restore/reseed the database
afterward.

## Not included

No real retailer API, real affiliate network, external checkout, purchase
attribution, Order Agent, Support Agent, refunds, or Step 17 behavior was added.
