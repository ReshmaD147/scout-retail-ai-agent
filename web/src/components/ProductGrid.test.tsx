import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ProductSummary } from "../types/chat";
import { ProductGrid } from "./ProductGrid";

const products: ProductSummary[] = Array.from({ length: 4 }, (_, index) => ({
  product_id: `P-${index + 1}`,
  name: `Verified Product ${index + 1}`,
  brand: "Scout Demo",
  category: "Footwear",
  subcategory: "Work",
  price: 50 + index,
  rating: 4.2,
  review_count: 10,
  active: true,
}));

describe("ProductGrid", () => {
  it("renders no more than three backend-ranked products", () => {
    render(<ProductGrid products={products} fulfillmentOptions={[]} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText("Verified Product 4")).not.toBeInTheDocument();
  });

  it("uses only backend product fields for visible category tags", () => {
    const { container } = render(<ProductGrid products={[products[0]]} fulfillmentOptions={[]} />);
    expect(container.querySelector(".product-grid--single")).toBeInTheDocument();
    expect(screen.getByText("Footwear")).toBeInTheDocument();
    expect(screen.getByText("Work")).toBeInTheDocument();
    expect(screen.queryByText("Memory Foam")).not.toBeInTheDocument();
  });

  it("keeps multi-result responses in the standard grid layout", () => {
    const { container } = render(<ProductGrid products={products.slice(0, 2)} fulfillmentOptions={[]} />);
    expect(container.querySelector(".product-grid--single")).not.toBeInTheDocument();
  });
});
