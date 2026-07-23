import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ActivityEvent } from "../types/chat";
import { AgentActivity } from "./AgentActivity";

const activities: ActivityEvent[] = [
  { id: 1, stageId: "understand", type: "workflow_started", label: "Understanding your request", status: "completed" },
  { id: 2, stageId: "plan", type: "plan_created", label: "Creating a shopping plan", status: "completed" },
  { id: 3, stageId: "catalog", type: "tool_started", label: "Searching the product catalog", status: "active" },
];

describe("AgentActivity", () => {
  it("renders the compact seven-step workflow timeline", () => {
    render(<AgentActivity activities={activities} />);
    expect(screen.getByText("Understanding request")).toBeInTheDocument();
    expect(screen.getByText("Creating shopping plan")).toBeInTheDocument();
    expect(screen.getByText("Searching catalog")).toBeInTheDocument();
    expect(screen.getByText("Preparing response")).toBeInTheDocument();
    expect(screen.queryByText("Searching the product catalog")).not.toBeInTheDocument();
  });

  it("starts collapsed after completion and can be expanded", async () => {
    const user = userEvent.setup();
    render(<AgentActivity activities={activities} isComplete />);
    expect(screen.getByRole("button", { name: "Show progress" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show progress" }));
    expect(screen.getByRole("button", { name: "Hide progress" })).toBeInTheDocument();
    expect(screen.getByText("Searching catalog")).toBeInTheDocument();
  });
});
