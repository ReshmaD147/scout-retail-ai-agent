---
policy_id: POL-REFUNDS
title: Refunds
version: 1.0.0
effective_date: 2026-07-01
review_date: 2026-10-01
status: active
category: refunds
categories: [refunds, payments, orders]
owner: Scout Retail Policy
related_policies: [returns, order_cancellation, damaged_items, missing_packages, gift_cards]
---

# Refunds Policy

## Standard Policy
Approved refunds are issued to the original payment method when available. Refund calculation must use the backend order record, verified promotions, taxes, shipping charges, and any returned quantities.

## Timing
- Card refunds are normally submitted within 3 business days after approval.
- Bank or card issuer posting times may add additional days.
- Store credit may be issued immediately only when the customer chooses it or the original payment method is unavailable.

## Exceptions
- Shipping charges are refundable only when Scout caused the issue, the order was canceled before shipment, or applicable law requires it.
- Gift card purchases are refunded back to gift card balance when possible.
- Price adjustments use `promotions_price_matching.md`, not the returns workflow.

## Cross-Policy Notes
Return approval is governed by `returns.md`. Cancellation refunds are governed by `order_cancellation.md`. Damaged or missing item evidence is governed by `damaged_items.md` and `missing_packages.md`.

Related policy files: `returns.md`, `order_cancellation.md`, `damaged_items.md`, `missing_packages.md`, `gift_cards.md`.
