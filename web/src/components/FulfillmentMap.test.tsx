import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StoreSummary } from "../types/cart";
import type { FulfillmentOption, RequestedLocation } from "../types/chat";
import { FulfillmentMap } from "./FulfillmentMap";

const fitBounds = vi.fn();

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="map-container">{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  CircleMarker: ({ children, center }: { children: React.ReactNode; center: [number, number] }) => (
    <div data-testid="circle-marker" data-center={center.join(",")}>{children}</div>
  ),
  Popup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Polyline: ({ children }: { children: React.ReactNode }) => <div data-testid="visual-connection">{children}</div>,
  useMap: () => ({ fitBounds }),
}));

const stores: StoreSummary[] = [
  { store_id: "STR-001", store_name: "Maple Grove", city: "Maple Grove", state: "MN", postal_code: "55369", latitude: 45.0725, longitude: -93.4557, pickup_enabled: true, active: true },
  { store_id: "STR-002", store_name: "Plymouth", city: "Plymouth", state: "MN", postal_code: "55447", latitude: 45.0105, longitude: -93.4555, pickup_enabled: true, active: true },
];

const options: FulfillmentOption[] = [
  { product_id: "FTW-004", channel: "selected_store", store_id: "STR-001", store_name: "Maple Grove", sellable_quantity: 0, distance_miles: 1.2, substitute_for: null, delivery_min_days: null, delivery_max_days: null },
  { product_id: "FTW-004", channel: "nearby_store", store_id: "STR-002", store_name: "Plymouth", sellable_quantity: 7, distance_miles: 4.28, substitute_for: null, delivery_min_days: null, delivery_max_days: null },
];

const requestedLocation: RequestedLocation = {
  label: "Maple Grove requested area",
  latitude: 45.0725,
  longitude: -93.4557,
};

describe("FulfillmentMap", () => {
  it("renders actual stored coordinates, availability details, fit bounds, and a non-routing connection", () => {
    render(<FulfillmentMap options={options} stores={stores} requestedLocation={requestedLocation} />);

    expect(screen.getByTestId("tile-layer")).toBeInTheDocument();
    expect(screen.getAllByTestId("circle-marker")).toHaveLength(3);
    expect(screen.getByText("Maple Grove requested area")).toBeInTheDocument();
    const mapleGroveMarker = screen
     .getByText("Maple Grove", { selector: "strong" })
     .closest('[data-testid="circle-marker"]');

    const plymouthMarker = screen
     .getByText("Plymouth", { selector: "strong" })
     .closest('[data-testid="circle-marker"]');

    expect(mapleGroveMarker).toHaveTextContent("Out of stock");
    expect(plymouthMarker).toHaveTextContent("7 in stock");
    expect(screen.getByTestId("visual-connection")).toBeInTheDocument();
    expect(screen.getAllByText(/not a driving route/i).length).toBeGreaterThan(0);
    expect(fitBounds).toHaveBeenCalled();
  });
});
