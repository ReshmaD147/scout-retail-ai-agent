import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { OrderStatusView } from "../types/chat";
import { OrderStatusCard } from "./OrderStatusCard";

const order: OrderStatusView = {
  order_id: "123e4567-e89b-42d3-a456-426614174000",
  session_id: "session-1",
  order_status: "confirmed",
  created_at: "2026-07-22T12:00:00Z",
  items: [
    {
      order_item_id: "item-1",
      product_id: "FTW-004",
      product_name: "ComfortPro Shift Support",
      brand: "ComfortPro",
      quantity: 1,
      charged_unit_price: 89.99,
      line_total: 89.99,
    },
  ],
  subtotal: 89.99,
  discount_total: 0,
  tax_total: 7.2,
  shipping_total: 0,
  total: 97.19,
  currency: "USD",
  payment: {
    status: "succeeded",
    provider: "mock",
    provider_reference: "mock-ref",
    amount: 97.19,
    currency: "USD",
    paid_at: "2026-07-22T12:00:00Z",
  },
  fulfillment: {
    fulfillment_type: "pickup",
    status: "processing",
    store_id: "STR-002",
    store_name: "Scout Demo Store - Plymouth",
    shipping_address: null,
    estimated_ready_at: "2026-07-22T14:00:00Z",
    estimated_delivery_at: null,
    estimate_source: "configured_policy",
    tracking: {
      available: false,
      carrier_name: null,
      tracking_number: null,
      tracking_url: null,
      message: "Tracking is not used for pickup orders.",
    },
  },
  eligibility: {
    cancellation: { eligible: true, reason: "Within the cancellation window.", deadline: null },
    return_eligibility: { eligible: false, reason: "Not completed yet.", deadline: null },
    exchange: { eligible: false, reason: "Not completed yet.", deadline: null },
  },
};

describe("OrderStatusCard", () => {
  it("renders a customer-friendly order page with progress, item, pickup, and eligibility facts", () => {
    render(<OrderStatusCard order={order} onNeedHelp={vi.fn()} onContinueShopping={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Your order is confirmed" })).toBeInTheDocument();
    expect(screen.getByText("Order #14174000")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Copy full order number ${order.order_id}` })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Order progress" })).toBeInTheDocument();
    expect(screen.getByText("Ready for pickup")).toBeInTheDocument();
    expect(screen.getByText("ComfortPro Shift Support")).toBeInTheDocument();
    expect(screen.getByAltText("ComfortPro Shift Support product photo")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pickup at Scout Demo Store - Plymouth" })).toBeInTheDocument();
    expect(screen.getByText("Tracking is not used for pickup orders.")).toBeInTheDocument();
    expect(screen.getByText("Cancellation eligible")).toBeInTheDocument();
    expect(screen.getByText("Return not available yet")).toBeInTheDocument();
    expect(screen.getByText("Exchange not available yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue shopping" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get order help" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(cancel|return|exchange)$/i })).not.toBeInTheDocument();
  });
});
