import { useState } from "react";
import type { FulfillmentOption, ProductSummary } from "../types/chat";
import { CartIcon, HeartIcon } from "./Icons";
import { FulfillmentInfo } from "./FulfillmentInfo";

export const PRODUCT_IMAGE_PLACEHOLDER = "/images/products/placeholder.svg";
const PRODUCT_IMAGE_EXTENSIONS = ["webp", "png", "jpg"] as const;

/** Tries each supported extension in order before falling back to the
 * shared placeholder - lets product images be dropped in as .webp,
 * .png, or .jpg without any filename lookup or manifest. */
export function getProductImageSrc(productId: string, attemptIndex: number): string {
  if (attemptIndex >= PRODUCT_IMAGE_EXTENSIONS.length) return PRODUCT_IMAGE_PLACEHOLDER;
  return `/images/products/${productId}.${PRODUCT_IMAGE_EXTENSIONS[attemptIndex]}`;
}

export interface ProductCardProps {
  product: ProductSummary;
  fulfillmentOptions: FulfillmentOption[];
  /** One-based position from the backend-ranked products array. */
  resultPosition?: number;
  onAddToCart?: (productId: string) => void;
  isSaved?: boolean;
  onToggleSaved?: (productId: string) => void;
}

export function ProductCard({ product, fulfillmentOptions, resultPosition, onAddToCart, isSaved = false, onToggleSaved }: ProductCardProps): JSX.Element {
  const [imageAttempt, setImageAttempt] = useState(0);
  const imageSrc = getProductImageSrc(product.product_id, imageAttempt);
  const rankLabel = resultPosition === 1 ? "Best match" : resultPosition ? "Strong option" : null;
  const promotion = product.verified_promotion?.verified ? product.verified_promotion : null;

  const handleImageError = (): void => {
    setImageAttempt((current) => current + 1);
  };

  return (
    <article className="product-card">
      <div className="product-card__top-row">
        {rankLabel ? <span className={`product-card__match product-card__match--${resultPosition === 1 ? "best" : "strong"}`}>{rankLabel}</span> : <span />}
        <button
          type="button"
          className={`product-card__favorite${isSaved ? " product-card__favorite--saved" : ""}`}
          aria-label={isSaved ? `Remove ${product.name} from saved` : `Save ${product.name}`}
          aria-pressed={isSaved}
          onClick={() => onToggleSaved?.(product.product_id)}
          disabled={!onToggleSaved}
        >
          <HeartIcon />
        </button>
      </div>

      <div className="product-card__image-wrap">
        <img
          className="product-card__image"
          src={imageSrc}
          onError={handleImageError}
          alt={`${product.name} product photo`}
          loading="lazy"
          width={320}
          height={240}
        />
      </div>

      <div className="product-card__body">
        <h3 className="product-card__name">{product.name}</h3>
        <p className="product-card__brand">{product.brand}</p>

        <div className="product-card__rating-price">
          {product.rating !== null ? (
            <p className="product-card__rating"><span aria-hidden="true">★</span> {product.rating.toFixed(1)} ({product.review_count})</p>
          ) : <span />}
          {promotion ? (
            <div className="product-card__price-block" aria-label={`Current price ${formatCurrency(promotion.promotional_price)}, original price ${formatCurrency(promotion.original_price)}`}>
              <p className="product-card__price" aria-label={`Current price ${formatCurrency(promotion.promotional_price)}`}>{formatCurrency(promotion.promotional_price)}</p>
              <p className="product-card__original-price">Original price <s>{formatCurrency(promotion.original_price)}</s></p>
            </div>
          ) : (
            <p className="product-card__price" aria-label={`Current price ${formatCurrency(product.price)}`}>{formatCurrency(product.price)}</p>
          )}
        </div>

        {promotion && (
          <div className="product-card__promotion" aria-label={`Verified promotion: ${promotion.label}`}>
            <span className="product-card__promotion-badge">Verified promotion</span>
            <strong>{promotion.label}</strong>
            <p>{promotionText(promotion)} · Save {formatCurrency(promotion.savings)}</p>
            <small>Valid through {formatDate(promotion.valid_until)}</small>
            {promotion.terms_summary && <small>{promotion.terms_summary}</small>}
          </div>
        )}

        {product.explanation && (
          <section className="product-card__explanation" aria-label={`Why Scout selected ${product.name}`}>
            <h4>Why Scout selected this</h4>
            <p>{product.explanation}</p>
          </section>
        )}

        {product.memory_influence && (
          <p className="product-card__memory-note">{product.memory_influence}</p>
        )}

        <div className="product-card__tags" aria-label="Verified product features">
          {verifiedFeatureLabels(product).map((tag) => <span key={tag}>{tag}</span>)}
        </div>

        <div className="product-card__fulfillment">
          <FulfillmentInfo options={fulfillmentOptions} />
        </div>

        {onAddToCart && product.active && (
          <button type="button" className="product-card__add-to-cart" title={`Add ${product.name} to cart`} onClick={() => onAddToCart(product.product_id)}>
            <CartIcon /> Add to cart
          </button>
        )}
      </div>
    </article>
  );
}

function formatCurrency(value: number): string {
  return `$${value.toFixed(2)}`;
}

function promotionText(promotion: NonNullable<ProductSummary["verified_promotion"]>): string {
  return promotion.discount_type === "percent"
    ? `${Number.isInteger(promotion.discount_value) ? promotion.discount_value.toFixed(0) : promotion.discount_value.toFixed(1)}% off`
    : `${formatCurrency(promotion.discount_value)} off`;
}

function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function verifiedFeatureLabels(product: ProductSummary): string[] {
  const preferredKeys = ["cushioning", "slip_resistance", "width", "water_resistance", "material", "connectivity"];
  const labels: string[] = [];
  const attributes = product.attributes ?? {};
  for (const key of preferredKeys) {
    const value = attributes[key];
    if (typeof value !== "string" && typeof value !== "number") continue;
    const cleanValue = String(value).replace(/-/g, " ").trim();
    if (!cleanValue || cleanValue.toLowerCase() === "n/a") continue;
    const cleanKey = key.replace(/_/g, " ");
    const label = ["cushioning", "slip_resistance", "width"].includes(key)
      ? `${titleCase(cleanValue)} ${cleanKey}`
      : key === "water_resistance"
        ? titleCase(cleanValue)
        : `${cleanValue} ${cleanKey}`;
    if (!labels.includes(label)) labels.push(label);
    if (labels.length === 3) break;
  }
  return labels.length > 0 ? labels : [product.category, product.subcategory].filter(Boolean);
}

function titleCase(value: string): string {
  return value.replace(/\b\w/g, (character) => character.toUpperCase());
}
