import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CartDrawer } from "./CartDrawer";
import type { CartView, StoreSummary } from "../types/cart";

/**
 * Unit tests for the cart drawer (Step 15). Every callback prop is a
 * `vi.fn()` stand-in for the real `useCart` action - this file only
 * asserts that the right callback fires with the right arguments, not
 * how the cart is actually updated (that is `cart_service.py`'s job,
 * covered by the backend test suite).
 */

const item = {
  cart_item_id: "CTI-1",
  product_id: "FTW-004",
  product_name: "ComfortPro Shift Support",
  brand: "ComfortPro",
  quantity: 2,
  unit_price: 89.99,
  unit_price_snapshot: 89.99,
  line_total: 179.98,
  promotion_id: null,
  promotion_label: null,
  active: true,
  warnings: [],
};

const cart: CartView = {
  cart_id: "CART-1",
  session_id: "s-1",
  items: [item],
  subtotal: 179.98,
  fulfillment_type: null,
  store_id: null,
  store_name: null,
  status: "active",
  validation_status: "valid",
  warnings: [],
  updated_at: "2026-01-01T00:00:00Z",
};

const stores: StoreSummary[] = [
  { store_id: "STR-001", store_name: "Scout Demo Store - Maple Grove", city: "Maple Grove", pickup_enabled: true, active: true },
  { store_id: "STR-003", store_name: "Scout Demo Store - No Pickup", city: "Elsewhere", pickup_enabled: false, active: true },
];

function baseProps() {
  return {
    isOpen: true,
    onClose: vi.fn(),
    cart,
    isLoading: false,
    errorMessage: null,
    stores,
    onUpdateQuantity: vi.fn(),
    onRemoveItem: vi.fn(),
    onClear: vi.fn(),
    onChoosePickup: vi.fn(),
    onChooseDelivery: vi.fn(),
    onDismissError: vi.fn(),
  };
}

describe("CartDrawer", () => {
  it("renders nothing when closed", () => {
    const props = baseProps();
    const { container } = render(<CartDrawer {...props} isOpen={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the empty-cart state when there are no items", () => {
    const props = baseProps();
    render(<CartDrawer {...props} cart={{ ...cart, items: [], subtotal: 0 }} />);
    expect(screen.getByText(/your cart is empty/i)).toBeInTheDocument();
  });

  it("shows the empty-cart state when no cart has loaded yet", () => {
    const props = baseProps();
    render(<CartDrawer {...props} cart={null} />);
    expect(screen.getByText(/your cart is empty/i)).toBeInTheDocument();
  });

  it("displays item name, unit price, quantity, and line total", () => {
    render(<CartDrawer {...baseProps()} />);
    expect(screen.getByText("ComfortPro Shift Support")).toBeInTheDocument();
    expect(screen.getByText("$89.99 each")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    const lineItem = screen.getByRole("listitem");
    expect(within(lineItem).getByText("$179.98")).toBeInTheDocument();
  });

  it("displays the subtotal from the backend, without recomputing it", () => {
    render(<CartDrawer {...baseProps()} />);
    expect(within(screen.getByLabelText("Cart subtotal")).getByText("$179.98")).toBeInTheDocument();
  });

  it("increments quantity via the + control (scenario 22)", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<CartDrawer {...props} />);
    await user.click(screen.getByLabelText(/increase quantity of comfortpro/i));
    expect(props.onUpdateQuantity).toHaveBeenCalledWith("CTI-1", 3);
  });

  it("decrements quantity via the − control (scenario 22)", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<CartDrawer {...props} />);
    await user.click(screen.getByLabelText(/decrease quantity of comfortpro/i));
    expect(props.onUpdateQuantity).toHaveBeenCalledWith("CTI-1", 1);
  });

  it("disables the decrement control at quantity 1, instead of allowing zero", () => {
    const props = baseProps();
    render(
      <CartDrawer
        {...props}
        cart={{ ...cart, items: [{ ...item, quantity: 1 }] }}
      />
    );
    expect(screen.getByLabelText(/decrease quantity of comfortpro/i)).toBeDisabled();
  });

  it("calls onRemoveItem when the remove button is clicked", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<CartDrawer {...props} />);
    await user.click(screen.getByLabelText(/remove comfortpro shift support from cart/i));
    expect(props.onRemoveItem).toHaveBeenCalledWith("CTI-1");
  });

  it("calls onClear when clear cart is clicked", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<CartDrawer {...props} />);
    await user.click(screen.getByRole("button", { name: "Clear cart" }));
    expect(props.onClear).toHaveBeenCalledTimes(1);
  });

  it("calls onChooseDelivery when delivery is selected", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<CartDrawer {...props} />);
    await user.click(screen.getByRole("radio", { name: "Delivery" }));
    expect(props.onChooseDelivery).toHaveBeenCalledTimes(1);
  });

  it("shows the store selector after pickup is selected and calls onChoosePickup", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<CartDrawer {...props} />);
    expect(screen.queryByLabelText("Pickup store")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Pickup" }));
    await user.selectOptions(screen.getByLabelText("Pickup store"), "STR-001");
    expect(props.onChoosePickup).toHaveBeenCalledWith("STR-001");
  });

  it("disables pickup-unavailable stores in the store dropdown", async () => {
    const user = userEvent.setup();
    render(<CartDrawer {...baseProps()} />);
    await user.click(screen.getByRole("radio", { name: "Pickup" }));
    const option = screen.getByRole("option", { name: /no pickup/i }) as HTMLOptionElement;
    expect(option.disabled).toBe(true);
  });

  it("hides the pickup-store selector while delivery is selected", () => {
    render(<CartDrawer {...baseProps()} cart={{ ...cart, fulfillment_type: "delivery" }} />);
    expect(screen.queryByLabelText("Pickup store")).not.toBeInTheDocument();
  });

  it("explains when pickup stores are unavailable and supports retry", async () => {
    const user = userEvent.setup();
    const onRefreshStores = vi.fn();
    render(
      <CartDrawer
        {...baseProps()}
        stores={[]}
        storesErrorMessage="Scout could not load pickup locations."
        onRefreshStores={onRefreshStores}
      />
    );
    await user.click(screen.getByRole("radio", { name: "Pickup" }));
    expect(screen.getByText(/could not load pickup locations/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Pickup store")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry pickup locations" }));
    expect(onRefreshStores).toHaveBeenCalledTimes(1);
  });

  it("collects a shipping address when delivery is selected", () => {
    render(<CartDrawer {...baseProps()} cart={{ ...cart, fulfillment_type: "delivery" }} />);
    expect(screen.getByText(/enter the shipping address in checkout below/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
    expect(screen.getByLabelText("Address line 1")).toBeInTheDocument();
  });

  it("displays validation warnings from the backend", () => {
    render(
      <CartDrawer
        {...baseProps()}
        cart={{ ...cart, warnings: ["The price of ComfortPro Shift Support has changed."] }}
      />
    );
    expect(screen.getByText("The price of ComfortPro Shift Support has changed.")).toBeInTheDocument();
  });

  it("displays a safe error message and lets the user dismiss it", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<CartDrawer {...props} errorMessage="Scout could not update your cart. Please try again." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Scout could not update your cart. Please try again.");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(props.onDismissError).toHaveBeenCalledTimes(1);
  });

  it("shows a loading indicator while a mutation is in flight", () => {
    render(<CartDrawer {...baseProps()} isLoading />);
    expect(screen.getByRole("status")).toHaveTextContent(/updating your cart/i);
  });

  it("calls onClose when the close button is clicked", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<CartDrawer {...props} />);
    await user.click(screen.getByLabelText("Close cart"));
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });
});
