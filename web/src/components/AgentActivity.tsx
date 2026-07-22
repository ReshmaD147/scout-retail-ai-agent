import type { ActivityEvent } from "../types/chat";

export interface AgentActivityProps {
  activities: ActivityEvent[];
}

/**
 * A live log of customer-safe workflow activity, in the order it
 * arrived from POST /chat/stream. Only ever renders `label` strings
 * Scout's backend already vetted as safe (scout/orchestration/events.py)
 * - never a tool name, an argument, or any other internal detail.
 *
 * `aria-live="polite"` announces each new line to screen readers as
 * it arrives, without interrupting whatever the user is doing.
 */
export function AgentActivity({ activities }: AgentActivityProps): JSX.Element | null {
  if (activities.length === 0) {
    return null;
  }

  return (
    <section className="agent-activity" aria-label="Scout's activity">
      <h2 className="agent-activity__title">What Scout is doing</h2>
      <ul className="agent-activity__list" aria-live="polite">
        {activities.map((activity) => (
          <li key={activity.id} className="agent-activity__item">
            {activity.label}
          </li>
        ))}
      </ul>
    </section>
  );
}
