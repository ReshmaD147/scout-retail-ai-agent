import type { FulfillmentOption, ProductSummary } from "../types/chat";
import { ProductCard } from "./ProductCard";

export interface ProductGridProps {
  products: ProductSummary[];
  fulfillmentOptions: FulfillmentOption[];
  onAddToCart?: (productId: string) => void;
  savedProductIds?: Set<string>;
  onToggleSaved?: (productId: string) => void;
}

export function ProductGrid({ products, fulfillmentOptions, onAddToCart, savedProductIds = new Set(), onToggleSaved }: ProductGridProps): JSX.Element {
  const visibleProducts = products.slice(0, 3);
  const layoutClass = visibleProducts.length === 1 ? " product-grid--single" : "";
  return (
    <div className={`product-grid${layoutClass}`} role="list" aria-label="Product results">
      {visibleProducts.map((product, index) => (
        <div role="listitem" key={product.product_id}>
          <ProductCard
            product={product}
            fulfillmentOptions={fulfillmentOptions.filter((option) => option.product_id === product.product_id)}
            resultPosition={index + 1}
            onAddToCart={onAddToCart}
            isSaved={savedProductIds.has(product.product_id)}
            onToggleSaved={onToggleSaved}
          />
        </div>
      ))}
    </div>
  );
}
