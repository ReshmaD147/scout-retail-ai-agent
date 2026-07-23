import { useState } from "react";
import type { ActivityEvent, WorkflowStageId } from "../types/chat";
import { CheckIcon, CloseIcon } from "./Icons";

export interface AgentActivityProps {
  activities: ActivityEvent[];
  isComplete?: boolean;
  showWhenEmpty?: boolean;
}

interface WorkflowStep {
  id: WorkflowStageId;
  label: string;
}

const STEPS: WorkflowStep[] = [
  { id: "understand", label: "Understanding request" },
  { id: "plan", label: "Creating shopping plan" },
  { id: "catalog", label: "Searching catalog" },
  { id: "selected-store", label: "Checking selected store" },
  { id: "nearby", label: "Checking nearby stores" },
  { id: "compare", label: "Comparing options" },
  { id: "prepare", label: "Preparing response" },
];

export function AgentActivity({ activities, isComplete = false, showWhenEmpty = false }: AgentActivityProps): JSX.Element | null {
  // Completed workflows start compact. The customer can expand them to
  // review the real stages that were emitted by /chat/stream.
  const [collapsed, setCollapsed] = useState(isComplete);
  if (activities.length === 0 && !showWhenEmpty) return null;

  const byStage = new Map(activities.map((activity) => [activity.stageId, activity]));

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
        <ol className="workflow-progress__steps" aria-live="polite">
          {STEPS.map((step, index) => {
            const activity = byStage.get(step.id);
            const status = activity?.status ?? "pending";
            return (
              <li key={step.id} className={`workflow-progress__step workflow-progress__step--${status}`}>
                <span className="workflow-progress__marker" aria-hidden="true">
                  {status === "completed" ? <CheckIcon /> : status === "failed" ? <CloseIcon /> : index + 1}
                </span>
                <span>{step.label}</span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
