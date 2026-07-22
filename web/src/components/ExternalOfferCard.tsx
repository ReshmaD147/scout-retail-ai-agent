import { buildAffiliateClickUrl } from "../api/affiliateClient";
import type { ExternalOfferSummary } from "../types/chat";
import { PRODUCT_IMAGE_PLACEHOLDER } from "./ProductCard";

export interface ExternalOfferCardProps {
  offer: ExternalOfferSummary;
  sessionId: string;
  workflowId: string;
}

/** One mock merchant alternative. It deliberately has no Add to cart
 * action: external checkout belongs to the retailer, not Scout. */
export function ExternalOfferCard({ offer, sessionId, workflowId }: ExternalOfferCardProps): JSX.Element {
  const clickUrl = buildAffiliateClickUrl(offer, sessionId, workflowId);
  const imageSource = offer.image_url ?? PRODUCT_IMAGE_PLACEHOLDER;

  return (
    <article className="external-offer-card">
      <img
        className="external-offer-card__image"
        src={imageSource}
        alt={`${offer.product_name} external product photo`}
        loading="lazy"
        width={180}
        height={180}
      />
      <div className="external-offer-card__body">
        <div className={`external-offer-card__match external-offer-card__match--${offer.match_type}`}>
          {offer.match_label}
        </div>
        <h3>{offer.product_name}</h3>
        <p className="external-offer-card__merchant">Sold by {offer.merchant_name}</p>
        <p className="external-offer-card__brand">{offer.brand}</p>
        <p className="external-offer-card__price">
          {offer.currency === "USD" ? "$" : `${offer.currency} `}
          {offer.price.toFixed(2)}
        </p>
        {offer.rating !== null && (
          <p className="external-offer-card__rating">
            <span aria-hidden="true">★</span> {offer.rating.toFixed(1)} ({offer.review_count} reviews)
          </p>
        )}
        <p className="external-offer-card__reason">{offer.match_reason}</p>
        <a
          className="external-offer-card__link"
          href={clickUrl}
          target="_blank"
          rel="noopener noreferrer sponsored"
        >
          View at retailer
        </a>
        <span className="external-offer-card__affiliate-label">Affiliate link</span>
      </div>
    </article>
  );
}
