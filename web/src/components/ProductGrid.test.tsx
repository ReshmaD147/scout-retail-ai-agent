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
    render(<ProductGrid products={[products[0]]} fulfillmentOptions={[]} />);
    expect(screen.getByText("Footwear")).toBeInTheDocument();
    expect(screen.getByText("Work")).toBeInTheDocument();
    expect(screen.queryByText("Memory Foam")).not.toBeInTheDocument();
  });
});
