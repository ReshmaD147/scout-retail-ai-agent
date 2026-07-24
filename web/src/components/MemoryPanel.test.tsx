import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryPanel } from "./MemoryPanel";
import type { UseMemorySettingsResult } from "../hooks/useMemorySettings";

function memory(overrides: Partial<UseMemorySettingsResult> = {}): UseMemorySettingsResult {
  return {
    preferences: [
      {
        preference_id: "pref-1",
        customer_id: "cust-1",
        type: "preferred_store",
        value: "Maple Grove",
        confidence: 1,
        source: "explicit",
        status: "active",
        created_at: "2026-07-24T00:00:00Z",
        updated_at: "2026-07-24T00:00:00Z",
        last_confirmed_at: "2026-07-24T00:00:00Z",
        expires_at: null,
      },
      {
        preference_id: "pref-2",
        customer_id: "cust-1",
        type: "width",
        value: "Wide",
        confidence: 1,
        source: "explicit",
        status: "active",
        created_at: "2026-07-24T00:00:00Z",
        updated_at: "2026-07-24T00:00:00Z",
        last_confirmed_at: "2026-07-24T00:00:00Z",
        expires_at: null,
      },
    ],
    memoryEnabled: true,
    isLoading: false,
    errorMessage: null,
    refresh: vi.fn(),
    save: vi.fn(),
    remove: vi.fn(),
    clearAll: vi.fn(),
    setEnabled: vi.fn(),
    clearSession: vi.fn(),
    ...overrides,
  };
}

describe("MemoryPanel", () => {
  it("renders saved preferences and controls", () => {
    render(<MemoryPanel memory={memory()} />);

    expect(screen.getByText("Scout memory")).toBeInTheDocument();
    expect(screen.getByText("Maple Grove")).toBeInTheDocument();
    expect(screen.getByText("Wide")).toBeInTheDocument();
    expect(screen.getByLabelText("Scout memory settings")).toHaveTextContent("Use saved preferences");
  });

  it("calls memory controls without clearing cart or saved products in React", () => {
    const state = memory();
    render(<MemoryPanel memory={state} />);

    fireEvent.click(screen.getByRole("button", { name: "Clear all remembered preferences" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear session shopping context" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);

    expect(state.clearAll).toHaveBeenCalledTimes(1);
    expect(state.clearSession).toHaveBeenCalledTimes(1);
    expect(state.remove).toHaveBeenCalledWith("pref-1");
  });
});
