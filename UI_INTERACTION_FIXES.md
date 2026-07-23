# Scout Step 17 UI Interaction Fixes

This patch addresses the interaction problems reported in the premium UI.

## Fixed

- Pickup store selector is shown only after **Pickup** is selected.
- Delivery no longer displays an unrelated pickup-store dropdown.
- Store-list failures are visible instead of silently leaving an empty selector.
- Added **Retry pickup locations**.
- Deals now runs a verified Scout deal search.
- Categories opens a picker using the real catalog categories: Footwear, Bags, Electronics, and Home & Kitchen.
- Saved is clickable and opens an honest notice because saved-product persistence is not in the backend yet.
- Order pages show one visible **Continue shopping** and one visible **Get order help** action per viewport.
- Order help now moves to the search bar and prefills `I need help with my order`.
- Removed repeated help entry points from the order page: top help, sidebar help card, floating assistant, and fulfillment-card help.
- Help and navigation dialogs use a higher stacking level so they remain clickable.

## Backend behavior

No ranking, inventory, fulfillment, checkout, payment, order, MCP, or LangGraph business logic was moved into React or changed.

## Local verification

```bash
cd web
npm test
npm run build
npm run dev
```

Open the React app at `http://localhost:5173`, not the FastAPI address.

If pickup locations still do not load, verify the backend running in the other terminal belongs to this same project folder and open `http://127.0.0.1:8000/stores`.
