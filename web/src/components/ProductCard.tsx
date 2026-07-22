import { useState } from "react";
import type { FulfillmentOption, ProductSummary } from "../types/chat";
import { FulfillmentInfo } from "./FulfillmentInfo";

/** One consistent placeholder for a missing or failed product image
 * (Step 14). Scout's synthetic demo catalog has no real per-product
 * photos, so every product image request is expected to fail and
 * fall back to this - by design, not as an edge case. */
export const PRODUCT_IMAGE_PLACEHOLDER = "/images/products/placeholder.svg";

export interface ProductCardProps {
  product: ProductSummary;
  fulfillmentOptions: FulfillmentOption[];
  /** Step 15's "Add to cart" action. Optional so ProductCard keeps
   * working anywhere a cart is not wired up (e.g. future contexts). */
  onAddToCart?: (productId: string) => void;
}

/**
 * One verified product result. Every field shown here comes directly
 * from `ProductSummary`/`FulfillmentOption` (scout/mcp/schemas.py,
 * scout/api/schemas/chat.py) - nothing is computed, ranked, or
 * guessed in this component. Fields the backend does not currently
 * return for this product (rating, a promotion, a "why this matched"
 * explanation - none of which exist on `ProductSummary` today) are
 * simply omitted rather than shown as a fabricated placeholder value.
 */
export function ProductCard({ product, fulfillmentOptions, onAddToCart }: ProductCardProps): JSX.Element {
  const [imageSrc, setImageSrc] = useState(`/images/products/${product.product_id}.webp`);

  const handleImageError = (): void => {
    if (imageSrc !== PRODUCT_IMAGE_PLACEHOLDER) {
      setImageSrc(PRODUCT_IMAGE_PLACEHOLDER);
    }
  };

  return (
    <article className="product-card">
      <img
        className="product-card__image"
        src={imageSrc}
        onError={handleImageError}
        alt={`${product.name} product photo`}
        loading="lazy"
        width={200}
        height={200}
      />
      <div className="product-card__body">
        <h3 className="product-card__name">{product.name}</h3>
        <p className="product-card__brand">{product.brand}</p>
        <p className="product-card__price">${product.price.toFixed(2)}</p>

        {product.rating !== null && (
          <p className="product-card__rating">
            <span aria-hidden="true">★</span> {product.rating.toFixed(1)} ({product.review_count} reviews)
          </p>
        )}

        <div className="product-card__fulfillment">
          <h4 className="product-card__fulfillment-title">Availability</h4>
          <FulfillmentInfo options={fulfillmentOptions} />
        </div>

        {onAddToCart && (
          <button
            type="button"
            className="product-card__add-to-cart"
            onClick={() => onAddToCart(product.product_id)}
          >
            Add to cart
          </button>
        )}
      </div>
    </article>
  );
}
