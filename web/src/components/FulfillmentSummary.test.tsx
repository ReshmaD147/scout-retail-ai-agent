import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StoreSummary } from "../types/cart";
import type { FulfillmentOption, RequestedLocation } from "../types/chat";
import { FulfillmentSummary } from "./FulfillmentSummary";

vi.mock("./FulfillmentMap", () => ({
  FulfillmentMap: () => <div aria-label="Verified store location map">Real map</div>,
}));

const stores: StoreSummary[] = [
  { store_id: "STR-001", store_name: "Scout Demo Store - Maple Grove", city: "Maple Grove", state: "MN", postal_code: "55369", latitude: 45.0725, longitude: -93.4557, pickup_enabled: true, active: true },
  { store_id: "STR-002", store_name: "Scout Demo Store - Plymouth", city: "Plymouth", state: "MN", postal_code: "55447", latitude: 45.0105, longitude: -93.4555, pickup_enabled: true, active: true },
];

const requestedLocation: RequestedLocation = { label: "Maple Grove", latitude: 45.0725, longitude: -93.4557 };

const options: FulfillmentOption[] = [
  { product_id: "FTW-004", channel: "selected_store", store_id: "STR-001", store_name: "Scout Demo Store - Maple Grove", sellable_quantity: 0, distance_miles: 1.2, substitute_for: null, delivery_min_days: null, delivery_max_days: null },
  { product_id: "FTW-004", channel: "nearby_store", store_id: "STR-002", store_name: "Scout Demo Store - Plymouth", sellable_quantity: 7, distance_miles: 4.28, substitute_for: null, delivery_min_days: null, delivery_max_days: null },
];

describe("FulfillmentSummary", () => {
  it("renders verified selected-store and nearby-store fulfillment without inventing warehouse data", () => {
    render(<FulfillmentSummary options={options} stores={stores} requestedLocation={requestedLocation} />);
    expect(screen.getByRole("heading", { name: "Fulfillment summary" })).toBeInTheDocument();
    expect(screen.getByLabelText("Verified store location map")).toBeInTheDocument();
    expect(screen.getAllByText("Scout Demo Store - Plymouth")).toHaveLength(2);
    expect(screen.getByText("7 in stock")).toBeInTheDocument();
    expect(screen.getByText("Out of stock")).toBeInTheDocument();
    expect(screen.queryByText(/warehouse/i)).not.toBeInTheDocument();
  });

  it("shows a grounded empty state before a search", () => {
    render(<FulfillmentSummary options={[]} stores={stores} requestedLocation={null} />);
    expect(screen.getByText(/search for a product to view verified pickup and delivery options/i)).toBeInTheDocument();
  });

  it("hides the empty fulfillment placeholder when delivery evidence exists", () => {
    render(
      <FulfillmentSummary
        options={[
          { product_id: "FTW-004", channel: "delivery", store_id: null, store_name: null, sellable_quantity: 7, distance_miles: null, substitute_for: null, delivery_min_days: 3, delivery_max_days: 5 },
        ]}
        stores={stores}
        requestedLocation={null}
      />
    );
    expect(screen.queryByText(/search for a product to view verified pickup and delivery options/i)).not.toBeInTheDocument();
    expect(screen.getByText(/7 available across the Scout store network/i)).toBeInTheDocument();
  });
});
