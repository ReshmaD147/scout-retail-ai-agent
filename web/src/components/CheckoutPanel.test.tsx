import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CheckoutPanel } from "./CheckoutPanel";
import type { UseCheckoutResult } from "../hooks/useCheckout";
import type { CartView } from "../types/cart";
import type { CheckoutReview, OrderConfirmation } from "../types/checkout";

const cart: CartView = {
  cart_id: "CART-1",
  session_id: "s-1",
  items: [
    {
      cart_item_id: "ITEM-1",
      product_id: "FTW-004",
      product_name: "ComfortPro Shift Support",
      brand: "ComfortPro",
      quantity: 1,
      unit_price: 80.99,
      unit_price_snapshot: 80.99,
      line_total: 80.99,
      promotion_id: "PRM-1",
      promotion_label: "10% off",
      active: true,
      warnings: [],
    },
  ],
  subtotal: 80.99,
  fulfillment_type: "delivery",
  store_id: null,
  store_name: null,
  status: "active",
  validation_status: "valid",
  warnings: [],
  updated_at: "2026-01-01T00:00:00Z",
};

const review: CheckoutReview = {
  checkout_id: "CHK-1",
  session_id: "s-1",
  cart_id: "CART-1",
  cart_updated_at: "2026-01-01T00:00:00Z",
  status: "review",
  fulfillment_type: "delivery",
  store_id: null,
  store_name: null,
  shipping_address: {
    full_name: "Scout Customer",
    line1: "123 Main Street",
    line2: null,
    city: "Maple Grove",
    state: "MN",
    postal_code: "55369",
    country: "US",
  },
  items: [
    {
      product_id: "FTW-004",
      product_name: "ComfortPro Shift Support",
      brand: "ComfortPro",
      quantity: 1,
      catalog_unit_price: 89.99,
      charged_unit_price: 80.99,
      line_subtotal: 89.99,
      discount_total: 9,
      line_total: 80.99,
      promotion_id: "PRM-1",
      promotion_label: "10% off",
    },
  ],
  subtotal: 89.99,
  discount_total: 9,
  merchandise_total: 80.99,
  tax_rate: 0.08,
  tax_total: 6.48,
  shipping_total: 0,
  total: 87.47,
  currency: "USD",
  warnings: [],
};

function checkoutState(overrides: Partial<UseCheckoutResult> = {}): UseCheckoutResult {
  return {
    review: null,
    confirmation: null,
    isLoading: false,
    errorMessage: null,
    createReview: vi.fn().mockResolvedValue(undefined),
    confirm: vi.fn().mockResolvedValue(undefined),
    reset: vi.fn(),
    dismissError: vi.fn(),
    ...overrides,
  };
}

describe("CheckoutPanel", () => {
  it("collects delivery address and requests a server review", async () => {
    const user = userEvent.setup();
    const checkout = checkoutState();
    render(<CheckoutPanel cart={cart} checkout={checkout} />);

    await user.type(screen.getByLabelText("Full name"), "Scout Customer");
    await user.type(screen.getByLabelText("Address line 1"), "123 Main Street");
    await user.type(screen.getByLabelText("City"), "Maple Grove");
    await user.type(screen.getByLabelText("State"), "MN");
    await user.type(screen.getByLabelText("ZIP code"), "55369");
    await user.click(screen.getByRole("button", { name: "Review checkout" }));

    expect(checkout.createReview).toHaveBeenCalledWith(
      expect.objectContaining({ city: "Maple Grove", state: "MN", country: "US" })
    );
  });

  it("requires explicit confirmation before placing the order", async () => {
    const user = userEvent.setup();
    const checkout = checkoutState({ review });
    render(<CheckoutPanel cart={cart} checkout={checkout} />);

    const placeOrder = screen.getByRole("button", { name: /place test order/i });
    expect(placeOrder).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    expect(placeOrder).toBeEnabled();
    await user.click(placeOrder);
    expect(checkout.confirm).toHaveBeenCalledWith(true);
  });

  it("shows the confirmed order result from the backend", () => {
    const confirmation: OrderConfirmation = {
      order_id: "ORD-1",
      checkout_id: "CHK-1",
      session_id: "s-1",
      status: "confirmed",
      fulfillment_type: "pickup",
      store_id: "STR-002",
      store_name: "Scout Demo Store - Plymouth",
      shipping_address: null,
      items: [],
      subtotal: 89.99,
      discount_total: 9,
      merchandise_total: 80.99,
      tax_total: 6.48,
      shipping_total: 0,
      total: 87.47,
      currency: "USD",
      payment: {
        provider: "mock",
        provider_reference: "mock-ref",
        status: "succeeded",
        amount: 87.47,
        currency: "USD",
      },
      created_at: "2026-01-01T00:00:00Z",
    };
    render(<CheckoutPanel cart={cart} checkout={checkoutState({ confirmation })} />);
    expect(screen.getByRole("heading", { name: "Order confirmed" })).toBeInTheDocument();
    expect(screen.getByText("ORD-1")).toBeInTheDocument();
    expect(screen.getByText(/no real card was charged/i)).toBeInTheDocument();
  });
});
