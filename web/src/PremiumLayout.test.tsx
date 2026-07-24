import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";


vi.mock("./hooks/useCatalogFilters", () => ({
  useCatalogFilters: () => ({
    options: {
      max_price: 250,
      categories: ["Footwear", "Electronics", "Home and Kitchen"],
      product_types: { Footwear: ["Work"], Electronics: ["Earbuds"], "Home and Kitchen": ["Coffee Makers"] },
      attributes: [],
    },
    isLoading: false,
    errorMessage: null,
  }),
}));

vi.mock("./hooks/useScoutChat", () => ({
  useScoutChat: () => ({
    query: "",
    setQuery: vi.fn(),
    phase: "idle",
    isLoading: false,
    activities: [],
    response: null,
    errorMessage: null,
    usedFallback: false,
    sessionId: "layout-session",
    submit: vi.fn(),
    cancel: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("./hooks/useCart", () => ({
  useCart: () => ({
    cart: {
      cart_id: "CART-1",
      session_id: "layout-session",
      items: [],
      subtotal: 239.97,
      fulfillment_type: null,
      store_id: null,
      store_name: null,
      status: "active",
      validation_status: "valid",
      warnings: [],
      updated_at: null,
    },
    itemCount: 3,
    isLoading: false,
    errorMessage: null,
    stores: [],
    addItem: vi.fn(),
    updateQuantity: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
    choosePickup: vi.fn(),
    chooseDelivery: vi.fn(),
    dismissError: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.mock("./hooks/useSavedProducts", () => ({
  useSavedProducts: () => ({
    saved: { session_id: "layout-session", customer_id: null, saved_product_ids: [], products: [], count: 0 },
    savedIds: new Set<string>(),
    count: 0,
    isLoading: false,
    errorMessage: null,
    refresh: vi.fn(),
    toggle: vi.fn(),
    dismissError: vi.fn(),
  }),
}));

describe("Premium Scout layout", () => {
  it("renders the three-column shell content and sidebar navigation", () => {
    const { container } = render(<App />);
    expect(container.querySelector(".app-shell")).toBeInTheDocument();
    expect(screen.getByLabelText("Primary navigation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New search" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fulfillment summary" })).toBeInTheDocument();
  });

  it("shows the backend cart subtotal in the top action area", () => {
    render(<App />);
    expect(screen.getByText("$239.97")).toBeInTheDocument();
    expect(screen.getByLabelText("3 items in cart")).toBeInTheDocument();
  });

  it("makes sidebar destinations interactive without inventing unsupported backend behavior", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByRole("button", { name: "Deals" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Categories" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Saved/ })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Categories" }));
    expect(screen.getByRole("dialog", { name: "Browse categories" })).toBeInTheDocument();
    await user.click(screen.getByLabelText("Close categories"));

    await user.click(screen.getByRole("button", { name: /Saved/ }));
    expect(screen.getByRole("heading", { name: "Saved products" })).toBeInTheDocument();
    expect(screen.getByText("You have not saved any products yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear all" })).toBeDisabled();
  });
});
