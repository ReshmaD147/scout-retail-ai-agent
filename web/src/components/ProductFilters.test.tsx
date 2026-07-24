import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProductFilters } from "./ProductFilters";

vi.mock("../hooks/useCatalogFilters", () => ({
  useCatalogFilters: () => ({
    options: {
      max_price: 220,
      categories: ["Electronics", "Footwear"],
      product_types: { Electronics: ["Earbuds", "Speakers"], Footwear: ["Work"] },
      attributes: [
        { token: "connectivity:Bluetooth 5.3", label: "Bluetooth 5.3 connectivity", key: "connectivity", value: "Bluetooth 5.3", categories: ["Electronics"], product_types: ["Earbuds"] },
      ],
    },
    isLoading: false,
    errorMessage: null,
    retry: vi.fn(),
  }),
}));

describe("ProductFilters", () => {
  it("submits structured catalog-backed filters to re-run the backend search", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<ProductFilters value={{ in_stock_only: true }} onApply={onApply} />);

    await user.selectOptions(screen.getByLabelText("Category"), "Electronics");
    await user.selectOptions(screen.getByLabelText("Product type"), "Earbuds");
    await user.click(screen.getByLabelText("Bluetooth 5.3 connectivity"));
    await user.selectOptions(screen.getByLabelText("Fulfillment"), "delivery");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({
      category: "Electronics",
      product_type: "Earbuds",
      attributes: ["connectivity:Bluetooth 5.3"],
      fulfillment: "delivery",
      in_stock_only: true,
    }));
  });

  it("clear all restores the only always-on verified-stock constraint", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<ProductFilters value={{ category: "Electronics", in_stock_only: true }} onApply={onApply} />);
    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onApply).toHaveBeenCalledWith({ in_stock_only: true });
  });

  it("allows local clearing before a query but blocks applying filters", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<ProductFilters value={{ category: "Electronics", in_stock_only: true }} canApply={false} onApply={onApply} />);

    expect(screen.getByRole("button", { name: "Search first to apply filters" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Category")).toHaveValue("");
  });
});
