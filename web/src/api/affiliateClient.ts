import type { ExternalOfferSummary } from "../types/chat";
import { API_BASE_URL } from "./config";

/** Build the audited outbound URL. Opening it records one click on the
 * backend and then redirects to the synthetic merchant URL. */
export function buildAffiliateClickUrl(
  offer: ExternalOfferSummary,
  sessionId: string,
  workflowId: string
): string {
  const params = new URLSearchParams({
    session_id: sessionId,
    workflow_id: workflowId,
    match_type: offer.match_type,
  });
  if (offer.source_product_id) {
    params.set("source_product_id", offer.source_product_id);
  }
  return `${API_BASE_URL}/affiliate/click/${encodeURIComponent(offer.offer_id)}?${params.toString()}`;
}
