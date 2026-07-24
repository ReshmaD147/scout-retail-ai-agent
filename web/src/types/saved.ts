import type { ProductSummary } from "./chat";

export interface SavedProductView {
  saved_id: string;
  product: ProductSummary;
  created_at: string;
  availability_label: string;
  can_add_to_cart: boolean;
}

export interface SavedProductsView {
  session_id: string | null;
  customer_id: string | null;
  saved_product_ids: string[];
  products: SavedProductView[];
  count: number;
}
