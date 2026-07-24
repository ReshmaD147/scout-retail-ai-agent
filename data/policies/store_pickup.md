---
policy_id: POL-PICKUP
title: Store Pickup
version: 1.0.0
effective_date: 2026-07-01
review_date: 2026-10-01
status: active
category: store_pickup
categories: [store_pickup, pickup, stores, fulfillment]
owner: Scout Retail Policy
related_policies: [order_cancellation, returns, exchanges]
---

# Store Pickup Policy

## Standard Policy
Pickup availability may be promised only after Scout verifies sellable inventory at the selected store. Nearby-store suggestions require a customer location, selected store, or resolved store area.

## Pickup Requirements
- Customer must select a store or provide a resolvable area.
- The selected store must be active and pickup-enabled.
- Pickup stock must be verified before showing a pickup-ready estimate.

## Exceptions
- Inventory can change before checkout unless inventory is reserved by the deterministic checkout flow.
- Store hours, holidays, and operational disruptions may affect pickup timing.

## Cross-Policy Notes
Checkout and inventory reservation are governed by the deterministic checkout workflow, not autonomous agents. Pickup cancellations follow `order_cancellation.md`.

Related policy files: `order_cancellation.md`, `returns.md`, `exchanges.md`.
