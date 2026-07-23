import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { OrderStatusView } from "../types/chat";
import { OrderSupportPanel } from "./OrderSupportPanel";

const order = {
  order_id: "order-1",
  session_id: "session-1",
  order_status: "confirmed",
  created_at: "2026-07-22T12:00:00Z",
  items: [],
  subtotal: 80,
  discount_total: 0,
  tax_total: 7.47,
  shipping_total: 0,
  total: 87.47,
  currency: "USD",
  payment: { status: "succeeded", provider: "mock", provider_reference: "ref", amount: 87.47, currency: "USD", paid_at: "2026-07-22T12:00:00Z" },
  fulfillment: {
    fulfillment_type: "pickup",
    status: "processing",
    store_id: "STR-1",
    store_name: "Scout Demo Store - Brooklyn Park",
    shipping_address: null,
    estimated_ready_at: "2026-07-22T22:30:00Z",
    estimated_delivery_at: null,
    estimate_source: "configured_policy",
    tracking: { available: false, carrier_name: null, tracking_number: null, tracking_url: null, message: "Tracking is not used for pickup orders." },
  },
  eligibility: {
    cancellation: { eligible: true, reason: "Eligible", deadline: null },
    return_eligibility: { eligible: false, reason: "Not yet", deadline: null },
    exchange: { eligible: false, reason: "Not yet", deadline: null },
  },
} satisfies OrderStatusView;

describe("OrderSupportPanel", () => {
  it("replaces shopping filters with grounded order help and fulfillment details", () => {
    render(<OrderSupportPanel order={order} onNeedHelp={vi.fn()} onContinueShopping={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Pickup summary" })).toBeInTheDocument();
    expect(screen.getByText("Scout Demo Store - Brooklyn Park")).toBeInTheDocument();
    expect(screen.getByText("Estimated ready")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Need help with this order?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get order help" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue shopping" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Filters" })).not.toBeInTheDocument();
  });
});
