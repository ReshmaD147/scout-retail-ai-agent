import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PRODUCT_IMAGE_PLACEHOLDER, ProductCard } from "./ProductCard";
import type { FulfillmentOption, ProductSummary } from "../types/chat";

const product: ProductSummary = {
  product_id: "FTW-004",
  name: "ComfortPro Shift Support",
  brand: "ComfortPro",
  category: "Footwear",
  subcategory: "Work",
  price: 89.99,
  rating: 4.7,
  review_count: 401,
  active: true,
};

const fulfillmentOptions: FulfillmentOption[] = [
  {
    product_id: "FTW-004",
    channel: "nearby_store",
    store_id: "STR-002",
    store_name: "Scout Demo Store - Plymouth",
    sellable_quantity: 7,
    distance_miles: 4.28,
    substitute_for: null,
    delivery_min_days: null,
    delivery_max_days: null,
  },
];

describe("ProductCard", () => {
  it("displays verified product data (scenario 7)", () => {
    render(<ProductCard product={product} fulfillmentOptions={fulfillmentOptions} />);
    expect(screen.getByText("ComfortPro Shift Support")).toBeInTheDocument();
    expect(screen.getByText("ComfortPro")).toBeInTheDocument();
  });

  it("formats the price correctly (scenario 8)", () => {
    render(<ProductCard product={product} fulfillmentOptions={fulfillmentOptions} />);
    expect(screen.getByText("$89.99")).toBeInTheDocument();
  });

  it("omits rating when the backend did not provide one, instead of guessing", () => {
    render(<ProductCard product={{ ...product, rating: null }} fulfillmentOptions={fulfillmentOptions} />);
    expect(screen.queryByText(/reviews\)/)).not.toBeInTheDocument();
  });

  it("tries webp, then png, then jpg before falling back to the placeholder (scenario 9)", () => {
    render(<ProductCard product={product} fulfillmentOptions={fulfillmentOptions} />);
    const image = screen.getByAltText("ComfortPro Shift Support product photo") as HTMLImageElement;

    expect(image.src).toContain(`/images/products/${product.product_id}.webp`);
    fireEvent.error(image);
    expect(image.src).toContain(`/images/products/${product.product_id}.png`);
    fireEvent.error(image);
    expect(image.src).toContain(`/images/products/${product.product_id}.jpg`);
    fireEvent.error(image);
    expect(image.src).toContain(PRODUCT_IMAGE_PLACEHOLDER);

    // A further error (e.g. the placeholder itself failing) must not loop.
    fireEvent.error(image);
    expect(image.src).toContain(PRODUCT_IMAGE_PLACEHOLDER);
  });

  it("clearly distinguishes fulfillment channels (scenario 10)", () => {
    render(
      <ProductCard
        product={product}
        fulfillmentOptions={[
          {
            product_id: "FTW-004",
            channel: "selected_store",
            store_id: "STR-001",
            store_name: "Scout Demo Store - Maple Grove",
            sellable_quantity: 0,
            distance_miles: null,
            substitute_for: null,
            delivery_min_days: null,
            delivery_max_days: null,
          },
          {
            product_id: "FTW-004",
            channel: "nearby_store",
            store_id: "STR-002",
            store_name: "Scout Demo Store - Plymouth",
            sellable_quantity: 7,
            distance_miles: 4.28,
            substitute_for: null,
            delivery_min_days: null,
            delivery_max_days: null,
          },
        ]}
      />
    );

    expect(screen.getByText(/not currently available for pickup at Scout Demo Store - Maple Grove/i)).toBeInTheDocument();
    expect(
      screen.getByText(/available at a nearby store, Scout Demo Store - Plymouth, 4.28 miles away/i)
    ).toBeInTheDocument();
  });

  it("shows an honest message when no fulfillment data exists, instead of guessing", () => {
    render(<ProductCard product={product} fulfillmentOptions={[]} />);
    expect(screen.getByText("Pickup time unavailable")).toBeInTheDocument();
  });
});
