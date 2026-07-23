import type { FulfillmentOption, ProductSummary } from "../types/chat";
import { ProductCard } from "./ProductCard";

export interface ProductGridProps {
  products: ProductSummary[];
  fulfillmentOptions: FulfillmentOption[];
  onAddToCart?: (productId: string) => void;
}

export function ProductGrid({ products, fulfillmentOptions, onAddToCart }: ProductGridProps): JSX.Element {
  return (
    <div className="product-grid" role="list" aria-label="Product results">
      {products.slice(0, 3).map((product, index) => (
        <div role="listitem" key={product.product_id}>
          <ProductCard
            product={product}
            fulfillmentOptions={fulfillmentOptions.filter((option) => option.product_id === product.product_id)}
            resultPosition={index + 1}
            onAddToCart={onAddToCart}
          />
        </div>
      ))}
    </div>
  );
}
