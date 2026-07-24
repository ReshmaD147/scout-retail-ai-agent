import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
    expect(screen.queryByText("Verified promotion")).not.toBeInTheDocument();
  });

  it("renders verified promotions with accessible original and promotional prices", () => {
    render(
      <ProductCard
        product={{
          ...product,
          verified_promotion: {
            promotion_id: "PRM-002",
            label: "Workwear Comfort Event",
            discount_type: "percent",
            discount_value: 10,
            original_price: 89.99,
            promotional_price: 80.99,
            savings: 9,
            valid_until: "2026-07-31",
            terms_summary: null,
            verified: true,
          },
        }}
        fulfillmentOptions={fulfillmentOptions}
      />
    );

    expect(screen.getByText("Verified promotion")).toBeInTheDocument();
    expect(screen.getByText("Workwear Comfort Event")).toBeInTheDocument();
    expect(screen.getByText("10% off · Save $9.00")).toBeInTheDocument();
    expect(screen.getByText("$80.99")).toBeInTheDocument();
    expect(screen.getByText("$89.99")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Current price $80.99, original price $89.99")
    ).toBeInTheDocument();
    expect(screen.getByText(/valid through/i)).toHaveTextContent("Valid through Jul 31, 2026");
    expect(screen.queryByText(/while the verified promotion is active/i)).not.toBeInTheDocument();
  });

  it("renders the grounded explanation for the correct product", () => {
    render(
      <ProductCard
        product={{
          ...product,
          explanation: "ComfortPro Shift Support matches your request with high cushioning and a verified active promotion.",
          explanation_source: "deterministic_fallback",
        }}
        fulfillmentOptions={fulfillmentOptions}
      />
    );

    expect(screen.getByLabelText("Why Scout selected ComfortPro Shift Support")).toHaveTextContent(
      "ComfortPro Shift Support matches your request"
    );
  });

  it("shows memory influence only when the backend says memory affected ranking", () => {
    const { rerender } = render(<ProductCard product={product} fulfillmentOptions={fulfillmentOptions} />);
    expect(screen.queryByText(/matches a saved preference/i)).not.toBeInTheDocument();

    rerender(
      <ProductCard
        product={{ ...product, memory_influence: "Ranked slightly higher because it matches your saved wide-fit preference." }}
        fulfillmentOptions={fulfillmentOptions}
      />
    );

    expect(screen.getByText("Ranked slightly higher because it matches your saved wide-fit preference.")).toBeInTheDocument();
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

  it("toggles saved state with accessible pressed labels", () => {
    const onToggleSaved = vi.fn();
    render(<ProductCard product={product} fulfillmentOptions={[]} isSaved onToggleSaved={onToggleSaved} />);
    const button = screen.getByRole("button", { name: "Remove ComfortPro Shift Support from saved" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(button);
    expect(onToggleSaved).toHaveBeenCalledWith("FTW-004");
  });
});
