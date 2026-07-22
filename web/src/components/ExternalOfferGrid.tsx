import type { ExternalOfferSummary } from "../types/chat";
import { ExternalOfferCard } from "./ExternalOfferCard";

export interface ExternalOfferGridProps {
  offers: ExternalOfferSummary[];
  sessionId: string;
  workflowId: string;
}

export function ExternalOfferGrid({ offers, sessionId, workflowId }: ExternalOfferGridProps): JSX.Element | null {
  if (offers.length === 0) {
    return null;
  }

  return (
    <section className="external-offers" aria-labelledby="external-offers-title">
      <div className="external-offers__heading">
        <div>
          <p className="external-offers__eyebrow">External merchant fallback</p>
          <h2 id="external-offers-title">Similar options from demo retailers</h2>
        </div>
        <span className="external-offers__badge">Not sold by Scout</span>
      </div>
      <p className="external-offers__disclosure">{offers[0].disclosure}</p>
      <div className="external-offers__grid" role="list" aria-label="External retailer alternatives">
        {offers.map((offer) => (
          <div role="listitem" key={offer.offer_id}>
            <ExternalOfferCard offer={offer} sessionId={sessionId} workflowId={workflowId} />
          </div>
        ))}
      </div>
    </section>
  );
}
