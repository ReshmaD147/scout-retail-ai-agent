import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ActivityEvent } from "../types/chat";
import { AgentActivity } from "./AgentActivity";

const activities: ActivityEvent[] = [
  { id: 1, type: "workflow_started", label: "Understanding request", status: "completed" },
  { id: 2, type: "tool_started", label: "Recommendation Agent searching products", status: "completed" },
  { id: 3, type: "plan_created", label: "Creating a shopping plan", status: "completed" },
  { id: 4, type: "tool_started", label: "Preparing response", status: "active" },
];

describe("AgentActivity", () => {
  it("renders streamed workflow events without fixed placeholder steps", () => {
    render(<AgentActivity activities={activities} />);
    expect(screen.getByText("Understanding request")).toBeInTheDocument();
    expect(screen.getByText("Creating a shopping plan")).toBeInTheDocument();
    expect(screen.getByText("Recommendation Agent searching products")).toBeInTheDocument();
    expect(screen.getByText("Preparing response")).toBeInTheDocument();
    const labels = screen.getAllByText(/Understanding request|Creating a shopping plan|Recommendation Agent searching products|Preparing response/);
    expect(labels.map((label) => label.textContent)).toEqual([
      "Understanding request",
      "Creating a shopping plan",
      "Recommendation Agent searching products",
      "Preparing response",
    ]);
  });

  it("starts collapsed after completion and can be expanded", async () => {
    const user = userEvent.setup();
    render(<AgentActivity activities={activities} isComplete />);
    expect(screen.getByRole("button", { name: "Show progress" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show progress" }));
    expect(screen.getByRole("button", { name: "Hide progress" })).toBeInTheDocument();
    expect(screen.getByText("Recommendation Agent searching products")).toBeInTheDocument();
  });
});
