import { useState } from "react";
import { decideProtectedAction } from "../api/protectedActionsClient";
import type { ProtectedActionConfirmationCard, ProtectedActionResult } from "../types/chat";

interface ProtectedActionCardProps {
  action: ProtectedActionConfirmationCard;
  sessionId: string;
}

function actionLabel(actionType: string): string {
  return actionType.replace(/_/g, " ");
}

export function ProtectedActionCard({ action, sessionId }: ProtectedActionCardProps): JSX.Element {
  const [status, setStatus] = useState<"awaiting" | "processing" | "completed" | "rejected" | "failed">("awaiting");
  const [result, setResult] = useState<ProtectedActionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (decision: "approve" | "reject"): Promise<void> => {
    if (status === "processing") return;
    setStatus("processing");
    setError(null);
    try {
      const next = await decideProtectedAction(action.confirmation_id, sessionId, decision);
      setResult(next);
      setStatus(next.execution_status === "rejected" ? "rejected" : next.execution_status === "verified" ? "completed" : "failed");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Scout could not complete this protected action safely.");
      setStatus("failed");
    }
  };

  return (
    <section className="protected-action-card" aria-label="Protected action confirmation">
      <p className="protected-action-card__eyebrow">Confirmation required</p>
      <h3>{action.proposal_summary}</h3>
      <dl>
        <div>
          <dt>Action</dt>
          <dd>{actionLabel(action.action_type)}</dd>
        </div>
        <div>
          <dt>Affected {action.resource_type}</dt>
          <dd>{action.resource_id}</dd>
        </div>
        <div>
          <dt>Eligibility</dt>
          <dd>{action.eligibility_status} · {action.eligibility_reason_code}</dd>
        </div>
      </dl>
      {action.customer_effects.length > 0 && (
        <ul>
          {action.customer_effects.map((effect) => <li key={effect}>{effect}</li>)}
        </ul>
      )}
      {action.financial_effects.length > 0 && (
        <ul>
          {action.financial_effects.map((effect) => <li key={effect}>{effect}</li>)}
        </ul>
      )}
      <p className="protected-action-card__expires">Expires {new Date(action.expires_at).toLocaleString()}</p>
      {result && <p className="protected-action-card__result">{result.message}</p>}
      {error && <p className="protected-action-card__error">{error}</p>}
      {status === "awaiting" || status === "processing" ? (
        <div className="protected-action-card__actions">
          <button type="button" onClick={() => void decide("approve")} disabled={status === "processing"}>
            {status === "processing" ? "Processing…" : `Confirm ${actionLabel(action.action_type)}`}
          </button>
          <button type="button" onClick={() => void decide("reject")} disabled={status === "processing"}>
            Reject
          </button>
        </div>
      ) : null}
    </section>
  );
}
