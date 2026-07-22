import type { FulfillmentOption, ProductSummary } from "../types/chat";
import { ProductCard } from "./ProductCard";

export interface ProductGridProps {
  products: ProductSummary[];
  fulfillmentOptions: FulfillmentOption[];
  /** Step 15's "Add to cart" action, threaded through to every card. */
  onAddToCart?: (productId: string) => void;
}

/**
 * A responsive grid of verified product results. Groups the flat
 * `fulfillmentOptions` list (ChatResponse.fulfillment_options) by
 * `product_id` so each `ProductCard` only ever sees the options that
 * actually belong to it - no card ever displays another product's
 * availability.
 */
export function ProductGrid({ products, fulfillmentOptions, onAddToCart }: ProductGridProps): JSX.Element {
  return (
    <div className="product-grid" role="list" aria-label="Product results">
      {products.map((product) => (
        <div role="listitem" key={product.product_id}>
          <ProductCard
            product={product}
            fulfillmentOptions={fulfillmentOptions.filter(
              (option) => option.product_id === product.product_id
            )}
            onAddToCart={onAddToCart}
          />
        </div>
      ))}
    </div>
  );
}
