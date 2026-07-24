import { useState } from "react";
import type { ActivityEvent } from "../types/chat";
import { CheckIcon, CloseIcon } from "./Icons";

export interface AgentActivityProps {
  activities: ActivityEvent[];
  isComplete?: boolean;
  showWhenEmpty?: boolean;
}

const DISPLAY_ORDER = new Map<string, number>([
  ["Understanding request", 0],
  ["Creating a shopping plan", 1],
  ["Recommendation Agent searching products", 2],
  ["Inventory Agent checking selected store", 3],
  ["Inventory Agent checking nearby stores", 4],
  ["Finding available substitutes", 5],
  ["External Offer Agent searching alternatives", 6],
  ["Order Agent retrieving order evidence", 7],
  ["Verifying claims", 8],
  ["Preparing response", 9],
  ["Completed", 10],
  ["Stopped safely", 10],
]);

function sortActivitiesForDisplay(activities: ActivityEvent[]): ActivityEvent[] {
  return [...activities].sort((left, right) => {
    const leftOrder = DISPLAY_ORDER.get(left.label) ?? 99;
    const rightOrder = DISPLAY_ORDER.get(right.label) ?? 99;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    return left.id - right.id;
  });
}

export function AgentActivity({ activities, isComplete = false, showWhenEmpty = false }: AgentActivityProps): JSX.Element | null {
  const [collapsed, setCollapsed] = useState(isComplete);
  if (activities.length === 0 && !showWhenEmpty) return null;
  const visibleActivities: ActivityEvent[] = activities.length > 0 ? sortActivitiesForDisplay(activities) : [{
    id: 0,
    type: "workflow_started",
    label: "Understanding request",
    status: "active",
  }];

  return (
    <section className={`workflow-progress${collapsed ? " workflow-progress--collapsed" : ""}`} aria-label="Scout's workflow">
      <div className="workflow-progress__header">
        <h2>{isComplete ? "Scout’s workflow" : "Scout is working on it…"}</h2>
        {isComplete && (
          <button type="button" onClick={() => setCollapsed((value) => !value)} aria-expanded={!collapsed}>
            {collapsed ? "Show progress" : "Hide progress"}
          </button>
        )}
      </div>

      {!collapsed && (
        <ol className="workflow-progress__steps" aria-live="polite" aria-label="Live Scout workflow events">
          {visibleActivities.map((activity, index) => {
            const status = activity.status;
            return (
              <li key={activity.id} className={`workflow-progress__step workflow-progress__step--${status}`}>
                <span className="workflow-progress__marker" aria-hidden="true">
                  {status === "completed" ? <CheckIcon /> : status === "failed" ? <CloseIcon /> : index + 1}
                </span>
                <span className="workflow-progress__label">{activity.label}</span>
                <span className="workflow-progress__status">{status === "active" ? "In progress" : status === "failed" ? "Failed" : "Done"}</span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
